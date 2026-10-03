#!/usr/bin/env python3
"""Restart an idle Claude Code session onto the installed binary, keeping the conversation.

Two entry points share one safety check:

- `stale_restart.py` (no arguments) is the Notification hook. hooks.json runs it on
  `idle_prompt` once the `restart_on_update` option is on. It reads this session's
  `~/.claude/sessions/<pid>.json`, and when the session is idle and its version differs
  from the `claude` on PATH, it writes a plan and opens a tmux window or Windows Terminal
  tab running the handoff.
- `stale_restart.py handoff <plan>` runs in that window. It counts down (any key cancels),
  re-checks the session, sends SIGTERM, waits for the process to exit, closes the old
  shell, and runs `claude --resume <id>` from the session's launch directory.

The same hook also runs on Stop, to record the turn's background tasks, session crons,
effort and permission mode (idle_prompt carries none of them), and on SubagentStart and
SubagentStop, to count running subagents.

It never sends SIGKILL, and it refuses when the pid's start time no longer matches the plan.
The session file is undocumented Claude Code state; when a field is missing or unexpected,
the check fails closed. Runs on the system python3, so it stays compatible with 3.9.
"""

from __future__ import annotations

import json
import os
import re
import select
import shlex
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

# Overridable so tests can point the check at fixture files.
SESSIONS = Path(os.environ.get("TECHNE_RESTART_SESSIONS") or Path.home() / ".claude" / "sessions")
PROC = Path(os.environ.get("TECHNE_RESTART_PROC") or "/proc")
# The bash snippet in docs/configuration.md builds the same path; keep the two in step.
STATE = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp") / f"techne-restart-{os.getuid()}"
COUNTDOWN = int(os.environ.get("TECHNE_RESTART_COUNTDOWN", "15"))
TERM_WAIT = float(os.environ.get("TECHNE_RESTART_TERM_WAIT", "10"))
SHELL_WAIT = float(os.environ.get("TECHNE_RESTART_SHELL_WAIT", "3"))
# A plan whose handoff never ran (the launcher failed silently) stops blocking after this.
PLAN_TTL = 600
# A subagent marker this old is taken as left behind by a SubagentStop that never fired.
AGENT_TTL = 6 * 3600
VERSION_RE = re.compile(r"(\d+\.\d+\.\d+)")
# Session ids name state files, so anything but a plain id is ignored.
SESSION_ID_RE = re.compile(r"[A-Za-z0-9-]+")
SHELLS = {"bash", "zsh"}

MODEL_RE = re.compile(r"claude-[a-z0-9.-]+")
EFFORTS = {"low", "medium", "high", "xhigh", "max"}
MODES = {"default", "plan", "acceptEdits", "auto", "dontAsk", "bypassPermissions"}
TRANSCRIPT_TAIL = 4 << 20
# Background task statuses that mean the task has not finished.
ACTIVE = {"running", "pending"}

# Launch flags carried onto the resumed session. Session-selecting flags (--resume,
# --continue, --session-id, --fork-session, --worktree, --name) and the positional prompt
# are left out on purpose; anything not listed here is dropped.
CARRY_VALUE = {
    "--model",
    "--permission-mode",
    "--plugin-dir",
    "--settings",
    "--agent",
    "--agents",
    "--effort",
    "--setting-sources",
    "--fallback-model",
    "--system-prompt",
    "--system-prompt-file",
    "--append-system-prompt",
    "--append-system-prompt-file",
}
CARRY_VARIADIC = {
    "--add-dir",
    "--mcp-config",
    "--allowedTools",
    "--allowed-tools",
    "--disallowedTools",
    "--disallowed-tools",
}
CARRY_BOOL = {
    "--dangerously-skip-permissions",
    "--strict-mcp-config",
    "--chrome",
    "--ide",
    "--verbose",
}


def log(msg: str) -> None:
    try:
        STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
        with open(STATE / "log", "a") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except OSError:
        pass


