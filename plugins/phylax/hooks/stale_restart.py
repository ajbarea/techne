#!/usr/bin/env python3
"""Restart an idle Claude Code session onto the installed binary, keeping the conversation.

Two entry points share one safety check:

- `stale_restart.py` (no arguments) is the hook. On Notification `idle_prompt` it reads this
  session's `~/.claude/sessions/<pid>.json`, and when the session is idle and the `claude`
  on PATH is newer, it writes a plan and opens a tmux window or Windows Terminal tab running
  the handoff. On Stop it records what the turn left running (background tasks, subagents,
  session crons) and the effort and permission mode, none of which idle_prompt carries;
  UserPromptSubmit clears that record so an interrupted turn, which skips Stop, leaves none.
- `stale_restart.py handoff <plan>` runs in that window. It counts down (any key cancels),
  re-checks the session, sends SIGTERM, waits for the process to exit, then respawns the
  old tmux pane with `claude --resume <id>`, or closes the old tab's shell and resumes in
  its own window, from the session's launch directory.

It never sends SIGKILL, refuses when the pid's start time no longer matches the plan, and
closes or respawns a shell only when the old session was its one child. The session file is
undocumented Claude Code state; when a field is missing or unexpected, the check fails
closed. Runs on the system python3, so it stays compatible with 3.9.
"""

from __future__ import annotations

import errno
import json
import os
import re
import select
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

# Overridable so tests can point the check at fixture files.
SESSIONS = Path(os.environ.get("TECHNE_RESTART_SESSIONS") or Path.home() / ".claude" / "sessions")
PROC = Path(os.environ.get("TECHNE_RESTART_PROC") or "/proc")
# The bash snippet in docs/configuration.md and resume_script() build the same path.
STATE = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp") / f"phylax-restart-{os.getuid()}"
COUNTDOWN = int(os.environ.get("TECHNE_RESTART_COUNTDOWN", "15"))
TERM_WAIT = float(os.environ.get("TECHNE_RESTART_TERM_WAIT", "10"))
SHELL_WAIT = float(os.environ.get("TECHNE_RESTART_SHELL_WAIT", "3"))
# After TERM_WAIT, how much longer a handoff with no terminal waits for the exit.
LATE_WAIT = float(os.environ.get("TECHNE_RESTART_LATE_WAIT", "60"))
# A plan whose handoff never ran (the launcher failed silently) stops blocking after this.
PLAN_TTL = 600
VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")
# Session ids name state files, so anything but a plain id is ignored.
SESSION_ID_RE = re.compile(r"[A-Za-z0-9-]+")
SHELLS = {"bash", "zsh"}
MODEL_RE = re.compile(r"claude-[a-z0-9.-]+")
FAMILIES = ("opus", "sonnet", "haiku", "fable")
EFFORTS = {"low", "medium", "high", "xhigh", "max"}
MODES = {"default", "plan", "acceptEdits", "auto", "dontAsk", "bypassPermissions"}
TRANSCRIPT_TAIL = 4 << 20
# Background task statuses that mean the task has ended; any other status counts as running.
ENDED = {"completed", "failed", "killed", "cancelled", "canceled", "stopped", "error", "done"}

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
    "--allow-dangerously-skip-permissions",
    "--strict-mcp-config",
    "--chrome",
    "--ide",
    "--verbose",
}


def state_ok(path: Path) -> bool:
    """Create the state dir if needed; trust it only when it is ours and private.

    With XDG_RUNTIME_DIR unset it sits in /tmp, where another user could create it first
    and plant a plan naming the binaries the handoff runs.
    """
    try:
        os.mkdir(path, 0o700)
    except FileExistsError:
        pass
    except OSError:
        return False
    try:
        st = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISDIR(st.st_mode) and st.st_uid == os.getuid() and not st.st_mode & 0o077


def log(msg: str) -> None:
    if not state_ok(STATE):
        return
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW
    try:
        fd = os.open(STATE / "log", flags, 0o600)
        with os.fdopen(fd, "a") as f:
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