def read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def drop(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def proc_stat(pid: int) -> tuple[str, int, str] | None:
    """(comm, ppid, starttime) from /proc/<pid>/stat, or None when the pid is gone."""
    try:
        raw = (PROC / str(pid) / "stat").read_text()
    except OSError:
        return None
    head, _, rest = raw.rpartition(")")
    fields = rest.split()
    if "(" not in head or len(fields) < 20:
        return None
    # Fields after the comm start at field 3 (state); starttime is field 22.
    return head.partition("(")[2], int(fields[1]), fields[19]


def alive(pid: int, start: str) -> bool:
    """The pid runs and is still the process that started at `start`. A zombie has exited."""
    stat = proc_stat(pid)
    if stat is None or stat[2] != start:
        return False
    try:
        state = (PROC / str(pid) / "stat").read_text().rpartition(")")[2].split()[0]
    except (OSError, IndexError):
        return False
    return state != "Z"


def session_by_id(session_id: str) -> dict | None:
    """The live interactive session file whose sessionId matches."""
    try:
        files = sorted(SESSIONS.glob("*.json"))
    except OSError:
        return None
    for path in files:
        data = read_json(path)
        if not data or data.get("sessionId") != session_id:
            continue
        pid, start = data.get("pid"), data.get("procStart")
        if isinstance(pid, int) and isinstance(start, str) and alive(pid, start):
            return data
    return None


def claude_path() -> str | None:
    found = shutil.which("claude")
    return os.path.abspath(found) if found else None


def installed_version(path: str | None) -> str | None:
    """The version the `claude` on PATH would start, without running it when possible."""
    if not path:
        return None
    real = Path(os.path.realpath(path))
    # Native installs symlink ~/.local/bin/claude to .../claude/versions/<version>.
    if real.parent.name == "versions" and VERSION_RE.fullmatch(real.name):
        return real.name
    try:
        out = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    m = VERSION_RE.search(out)
    return m.group(1) if m else None


def agents_dir(session_id: str) -> Path:
    return STATE / f"agents-{session_id}"


def running_agents(session_id: str) -> int:
    """Subagents started and not yet stopped. The session file can read idle while a
    background subagent waits on the model, so these are counted from the hooks."""
    now = time.time()
    count = 0
    try:
        for marker in agents_dir(session_id).iterdir():
            if now - marker.stat().st_mtime < AGENT_TTL:
                count += 1
    except OSError:
        pass
    return count


def track_agent(event: dict) -> None:
    session_id, agent_id = event.get("session_id"), event.get("agent_id")
    if not isinstance(session_id, str) or not SESSION_ID_RE.fullmatch(session_id):
        return
    if not isinstance(agent_id, str):
        return
    # The prefix keeps an id of "." or ".." a plain file name.
    marker = agents_dir(session_id) / ("a-" + re.sub(r"[^\w.-]", "_", agent_id))
    if event.get("hook_event_name") == "SubagentStart":
        marker.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        marker.touch()
    else:
        drop(marker)


def record_turn(event: dict) -> None:
    """Keep what the Stop hook reports about the session, which idle_prompt does not carry."""
    session_id = event.get("session_id")
    if not isinstance(session_id, str) or not SESSION_ID_RE.fullmatch(session_id):
        return
    tasks = event.get("background_tasks")
    crons = event.get("session_crons")
    state = {
        "effort": event.get("effort"),
        "permission_mode": event.get("permission_mode"),
        # Unknown when absent, so the check refuses rather than guess there are none.
        "tasks": None
        if not isinstance(tasks, list)
        else sum(1 for t in tasks if not isinstance(t, dict) or t.get("status") in ACTIVE),
        "crons": len(crons) if isinstance(crons, list) else None,
    }
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    (STATE / f"turn-{session_id}.json").write_text(json.dumps(state))


def last_turn(session_id: str) -> dict:
    return read_json(STATE / f"turn-{session_id}.json") or {}


def blocker(session: dict | None, installed: str | None) -> str | None:
    """Why this session must not be restarted now, or None when it is safe."""
    if session is None:
        return "no live session file"
    if session.get("kind") != "interactive":
        return f"kind is {session.get('kind')!r}, not interactive"
    if session.get("status") != "idle":
        return f"status is {session.get('status')!r}, not idle"
    agents = running_agents(str(session.get("sessionId")))
    if agents:
        return f"{agents} subagent(s) still running"
    turn = last_turn(str(session.get("sessionId")))
    if not turn:
        return "no turn recorded since the hook was enabled"
    if turn.get("tasks") != 0:
        return f"background tasks: {turn.get('tasks')}"
    if turn.get("crons") != 0:
        # Session crons (/loop, CronCreate) live in the process and end with it.
        return f"session crons: {turn.get('crons')}"
    running = session.get("version")
    if not running or not installed:
        return "version unknown"
    if running == installed:
        return "already on the installed version"
    pid, start = session.get("pid"), session.get("procStart")
    if not (isinstance(pid, int) and isinstance(start, str) and alive(pid, start)):
        return "process gone or pid reused"
    return None


def carry_flags(pid: int) -> list[str]:
    """The allowlisted launch flags from the running process's argv."""
    try:
        argv = (PROC / str(pid) / "cmdline").read_bytes().split(b"\0")
    except OSError:
        return []
    args = [a.decode("utf-8", "surrogateescape") for a in argv[1:] if a]
    out: list[str] = []
    i = 0
    while i < len(args):
        arg = args[i]
        name, eq, _ = arg.partition("=")
        i += 1
        if eq and name in CARRY_VALUE | CARRY_VARIADIC:
            out.append(arg)
        elif arg in CARRY_BOOL:
            out.append(arg)
        elif arg in CARRY_VALUE and i < len(args):
            out += [arg, args[i]]
            i += 1
        elif arg in CARRY_VARIADIC:
            vals = []
            while i < len(args) and not args[i].startswith("-"):
                vals.append(args[i])
                i += 1
            if vals:
                out += [arg, *vals]
    return out


def last_model(transcript: object) -> str | None:
    """The model of the session's latest reply, read from the end of its transcript."""
    if not isinstance(transcript, str):
        return None
    try:
        with open(transcript, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - TRANSCRIPT_TAIL))
            lines = f.read().splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        if b'"assistant"' not in line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        message = entry.get("message") if isinstance(entry, dict) else None
        model = message.get("model") if isinstance(message, dict) else None
        # Claude Code writes "<synthetic>" for replies it makes up itself.
        if (
            entry.get("type") == "assistant"
            and isinstance(model, str)
            and MODEL_RE.fullmatch(model)
        ):
            return model
    return None