def proc_stat(pid: int) -> tuple[str, str, int, str] | None:
    """(comm, state, ppid, starttime) from /proc/<pid>/stat, or None when the pid is gone."""
    try:
        raw = (PROC / str(pid) / "stat").read_text()
    except OSError:
        return None
    head, _, rest = raw.rpartition(")")
    fields = rest.split()
    if "(" not in head or len(fields) < 20:
        return None
    # Fields after the comm start at field 3 (state); starttime is field 22.
    return head.partition("(")[2], fields[0], int(fields[1]), fields[19]


def alive(pid: int, start: str) -> bool:
    """The pid runs and is still the process that started at `start`. A zombie has exited."""
    st = proc_stat(pid)
    return st is not None and st[3] == start and st[1] != "Z"


def children(pid: int) -> list[int]:
    """Live child pids, found by scanning /proc."""
    try:
        entries = [p.name for p in PROC.iterdir() if p.name.isdigit()]
    except OSError:
        return []
    out = []
    for name in entries:
        st = proc_stat(int(name))
        if st is not None and st[2] == pid and st[1] != "Z":
            out.append(int(name))
    return out


def live_session(data: dict | None, session_id: str) -> bool:
    if not data or data.get("sessionId") != session_id:
        return False
    pid, start = data.get("pid"), data.get("procStart")
    return isinstance(pid, int) and isinstance(start, str) and alive(pid, start)


def owner() -> int:
    """The claude process that fired this hook: hooks.json execs python3, so the parent.
    A conversation can be open in two processes at once (`--resume` twice), so the session
    id alone does not say which process to act on."""
    return int(os.environ.get("TECHNE_RESTART_PARENT") or os.getppid())


def session_for(session_id: str) -> dict | None:
    """This hook's own session file, when it is live and holds this session."""
    own = read_json(SESSIONS / f"{owner()}.json")
    return own if live_session(own, session_id) else None


def send(pid: int, start: str, sig: int) -> bool:
    """Signal the process only if it is still the one that started at `start`.

    A pidfd pins the process, so the pid cannot be reused between the check and the signal.
    """
    try:
        fd = os.pidfd_open(pid)
    except (AttributeError, NotImplementedError):
        fd = None
    except OSError as exc:
        if exc.errno != errno.ENOSYS:  # kernels before 5.3, and WSL1
            return False
        fd = None
    try:
        if not alive(pid, start):
            return False
        if fd is None:
            os.kill(pid, sig)
        else:
            signal.pidfd_send_signal(fd, sig)
        return True
    except (ProcessLookupError, PermissionError):
        return False
    finally:
        if fd is not None:
            os.close(fd)


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
    return m.group(0) if m else None


def version_key(version: object) -> tuple[int, ...] | None:
    m = VERSION_RE.fullmatch(version) if isinstance(version, str) else None
    return tuple(int(g) for g in m.groups()) if m else None


def turn_path(session_id: str) -> Path:
    return STATE / f"turn-{session_id}.json"


def record_turn(event: dict, session_id: str, pid: int) -> None:
    """Keep what the Stop hook reports about the session, which idle_prompt does not carry.

    It is stamped with the claude process that ended the turn, so a second process holding
    the same conversation cannot vouch for this one.
    """
    st = proc_stat(pid)
    tasks = event.get("background_tasks")
    crons = event.get("session_crons")
    turn = {
        "pid": pid,
        "start": st[3] if st else None,
        "effort": event.get("effort"),
        "permission_mode": event.get("permission_mode"),
        # Unknown when absent, so the check refuses rather than guess there are none.
        "tasks": None
        if not isinstance(tasks, list)
        else sum(1 for t in tasks if not isinstance(t, dict) or t.get("status") not in ENDED),
        "crons": len(crons) if isinstance(crons, list) else None,
    }
    turn_path(session_id).write_text(json.dumps(turn))


def last_turn(session_id: str) -> dict:
    return read_json(turn_path(session_id)) or {}