def without(flags: list[str], name: str) -> list[str]:
    """`flags` with every `name <value>` and `name=<value>` removed."""
    out: list[str] = []
    skip = False
    for arg in flags:
        if skip:
            skip = False
        elif arg == name:
            skip = True
        elif not arg.startswith(name + "="):
            out.append(arg)
    return out


def flag_value(flags: list[str], name: str) -> str | None:
    value = None
    for i, arg in enumerate(flags):
        if arg == name and i + 1 < len(flags):
            value = flags[i + 1]
        elif arg.startswith(name + "="):
            value = arg.partition("=")[2]
    return value


def replace_flag(flags: list[str], name: str, value: str) -> list[str]:
    return [*without(flags, name), name, value]


def live_flags(flags: list[str], transcript: object, turn: dict) -> list[str]:
    """Launch flags with the model, effort and permission mode the session has now.

    `/model`, `/effort` and shift+tab change these after launch, and a resume would
    otherwise start on the launch flags or the settings default.
    """
    model = last_model(transcript)
    launched = flag_value(flags, "--model") or ""
    # The transcript's model id drops a [1m] context suffix chosen at launch, so keep that.
    if model and "[1m]" not in launched:
        flags = replace_flag(flags, "--model", model)
    effort = turn.get("effort")
    level = effort.get("level") if isinstance(effort, dict) else None
    if level in EFFORTS:
        flags = replace_flag(flags, "--effort", level)
    mode = turn.get("permission_mode")
    if mode in MODES:
        flags = replace_flag(flags, "--permission-mode", mode)
    return flags


def closable_shell(pid: int) -> dict | None:
    """The shell that owns this session's terminal tab, when it is the tab's top process.

    Under WSL a tab's login shell is a child of the distro's `Relay(...)` process. A shell
    deeper in the tree (a subshell, an editor's terminal) is left alone.
    """
    stat = proc_stat(pid)
    if stat is None:
        return None
    shell = proc_stat(stat[1])
    if shell is None or shell[0].lstrip("-") not in SHELLS:
        return None
    parent = proc_stat(shell[1])
    if parent is None or not parent[0].startswith("Relay("):
        return None
    return {"pid": stat[1], "start": shell[2]}


def tmux_pane(session: dict) -> str | None:
    target = session.get("tmux")
    if not isinstance(target, str) or "." not in target:
        return None
    pane = target.rpartition(".")[2]
    return pane if pane.startswith("%") else None


def pick_launcher(session: dict) -> str | None:
    if tmux_pane(session) and shutil.which("tmux"):
        return "tmux"
    wsl = os.environ.get("WSL_DISTRO_NAME") and os.environ.get("WT_SESSION")
    if wsl and shutil.which("wt.exe"):
        return "wt"
    return None