def session_blocker(session: dict | None) -> str | None:
    """Why this session is not safe to stop now, or None. Reads files only."""
    if session is None:
        return "no live session file"
    if session.get("kind") != "interactive":
        return f"kind is {session.get('kind')!r}, not interactive"
    if session.get("status") != "idle":
        return f"status is {session.get('status')!r}, not idle"
    pid, start = session.get("pid"), session.get("procStart")
    if not (isinstance(pid, int) and isinstance(start, str) and alive(pid, start)):
        return "process gone or pid reused"
    turn = last_turn(str(session.get("sessionId")))
    if not turn:
        return "no completed turn recorded"
    if (turn.get("pid"), turn.get("start")) != (pid, start):
        return "last turn recorded by another process"
    if turn.get("tasks") != 0:
        return f"background tasks or subagents running: {turn.get('tasks')}"
    if turn.get("crons") != 0:
        # Session crons (/loop, CronCreate) live in the process and end with it.
        return f"session crons: {turn.get('crons')}"
    return None


def version_blocker(running: object, installed: str | None) -> str | None:
    have, new = version_key(running), version_key(installed)
    if have is None or new is None:
        return "version unknown"
    if new <= have:
        return "installed version is not newer"
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
        if entry.get("type") == "assistant" and isinstance(model, str):
            if MODEL_RE.fullmatch(model):
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


def families(model: str) -> set[str]:
    """The model families an id or alias can run. `opusplan` runs opus and sonnet."""
    low = model.lower()
    found = {f for f in FAMILIES if f in low}
    if "opusplan" in low:
        found.add("sonnet")
    return found


def process_env(pid: int, name: str) -> str | None:
    try:
        raw = (PROC / str(pid) / "environ").read_bytes()
    except OSError:
        return None
    prefix = name.encode() + b"="
    for item in raw.split(b"\0"):
        if item.startswith(prefix):
            return item[len(prefix) :].decode("utf-8", "surrogateescape") or None
    return None


def settings_model(flags: list[str], cwd: str) -> str | None:
    """The model a resume without --model or ANTHROPIC_MODEL starts on, from settings."""
    sources: list[dict | None] = []
    inline = flag_value(flags, "--settings")
    if inline:
        try:
            sources.append(json.loads(inline))
        except ValueError:
            sources.append(read_json(Path(cwd) / inline))
    sources += [
        read_json(Path(cwd) / ".claude" / "settings.local.json"),
        read_json(Path(cwd) / ".claude" / "settings.json"),
        read_json(Path.home() / ".claude" / "settings.json"),
    ]
    for source in sources:
        model = source.get("model") if isinstance(source, dict) else None
        if isinstance(model, str) and model:
            return model
    return None


def resume_flags(
    flags: list[str], transcript: object, turn: dict, cwd: str, env_model: str | None = None
) -> list[str]:
    """Launch flags adjusted so the resumed session runs as the old one does now.

    `/model` saves its choice as the default, so a plain resume usually lands on the right
    model and keeps aliases and `[1m]`. Only when the model a resume would pick is a
    different family from the latest reply's (another session changed the default, say)
    is the reply's exact id pinned. Effort and permission mode come from the last turn.
    """
    # The new tab starts from a login shell, not the old process's environment, so an
    # ANTHROPIC_MODEL set for that process alone is passed on as the flag it stands for.
    if env_model and not flag_value(flags, "--model"):
        flags = [*flags, "--model", env_model]
    live = last_model(transcript)
    expected = flag_value(flags, "--model") or settings_model(flags, cwd) or ""
    fallback = flag_value(flags, "--fallback-model") or ""
    live_families = families(live) if live else set()
    if live_families and not live_families & families(expected):
        # A reply from --fallback-model is a one-off, not the session's model.
        if not live_families & families(fallback):
            flags = replace_flag(flags, "--model", live or "")
    effort = turn.get("effort")
    level = effort.get("level") if isinstance(effort, dict) else None
    if level in EFFORTS:
        flags = replace_flag(flags, "--effort", level)
    mode = turn.get("permission_mode")
    if mode in MODES:
        flags = replace_flag(flags, "--permission-mode", mode)
    skip, allow = "--dangerously-skip-permissions", "--allow-dangerously-skip-permissions"
    # A launch flag would switch bypass back on. Unless the session is known to be in
    # bypass now, keep bypass one shift+tab away instead.
    if mode != "bypassPermissions":
        launch_mode = flag_value(flags, "--permission-mode")
        if skip in flags or launch_mode == "bypassPermissions":
            flags = [f for f in flags if f != skip]
            if launch_mode == "bypassPermissions":
                flags = without(flags, "--permission-mode")
            if allow not in flags:
                flags.append(allow)
    return flags


def sole_child_shell(shell_pid: int, child: int) -> dict | None:
    """The shell as {pid, start} when it is bash or zsh and `child` is its only child."""
    st = proc_stat(shell_pid)
    if st is None or st[0].lstrip("-") not in SHELLS:
        return None
    if children(shell_pid) != [child]:
        return None
    return {"pid": shell_pid, "start": st[3]}


def closable_shell(pid: int) -> dict | None:
    """The tab's top shell when this session is its only child, so closing it loses nothing.

    Under WSL a tab's login shell is a child of the distro's `Relay(...)` process. A shell
    deeper in the tree (a subshell, an editor's terminal) or one with jobs is left alone.
    """
    st = proc_stat(pid)
    shell = sole_child_shell(st[2], pid) if st else None
    parent = proc_stat(st[2]) if st else None
    grand = proc_stat(parent[2]) if parent else None
    if shell is None or grand is None or not grand[0].startswith("Relay("):
        return None
    return shell


def tmux_pane(session: dict) -> str | None:
    target = session.get("tmux")
    if not isinstance(target, str) or "." not in target:
        return None
    pane = target.rpartition(".")[2]
    return pane if pane.startswith("%") else None


def tmux_out(*args: str) -> str | None:
    try:
        proc = subprocess.run(["tmux", *args], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout.strip() if proc.returncode == 0 else None


def tmux(*args: str) -> bool:
    return tmux_out(*args) is not None


def respawnable_pane(session: dict) -> dict | None:
    """The pane to respawn in place, when the session is its first process or that
    process is a shell whose only child is the session. Anything else in the pane
    (an editor, a job, an ssh hop) would die with `respawn-pane -k`, so it is left."""
    pane, pid = tmux_pane(session), session["pid"]
    raw = tmux_out("display-message", "-p", "-t", pane, "#{pane_pid}") if pane else None
    if not raw or not raw.isdigit():
        return None
    root = int(raw)
    if root == pid:
        return {"pane": pane, "shell": None}
    st = proc_stat(pid)
    shell = sole_child_shell(root, pid) if st and st[2] == root else None
    return {"pane": pane, "shell": shell} if shell else None


def pick_launcher(session: dict) -> str | None:
    if tmux_pane(session) and shutil.which("tmux"):
        return "tmux"
    wsl = os.environ.get("WSL_DISTRO_NAME") and os.environ.get("WT_SESSION")
    if wsl and shutil.which("wt.exe"):
        return "wt"
    return None


def resume_args(plan: dict) -> list[str]:
    return [plan["claude"], "--resume", plan["sessionId"], *plan["flags"]]


def resume_script(plan: dict) -> str:
    """Shell command for the new tab or pane: resume, then stay in a login shell.

    It exits 0 instead when a later restart marked this shell for closing, which is how
    a Windows Terminal tab closes itself (closeOnExit closes only on exit code 0). The
    marker path is expanded by this shell, so it matches the state dir its session uses.
    """
    cmd = shlex.join(resume_args(plan))
    marker = '"${XDG_RUNTIME_DIR:-/tmp}/phylax-restart-$(id -u)/close-$$"'
    return f'{cmd}; if [ -e {marker} ]; then rm -f {marker}; exit 0; fi; exec "$0" -l'


def launch_argv(launcher: str, plan: dict, plan_path: Path) -> list[str] | None:
    handoff = shlex.join([sys.executable, os.path.abspath(__file__), "handoff", str(plan_path)])
    if launcher == "tmux":
        session_name = plan["tmux"].partition(":")[0]
        return [
            "tmux", "new-window", "-t", f"={session_name}:", "-n", "claude-restart",
            "-c", plan["cwd"], handoff,
        ]  # fmt: skip
    title = "claude restart: " + re.sub(r"[;\"]", "", plan.get("name") or plan["sessionId"][:8])
    argv = [
        "wt.exe", "-w", "0", "new-tab", "--title", title,
        "wsl.exe", "-d", os.environ["WSL_DISTRO_NAME"], "--cd", plan["cwd"], "--",
        plan["shell"], "-lic", f"exec {handoff}",
    ]  # fmt: skip
    # wt.exe splits its command line on `;`, so an argument holding one would start a
    # second wt command.
    return None if any(";" in a for a in argv) else argv


def take_plan_slot(session_id: str) -> Path | None:
    """Create the plan file exclusively, so only one handoff runs per session."""
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
    session_id = event.get("session_id")
    if not isinstance(session_id, str) or not SESSION_ID_RE.fullmatch(session_id):
        return 0
    if not state_ok(STATE):
        return 0
    name = event.get("hook_event_name")
    if name == "Stop":
        record_turn(event, session_id, owner())
        return 0
    if name == "UserPromptSubmit":
        # An interrupted turn skips Stop, so no record survives a turn that is under way.
        drop(turn_path(session_id))
        return 0
    if name == "SessionEnd":
        drop(turn_path(session_id))
        drop(STATE / f"notice-{session_id}")
        drop(STATE / f"declined-{session_id}")
        return 0
    if event.get("notification_type") != "idle_prompt":
        return 0
    session = session_for(session_id)
    # The file checks rule out most idle_prompts, so they run before `claude --version`.
    if session_blocker(session):
        return 0
    assert session is not None
    claude = claude_path()
    installed = installed_version(claude)
    why = version_blocker(session.get("version"), installed)
    if why:
        if why == "version unknown":
            log(f"{session_id} skip: {why}")
        return 0
    assert installed is not None and claude is not None
    if declined(session_id, installed):
        return 0
    launcher = pick_launcher(session)
    if launcher is None:
        notice = STATE / f"notice-{session_id}"
        if not notice.exists():
            notice.touch()
            emit(
                f"phylax: Claude Code {installed} is installed and this session runs "
                f"{session['version']}. restart_on_update supports tmux and Windows Terminal "
                "under WSL only, so restart this session yourself."
            )
        return 0
    plan_path = take_plan_slot(session_id)
    if plan_path is None:
        return 0
    login = os.path.basename(os.environ.get("SHELL", ""))
    cwd = session.get("cwd") or event.get("cwd") or os.getcwd()
    flags = carry_flags(session["pid"])
    plan = {
        "sessionId": session_id,
        "pid": session["pid"],
        "procStart": session["procStart"],
        "cwd": cwd,
        "name": session.get("name"),
        "version": session["version"],
        "installed": installed,
        "claude": claude,
        "flags": resume_flags(
            flags,
            event.get("transcript_path"),
            last_turn(session_id),
            cwd,
            process_env(session["pid"], "ANTHROPIC_MODEL"),
        ),
        "launcher": launcher,
        "tmux": session.get("tmux"),
        "respawn": respawnable_pane(session) if launcher == "tmux" else None,
        "closeShell": closable_shell(session["pid"]) if launcher == "wt" else None,
        "shell": (shutil.which(login) or "/bin/bash") if login in SHELLS else "/bin/bash",
    }
    plan_path.write_text(json.dumps(plan))
    argv = launch_argv(launcher, plan, plan_path)
    if argv is None:
        drop(plan_path)
        log(f"{session_id} not launched: a path holds ';', which wt.exe cannot pass")
        return 0
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
        f"phylax: moving this session from Claude Code {plan['version']} to {installed} "
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
        restore_terminal(fd, saved)


def restore_terminal(fd: int, saved: list) -> None:
    # The terminal may have hung up already (its window was closed). termios.error is not
    # an OSError, and nothing here may mask the exception that brought us here.
    try:
        import termios

        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
    except Exception as exc:
        log(f"terminal not restored: {exc}")


def wait_gone(pid: int, start: str, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while alive(pid, start):
        if time.monotonic() > deadline:
            return False
        time.sleep(0.2)
    return True


def wait_exit(pid: int, start: str) -> bool:
    """Wait for a signalled process to exit. Past TERM_WAIT, keep waiting until it does or,
    in a terminal, until a key or Ctrl-C gives up; elsewhere, or once the window has closed,
    give up after another LATE_WAIT. Ctrl-C and hangup were blocked around the signal and
    are let through here, inside the handlers' reach."""
    try:
        signal.pthread_sigmask(signal.SIG_UNBLOCK, INTERRUPTS)
        if wait_gone(pid, start, TERM_WAIT):
            return True
        if sys.stdin.isatty():
            try:
                wait_for_key(pid, start)
            except OSError:  # the window closed; the pane may still be respawned
                wait_gone(pid, start, LATE_WAIT)
        else:
            wait_gone(pid, start, LATE_WAIT)
    except Closed:
        pass
    return not alive(pid, start)


def wait_for_key(pid: int, start: str) -> None:
    import termios
    import tty

    print("The old process is still exiting. Press any key to stop waiting.")
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        while alive(pid, start):
            ready, _, _ = select.select([fd], [], [], 0.5)
            if ready:
                os.read(fd, 64)
                return
    finally:
        restore_terminal(fd, saved)


def pause(message: str) -> int:
    try:
        print(message)
        if sys.stdin.isatty():
            input("Press Enter to close. ")
    except (OSError, EOFError, Closed):
        pass
    return 1


class Abort(Exception):
    """Stop the handoff and show the message once the plan slot is freed."""


class Closed(Exception):
    """The countdown's tab or window was closed."""


def on_close(signum: int, frame: object) -> None:
    # Act on the first Ctrl-C or hangup only, so a second one cannot cut short the
    # cleanup the first one started.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    raise Closed


INTERRUPTS = {signal.SIGINT, signal.SIGHUP}
# Python ignores SIGPIPE and SIGXFSZ for itself; an exec'd shell would inherit that.
EXEC_DEFAULTS = (signal.SIGINT, signal.SIGHUP, signal.SIGPIPE, signal.SIGXFSZ)


def handoff(plan_path: Path) -> int:
    global STATE
    # The plan sits in the hook's state dir, which this tab's environment may not name.
    if not state_ok(plan_path.parent):
        return pause(f"phylax: {plan_path.parent} is not a private state directory.")
    STATE = plan_path.parent
    plan = read_json(plan_path)
    if plan is None:
        return pause(f"phylax: no restart plan at {plan_path}.")
    # Ctrl-C or closing the window raises Closed: a cancel before SIGTERM, "stop waiting"
    # while waiting for the exit, and "resume here" once the old process has gone.
    signal.signal(signal.SIGINT, on_close)
    signal.signal(signal.SIGHUP, on_close)
    try:
        return _handoff(plan, plan_path)
    except Abort as exc:
        message = str(exc)
    except Closed:
        message = "Closed before the restart. Nothing changed."
    finally:
        # Freed before any pause, so a tab left open cannot outlive PLAN_TTL and remove
        # a later handoff's plan.
        drop(plan_path)
    return pause(message)


def _handoff(plan: dict, plan_path: Path) -> int:
    sid, pid, start = plan["sessionId"], plan["pid"], plan["procStart"]
    label = plan.get("name") or sid
    print(f"phylax: moving Claude Code session '{label}'")
    print(f"from {plan['version']} to {plan['installed']}.")
    try:
        go = countdown(COUNTDOWN)
    except (Closed, OSError):  # Ctrl-C, or the window closed: a cancel, like a key
        go = False
    if not go:
        # A second Ctrl-C or the window's hangup must not cut the record short.
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGHUP, signal.SIG_IGN)
        (STATE / f"declined-{sid}").write_text(plan["installed"])
        log(f"{sid} cancelled at the countdown")
        raise Abort("Cancelled. This session stays as it is until the next update.")
    session = read_json(SESSIONS / f"{pid}.json")
    planned = (
        live_session(session, sid) and session is not None and session.get("procStart") == start
    )
    why = (
        session_blocker(session if planned else None)
        or version_blocker(plan["version"], installed_version(plan["claude"]))
        or (None if os.path.isdir(plan["cwd"]) else f"{plan['cwd']} no longer exists")
    )
    if why:
        log(f"{sid} handoff refused: {why}")
        raise Abort(f"Not restarting: {why}.")
    respawn = plan.get("respawn") or {}
    pane, rshell = respawn.get("pane"), respawn.get("shell")
    # The session is the pane's first process; keep the pane when it exits.
    first = bool(pane) and rshell is None
    if first:
        tmux("set-option", "-p", "-t", pane, "remain-on-exit", "on")
    shell = plan.get("closeShell")
    marker = STATE / f"close-{shell['pid']}" if shell else None
    # From the close marker to the signal nothing may interrupt; after it, a closed window
    # no longer stops the handoff, which can still respawn a tmux pane.
    signal.pthread_sigmask(signal.SIG_BLOCK, INTERRUPTS)
    if marker:
        marker.touch()
    sent = send(pid, start, signal.SIGTERM)
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    if not sent:
        signal.pthread_sigmask(signal.SIG_UNBLOCK, INTERRUPTS)
    # A process that exits just as the wait gives up still counts as stopped.
    if not sent or (not wait_exit(pid, start) and alive(pid, start)):
        if marker:
            drop(marker)
        if first:
            tmux("set-option", "-p", "-u", "-t", pane, "remain-on-exit")
        if sent:
            log(f"{sid} still running after SIGTERM; gave up waiting")
            raise Abort(
                "The old process has not exited. Once it does, resume it with:\n  "
                + resume_command(plan)
            )
        log(f"{sid} process {pid} was gone or replaced before SIGTERM")
        raise Abort("The old process was gone before it could be stopped. Nothing restarted.")
    # The session has ended, so from here every path resumes it. Ctrl-C and a closed window
    # no longer stop anything; resume_here() restores both before the exec.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    log(f"{sid} stopped {plan['version']} process {pid}")
    script = resume_script(plan)
    try:
        if close_old(plan, pane, rshell, first, shell, marker, script):
            return 0
    except Exception as exc:
        log(f"{sid} closing the old shell failed: {type(exc).__name__}: {exc}")
        print(f"phylax: could not tidy the old terminal ({exc}); resuming here.")
    drop(plan_path)  # exec skips handoff()'s finally
    return resume_here(plan, script)


def close_old(
    plan: dict,
    pane: str | None,
    rshell: dict | None,
    first: bool,
    shell: dict | None,
    marker: Path | None,
    script: str,
) -> bool:
    """Respawn the old tmux pane with the resume (True), or close the old tab's shell
    (False, the resume then runs here). Either only while nothing else runs there."""
    sid = plan["sessionId"]
    if pane:
        # Re-check: the shell must have gained no child since the plan was made.
        empty = rshell is None or (
            alive(rshell["pid"], rshell["start"]) and not children(rshell["pid"])
        )
        ok = empty and tmux(
            "respawn-pane", "-k", "-t", pane, "-c", plan["cwd"], plan["shell"], "-lic", script
        )
        if first:
            tmux("set-option", "-p", "-u", "-t", pane, "remain-on-exit")
        if not ok:
            print("The old pane was left as it is; resuming here instead.")
        return ok
    if shell and marker:
        if wait_gone(shell["pid"], shell["start"], SHELL_WAIT):
            log(f"{sid} old shell {shell['pid']} exited on its marker")
        elif children(shell["pid"]):
            log(f"{sid} old shell {shell['pid']} has a new child; left open")
        else:
            # No PROMPT_COMMAND snippet: the tab stays open showing the shell's exit code.
            send(shell["pid"], shell["start"], signal.SIGHUP)
            log(f"{sid} sent SIGHUP to old shell {shell['pid']}")
        drop(marker)
    return False


def resume_command(plan: dict) -> str:
    return f"cd {shlex.quote(plan['cwd'])} && {shlex.join(resume_args(plan))}"


def resume_here(plan: dict, script: str) -> int:
    """Replace this process with the resumed session, in the launch directory if it is
    still there. Falls back to /bin/bash, then to printing the command."""
    try:
        os.chdir(plan["cwd"])
    except OSError:
        os.chdir(Path.home())
        print(f"phylax: {plan['cwd']} is gone; resuming from {Path.home()}.")
    sys.stdout.flush()
    for sig in EXEC_DEFAULTS:
        signal.signal(sig, signal.SIG_DFL)
    for shell in dict.fromkeys([plan["shell"], "/bin/bash"]):
        try:
            os.execv(shell, [shell, "-lic", script])
        except OSError:
            continue
    return pause(
        "phylax: could not start a shell. Resume the session with:\n  " + resume_command(plan)
    )


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