def resume_script(plan: dict) -> str:
    """Shell command for the new tab or pane: resume, then stay in a login shell.

    It exits 0 instead when a later restart marked this shell for closing, which is how
    a Windows Terminal tab closes itself (closeOnExit closes only on exit code 0).
    """
    cmd = shlex.join([plan["claude"], "--resume", plan["sessionId"], *plan["flags"]])
    marker = shlex.quote(str(STATE)) + "/close-$$"
    return f'{cmd}; if [ -e {marker} ]; then rm -f {marker}; exit 0; fi; exec "$0" -l'


def launch_argv(launcher: str, plan: dict, plan_path: Path) -> list[str]:
    handoff = shlex.join([sys.executable, os.path.abspath(__file__), "handoff", str(plan_path)])
    if launcher == "tmux":
        session_name = plan["tmux"].partition(":")[0]
        return [
            "tmux", "new-window", "-t", f"{session_name}:", "-n", "claude-restart",
            "-c", plan["cwd"], handoff,
        ]  # fmt: skip
    title = "claude restart: " + re.sub(r"[;\"]", "", plan.get("name") or plan["sessionId"][:8])
    return [
        "wt.exe", "-w", "0", "new-tab", "--title", title,
        "wsl.exe", "-d", os.environ["WSL_DISTRO_NAME"], "--cd", plan["cwd"], "--",
        plan["shell"], "-lic", f"exec {handoff}",
    ]  # fmt: skip


def take_plan_slot(session_id: str) -> Path | None:
    """Create the plan file exclusively, so only one handoff runs per session."""
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = STATE / f"plan-{session_id}.json"
    try:
        if time.time() - path.stat().st_mtime > PLAN_TTL:
            path.unlink()
    except OSError:
        pass
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return None
    os.close(fd)
    return path


def declined(session_id: str, installed: str) -> bool:
    try:
        return (STATE / f"declined-{session_id}").read_text().strip() == installed
    except OSError:
        return False


def emit(message: str) -> None:
    print(json.dumps({"systemMessage": message}))


def hook() -> int:
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return 0
    if not isinstance(event, dict):
        return 0
    if event.get("hook_event_name") in ("SubagentStart", "SubagentStop"):
        track_agent(event)
        return 0
    if event.get("hook_event_name") == "Stop":
        record_turn(event)
        return 0
    if event.get("notification_type") != "idle_prompt":
        return 0
    session_id = event.get("session_id")
    if not isinstance(session_id, str) or not SESSION_ID_RE.fullmatch(session_id):
        return 0
    session = session_by_id(session_id)
    claude = claude_path()
    installed = installed_version(claude)
    why = blocker(session, installed)
    if why:
        log(f"{session_id} skip: {why}")
        return 0
    assert session is not None and installed is not None and claude is not None
    if declined(session_id, installed):
        return 0
    launcher = pick_launcher(session)
    if launcher is None:
        notice = STATE / f"notice-{session_id}"
        if not notice.exists():
            STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
            notice.touch()
            emit(
                f"techne: Claude Code {installed} is installed and this session runs "
                f"{session['version']}. restart_on_update supports tmux and Windows Terminal "
                "under WSL only, so restart this session yourself."
            )
        return 0
    plan_path = take_plan_slot(session_id)
    if plan_path is None:
        return 0
    login = os.path.basename(os.environ.get("SHELL", ""))
    plan = {
        "sessionId": session_id,
        "pid": session["pid"],
        "procStart": session["procStart"],
        "cwd": session.get("cwd") or event.get("cwd") or os.getcwd(),
        "name": session.get("name"),
        "version": session["version"],
        "installed": installed,
        "claude": claude,
        "flags": live_flags(
            carry_flags(session["pid"]), event.get("transcript_path"), last_turn(session_id)
        ),
        "launcher": launcher,
        "tmux": session.get("tmux"),
        "closeShell": closable_shell(session["pid"]) if launcher == "wt" else None,
        "shell": shutil.which(login) or "/bin/bash" if login in SHELLS else "/bin/bash",
    }
    plan_path.write_text(json.dumps(plan))
    argv = launch_argv(launcher, plan, plan_path)
    try:
        rc = subprocess.run(
            argv, stdin=subprocess.DEVNULL, capture_output=True, timeout=15, start_new_session=True
        ).returncode
    except (OSError, subprocess.SubprocessError) as exc:
        rc = f"{type(exc).__name__}: {exc}"
    if rc != 0:
        drop(plan_path)
        log(f"{session_id} launcher {launcher} failed: {rc}")
        return 0
    log(f"{session_id} handoff launched via {launcher}: {plan['version']} -> {installed}")
    where = "a new tmux window" if launcher == "tmux" else "a new tab"
    emit(
        f"techne: moving this session from Claude Code {plan['version']} to {installed} "
        f"in {where} in {COUNTDOWN}s. Press any key there to cancel."
    )
    return 0


def countdown(seconds: int) -> bool:
    """True when the countdown ran out, False when a key cancelled it."""
    if seconds <= 0:
        return True
    if not sys.stdin.isatty():
        time.sleep(seconds)
        return True
    import termios
    import tty

    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        for left in range(seconds, 0, -1):
            print(f"\r  Restarting in {left:2d}s. Press any key to cancel.", end="", flush=True)
            ready, _, _ = select.select([fd], [], [], 1)
            if ready:
                os.read(fd, 64)
                print()
                return False
        print()
        return True
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)


def wait_gone(pid: int, start: str, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while alive(pid, start):
        if time.monotonic() > deadline:
            return False
        time.sleep(0.2)
    return True


def tmux(*args: str) -> bool:
    return subprocess.run(["tmux", *args], capture_output=True).returncode == 0


def pause(message: str) -> int:
    print(message)
    if sys.stdin.isatty():
        input("Press Enter to close. ")
    return 1


def handoff(plan_path: Path) -> int:
    plan = read_json(plan_path)
    if plan is None:
        return pause(f"techne: no restart plan at {plan_path}.")
    try:
        return _handoff(plan, plan_path)
    finally:
        drop(plan_path)


def _handoff(plan: dict, plan_path: Path) -> int:
    sid, pid, start = plan["sessionId"], plan["pid"], plan["procStart"]
    label = plan.get("name") or sid
    print(f"techne: moving Claude Code session '{label}'")
    print(f"from {plan['version']} to {plan['installed']}.")
    if not countdown(COUNTDOWN):
        STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
        (STATE / f"declined-{sid}").write_text(plan["installed"])
        log(f"{sid} cancelled at the countdown")
        return pause("Cancelled. This session stays as it is until the next update.")
    session = read_json(SESSIONS / f"{pid}.json")
    if session is not None and session.get("sessionId") != sid:
        session = None
    if session is not None and session.get("procStart") != start:
        session = None
    why = blocker(session, installed_version(plan["claude"]))
    if why:
        log(f"{sid} handoff refused: {why}")
        return pause(f"Not restarting: {why}.")
    pane = tmux_pane(plan) if plan["launcher"] == "tmux" else None
    if pane:
        # Keeps the pane when claude is its first process, so it can be respawned.
        tmux("set-option", "-p", "-t", pane, "remain-on-exit", "on")
    shell = plan.get("closeShell")
    marker = STATE / f"close-{shell['pid']}" if shell else None
    if marker:
        marker.touch()
    os.kill(pid, signal.SIGTERM)
    if not wait_gone(pid, start, TERM_WAIT):
        if marker:
            drop(marker)
        if pane:
            tmux("set-option", "-p", "-u", "-t", pane, "remain-on-exit")
        log(f"{sid} did not exit within {TERM_WAIT}s of SIGTERM")
        return pause(f"The old process did not exit within {TERM_WAIT:.0f}s. It was left running.")
    log(f"{sid} stopped {plan['version']} process {pid}")
    script = resume_script(plan)
    if pane:
        respawn = ["respawn-pane", "-k", "-t", pane, "-c", plan["cwd"]]
        ok = tmux(*respawn, plan["shell"], "-lic", script)
        tmux("set-option", "-p", "-u", "-t", pane, "remain-on-exit")
        if ok:
            return 0
        print("tmux could not respawn the old pane; resuming here instead.")
    elif shell and marker:
        if wait_gone(shell["pid"], shell["start"], SHELL_WAIT):
            log(f"{sid} old shell {shell['pid']} exited on its marker")
        else:
            # No PROMPT_COMMAND snippet: the tab stays open showing the shell's exit code.
            os.kill(shell["pid"], signal.SIGHUP)
            log(f"{sid} sent SIGHUP to old shell {shell['pid']}")
        drop(marker)
    # exec skips handoff()'s finally, so free the slot here.
    drop(plan_path)
    os.chdir(plan["cwd"])
    os.execv(plan["shell"], [plan["shell"], "-lic", script])
    return 0  # unreachable


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[1] == "handoff":
        return handoff(Path(argv[2]))
    if len(argv) == 1:
        try:
            return hook()
        except Exception as exc:  # A hook must never break the session.
            log(f"hook error: {type(exc).__name__}: {exc}")
            return 0
    print("usage: stale_restart.py [handoff <plan>]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
