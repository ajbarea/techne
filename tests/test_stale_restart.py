"""Tests for the opt-in restart_on_update hook in plugins/techne/hooks/stale_restart.py.

The safety check is tested in process against fixture session files and a fake /proc.
The hook and the handoff run as subprocesses, the way Claude Code and the launcher run
them, with stub `claude`, `tmux` and shell executables on PATH. Handoff cases signal real
child processes, since sending SIGTERM to the right pid, and nothing else, is the point.
"""

from __future__ import annotations

import json
import os
import pathlib
import pty
import signal
import subprocess
import sys
import time

import pytest
from conftest import _load

ROOT = pathlib.Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "plugins" / "techne"
SCRIPT = PLUGIN / "hooks" / "stale_restart.py"
HOOKS_JSON = PLUGIN / "hooks" / "hooks.json"
MANIFEST = PLUGIN / ".claude-plugin" / "plugin.json"
OPTION = "restart_on_update"

# The hook runs on the user's system python3; `make test-hooks-oldest` sets this to 3.9.
HOOK_PYTHON = os.environ.get("TECHNE_GUARD_PYTHON", sys.executable)

OLD, NEW = "2.1.287", "2.1.288"
SID = "11111111-2222-3333-4444-555555555555"


@pytest.fixture(scope="module")
def sr():
    return _load("techne_stale_restart", SCRIPT)


def write_stat(proc: pathlib.Path, pid: int, comm: str, ppid: int, start: str) -> None:
    d = proc / str(pid)
    d.mkdir(parents=True, exist_ok=True)
    # Fields 3..21 between ppid and starttime are irrelevant to the hook.
    fields = [str(pid), f"({comm})", "S", str(ppid)] + ["0"] * 17 + [start, "0", "0"]
    (d / "stat").write_text(" ".join(fields) + "\n")


def write_cmdline(proc: pathlib.Path, pid: int, argv: list[str]) -> None:
    (proc / str(pid) / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")


def real_start(pid: int) -> str:
    return pathlib.Path(f"/proc/{pid}/stat").read_text().rpartition(")")[2].split()[19]


def session(pid: int, start: str, **over) -> dict:
    data = {
        "pid": pid,
        "sessionId": SID,
        "cwd": "/work",
        "procStart": start,
        "version": OLD,
        "kind": "interactive",
        "status": "idle",
        "name": "probe",
    }
    data.update(over)
    return data


@pytest.fixture
def env(tmp_path, sr, monkeypatch):
    """Fixture dirs, the module pointed at them, and an environment for subprocesses."""
    sessions, proc, runtime, bin_ = (tmp_path / n for n in ("sessions", "proc", "run", "bin"))
    for d in (sessions, proc, runtime, bin_):
        d.mkdir()
    versions = tmp_path / "share" / "claude" / "versions"
    versions.mkdir(parents=True)
    stub(versions / NEW, 'echo "$@" >> "$STUB_LOG"')
    (bin_ / "claude").symlink_to(versions / NEW)
    state = runtime / f"techne-restart-{os.getuid()}"
    monkeypatch.setattr(sr, "SESSIONS", sessions)
    monkeypatch.setattr(sr, "PROC", proc)
    monkeypatch.setattr(sr, "STATE", state)
    sub = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("CLAUDE_PLUGIN_OPTION_", "TMUX", "WT_", "WSL_"))
    }
    sub.update(
        PATH=f"{bin_}:/usr/bin:/bin",
        TECHNE_RESTART_SESSIONS=str(sessions),
        TECHNE_RESTART_PROC=str(proc),
        XDG_RUNTIME_DIR=str(runtime),
        TECHNE_RESTART_COUNTDOWN="0",
        TECHNE_RESTART_TERM_WAIT="3",
        TECHNE_RESTART_SHELL_WAIT="1",
        STUB_LOG=str(tmp_path / "stub.log"),
        SHELL="/bin/bash",
    )
    return {
        "sessions": sessions,
        "proc": proc,
        "bin": bin_,
        "state": state,
        "env": sub,
        "log": tmp_path / "stub.log",
        "tmp": tmp_path,
    }


def stub(path: pathlib.Path, body: str) -> pathlib.Path:
    path.write_text(f"#!/bin/sh\n{body}\n")
    path.chmod(0o755)
    return path


def calls(env) -> list[str]:
    return env["log"].read_text().splitlines() if env["log"].exists() else []


def put_session(env, data: dict) -> None:
    (env["sessions"] / f"{data['pid']}.json").write_text(json.dumps(data))


# --- the safety check ----------------------------------------------------------


QUIET_TURN = {
    "hook_event_name": "Stop",
    "session_id": SID,
    "background_tasks": [],
    "session_crons": [],
}


@pytest.fixture
def live(env, sr):
    """A fake live claude process 4242 with start time 777, after a quiet turn."""
    write_stat(env["proc"], 4242, "claude", 4000, "777")
    sr.record_turn(QUIET_TURN)
    return session(4242, "777")


def test_blocker_passes_an_idle_stale_interactive_session(sr, live):
    assert sr.blocker(live, NEW) is None


@pytest.mark.parametrize(
    ("over", "installed", "reason"),
    [
        ({"kind": "bg"}, NEW, "not interactive"),
        ({"status": "busy"}, NEW, "not idle"),
        ({"status": "shell"}, NEW, "not idle"),
        ({"status": None}, NEW, "not idle"),
        ({"version": NEW}, NEW, "already on the installed version"),
        ({}, None, "version unknown"),
        ({"version": None}, NEW, "version unknown"),
        ({"procStart": "778"}, NEW, "pid reused"),
        ({"pid": 4243}, NEW, "pid reused"),
        ({"pid": "4242"}, NEW, "pid reused"),
    ],
)
def test_blocker_refuses(sr, live, over, installed, reason):
    live.update(over)
    assert reason in sr.blocker(live, installed)


def test_blocker_refuses_a_missing_session(sr):
    assert sr.blocker(None, NEW) == "no live session file"


def test_blocker_counts_subagents_until_they_stop(sr, live):
    start = {"hook_event_name": "SubagentStart", "session_id": SID, "agent_id": "a/1"}
    sr.track_agent(start)
    sr.track_agent({**start, "agent_id": "a2"})
    assert sr.blocker(live, NEW) == "2 subagent(s) still running"
    sr.track_agent({**start, "hook_event_name": "SubagentStop"})
    sr.track_agent({**start, "hook_event_name": "SubagentStop", "agent_id": "a2"})
    assert sr.blocker(live, NEW) is None


def test_stale_subagent_marker_expires(sr, live):
    sr.track_agent({"hook_event_name": "SubagentStart", "session_id": SID, "agent_id": "x"})
    marker = sr.agents_dir(SID) / "a-x"
    old = time.time() - sr.AGENT_TTL - 1
    os.utime(marker, (old, old))
    assert sr.blocker(live, NEW) is None


def test_session_by_id_skips_dead_and_reused_pids(sr, env, live):
    put_session(env, session(4241, "1"))  # no /proc entry
    write_stat(env["proc"], 4240, "claude", 1, "9")
    put_session(env, session(4240, "8"))  # start time differs
    assert sr.session_by_id(SID) is None
    put_session(env, live)
    assert sr.session_by_id(SID)["pid"] == 4242
    assert sr.session_by_id("other") is None


def test_installed_version_reads_the_native_symlink(sr, env):
    assert sr.installed_version(str(env["bin"] / "claude")) == NEW


def test_installed_version_falls_back_to_running_it(sr, env):
    other = stub(env["tmp"] / "claude-npm", 'echo "2.1.300 (Claude Code)"')
    assert sr.installed_version(str(other)) == "2.1.300"
    assert sr.installed_version(None) is None


def test_carry_flags_keeps_the_allowlist_only(sr, env):
    write_stat(env["proc"], 4242, "claude", 1, "1")
    argv = [
        "claude",
        "--model",
        "opus",
        "--resume",
        "old-id",
        "-c",
        "--plugin-dir",
        "/a b",
        "--plugin-dir=/c",
        "--add-dir",
        "/x",
        "/y",
        "--verbose",
        "--worktree",
        "wt",
        "-n",
        "name",
        "--settings=s.json",
        "--session-id",
        "abc",
        "--mcp-config",
        "m.json",
        "--dangerously-skip-permissions",
        "fix the bug",
    ]
    write_cmdline(env["proc"], 4242, argv)
    assert sr.carry_flags(4242) == [
        "--model",
        "opus",
        "--plugin-dir",
        "/a b",
        "--plugin-dir=/c",
        "--add-dir",
        "/x",
        "/y",
        "--verbose",
        "--settings=s.json",
        "--mcp-config",
        "m.json",
        "--dangerously-skip-permissions",
    ]


def test_carry_flags_drops_a_trailing_value_flag(sr, env):
    write_stat(env["proc"], 4242, "claude", 1, "1")
    write_cmdline(env["proc"], 4242, ["claude", "--add-dir", "--model"])
    assert sr.carry_flags(4242) == []
    assert sr.carry_flags(9999) == []


@pytest.mark.parametrize(
    ("chain", "closable"),
    [
        ([("bash", 1), ("Relay(10)", 1)], True),
        ([("-bash", 1), ("Relay(10)", 1)], True),
        ([("zsh", 1), ("Relay(10)", 1)], True),
        ([("bash", 1), ("bash", 1)], False),  # a nested shell
        ([("python3", 1), ("Relay(10)", 1)], False),
        ([("fish", 1), ("Relay(10)", 1)], False),
    ],
)
def test_closable_shell_only_takes_a_tabs_top_shell(sr, env, chain, closable):
    write_stat(env["proc"], 4242, "claude", 300, "1")
    (shell_comm, _), (parent_comm, _) = chain
    write_stat(env["proc"], 300, shell_comm, 200, "55")
    write_stat(env["proc"], 200, parent_comm, 1, "5")
    got = sr.closable_shell(4242)
    assert (got == {"pid": 300, "start": "55"}) if closable else got is None


@pytest.mark.parametrize(
    ("value", "pane"),
    [("main:@0.%3", "%3"), ("a.b:@1.%12", "%12"), ("main:@0", None), (None, None), ("x.y", None)],
)
def test_tmux_pane(sr, value, pane):
    assert sr.tmux_pane({"tmux": value}) == pane


def test_resume_script_quotes_and_closes_on_marker(sr):
    plan = {"claude": "/bin/claude", "sessionId": SID, "flags": ["--plugin-dir", "/a b"]}
    script = sr.resume_script(plan)
    assert script.startswith(f"/bin/claude --resume {SID} --plugin-dir '/a b'; ")
    assert f"{sr.STATE}/close-$$" in script
    assert script.endswith('exec "$0" -l')


def test_wt_launch_argv_strips_separators_from_the_title(sr, monkeypatch, tmp_path):
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
    plan = {"name": 'a;b"c', "sessionId": SID, "cwd": "/w d", "shell": "/bin/bash"}
    argv = sr.launch_argv("wt", plan, tmp_path / "plan.json")
    assert argv[:6] == ["wt.exe", "-w", "0", "new-tab", "--title", "claude restart: abc"]
    assert argv[6:12] == ["wsl.exe", "-d", "Ubuntu", "--cd", "/w d", "--"]
    assert argv[12:14] == ["/bin/bash", "-lic"]
    assert argv[14].startswith("exec ") and argv[14].endswith(f"handoff {tmp_path}/plan.json")


def test_tmux_launch_argv_opens_a_window_in_the_same_session(sr, tmp_path):
    plan = {"tmux": "work:@2.%7", "cwd": "/w"}
    argv = sr.launch_argv("tmux", plan, tmp_path / "p.json")
    assert argv[:8] == ["tmux", "new-window", "-t", "work:", "-n", "claude-restart", "-c", "/w"]
    assert argv[-1].endswith(f"handoff {tmp_path}/p.json")


# --- the hook, as Claude Code runs it ------------------------------------------


def run_hook(env, event: dict, extra_env: dict | None = None) -> dict | None:
    proc = subprocess.run(
        [HOOK_PYTHON, str(SCRIPT)],
        input=json.dumps(event),
        capture_output=True,
        text=True,
        env={**env["env"], **(extra_env or {})},
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stderr == ""
    return json.loads(proc.stdout) if proc.stdout.strip() else None


IDLE = {"hook_event_name": "Notification", "notification_type": "idle_prompt", "session_id": SID}


@pytest.fixture
def tmux_env(env, live):
    """A stale idle session in tmux pane %3, with a stub tmux that logs its argv."""
    stub(env["bin"] / "tmux", 'echo "tmux $*" >> "$STUB_LOG"')
    live["tmux"] = "work:@0.%3"
    put_session(env, live)
    write_cmdline(env["proc"], 4242, ["claude", "--model", "opus", "hello"])
    return env


def test_hook_launches_one_handoff_and_says_so(tmux_env):
    out = run_hook(tmux_env, IDLE)
    assert out is not None
    assert "a new tmux window" in out["systemMessage"]
    (call,) = calls(tmux_env)
    assert call.startswith("tmux new-window -t work: -n claude-restart -c /work ")
    plan = json.loads((tmux_env["state"] / f"plan-{SID}.json").read_text())
    assert plan["flags"] == ["--model", "opus"]
    assert plan["closeShell"] is None and plan["launcher"] == "tmux"
    assert (plan["version"], plan["installed"]) == (OLD, NEW)
    # A second idle_prompt while the handoff is pending launches nothing.
    assert run_hook(tmux_env, IDLE) is None
    assert len(calls(tmux_env)) == 1


def test_hook_ignores_other_notifications_and_busy_sessions(tmux_env, live):
    assert run_hook(tmux_env, {**IDLE, "notification_type": "permission_prompt"}) is None
    put_session(tmux_env, {**live, "status": "busy"})
    assert run_hook(tmux_env, IDLE) is None
    assert calls(tmux_env) == []
    assert "skip: status is 'busy'" in (tmux_env["state"] / "log").read_text()


def test_hook_respects_a_cancel_for_the_same_version_only(tmux_env):
    tmux_env["state"].mkdir(parents=True, exist_ok=True)
    (tmux_env["state"] / f"declined-{SID}").write_text(NEW)
    assert run_hook(tmux_env, IDLE) is None
    (tmux_env["state"] / f"declined-{SID}").write_text("2.1.250")
    assert run_hook(tmux_env, IDLE) is not None


def test_hook_frees_the_slot_when_the_launcher_fails(tmux_env):
    stub(tmux_env["bin"] / "tmux", "exit 1")
    assert run_hook(tmux_env, IDLE) is None
    assert not (tmux_env["state"] / f"plan-{SID}.json").exists()
    assert "launcher tmux failed: 1" in (tmux_env["state"] / "log").read_text()


def test_hook_reclaims_an_expired_slot(tmux_env, sr):
    tmux_env["state"].mkdir(parents=True, exist_ok=True)
    plan = tmux_env["state"] / f"plan-{SID}.json"
    plan.write_text("{}")
    old = time.time() - sr.PLAN_TTL - 1
    os.utime(plan, (old, old))
    assert run_hook(tmux_env, IDLE) is not None


def test_hook_notices_an_unsupported_terminal_once(env, live):
    put_session(env, live)
    first = run_hook(env, IDLE)
    assert first is not None
    assert "supports tmux and Windows Terminal" in first["systemMessage"]
    assert run_hook(env, IDLE) is None


def test_hook_picks_windows_terminal_under_wsl(env, live):
    stub(env["bin"] / "wt.exe", 'echo "wt $*" >> "$STUB_LOG"')
    write_stat(env["proc"], 4242, "claude", 300, "777")
    write_stat(env["proc"], 300, "bash", 200, "55")
    write_stat(env["proc"], 200, "Relay(300)", 1, "5")
    put_session(env, live)
    out = run_hook(env, IDLE, {"WSL_DISTRO_NAME": "Ubuntu", "WT_SESSION": "x"})
    assert out is not None
    assert "a new tab" in out["systemMessage"]
    (call,) = calls(env)
    assert call.startswith("wt -w 0 new-tab --title claude restart: probe wsl.exe -d Ubuntu")
    plan = json.loads((env["state"] / f"plan-{SID}.json").read_text())
    assert plan["closeShell"] == {"pid": 300, "start": "55"}


def test_hook_tracks_subagents(env, live):
    stub(env["bin"] / "tmux", 'echo "tmux $*" >> "$STUB_LOG"')
    put_session(env, {**live, "tmux": "w:@0.%1"})
    start = {"hook_event_name": "SubagentStart", "session_id": SID, "agent_id": "ag1"}
    assert run_hook(env, start) is None
    assert run_hook(env, IDLE) is None
    assert run_hook(env, {**start, "hook_event_name": "SubagentStop"}) is None
    assert run_hook(env, IDLE) is not None


@pytest.mark.parametrize(
    "payload",
    [
        "",
        "[]",
        "not json",
        '{"session_id": 5, "notification_type": "idle_prompt"}',
        '{"session_id": "../x", "notification_type": "idle_prompt"}',
        '{"session_id": "../x", "hook_event_name": "SubagentStart", "agent_id": ".."}',
    ],
)
def test_hook_tolerates_bad_input(env, payload):
    proc = subprocess.run(
        [HOOK_PYTHON, str(SCRIPT)], input=payload, capture_output=True, text=True, env=env["env"]
    )
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, "", "")


# --- hooks.json and the manifest -----------------------------------------------


def _handlers(event: str) -> list[dict]:
    config = json.loads(HOOKS_JSON.read_text())
    return [h for group in config["hooks"][event] for h in group["hooks"]]


def test_hooks_json_wires_the_option_to_its_events():
    config = json.loads(HOOKS_JSON.read_text())
    assert config["hooks"]["Notification"][0]["matcher"] == "idle_prompt"
    for event in ("Notification", "Stop", "SubagentStart", "SubagentStop"):
        (handler,) = _handlers(event)
        assert f"$CLAUDE_PLUGIN_OPTION_{OPTION.upper()}" in handler["command"]
        assert '"${CLAUDE_PLUGIN_ROOT}/hooks/stale_restart.py"' in handler["command"]


def test_hooks_json_skips_python_when_off(tmp_path):
    (handler,) = _handlers("Notification")
    shell = handler["command"].replace("${CLAUDE_PLUGIN_ROOT}", str(PLUGIN))
    empty = tmp_path / "bin"
    empty.mkdir()
    proc = subprocess.run(
        ["/bin/sh", "-c", shell],
        input="{}",
        capture_output=True,
        text=True,
        env={"PATH": str(empty)},
    )
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, "", "")


def test_manifest_option_defaults_off():
    spec = json.loads(MANIFEST.read_text())["userConfig"][OPTION]
    assert (spec["type"], spec["default"]) == ("boolean", False)


# --- the handoff ---------------------------------------------------------------


@pytest.fixture
def old_claude(env):
    """A real process standing in for the stale claude, with its real start time."""
    child = subprocess.Popen(["sleep", "60"])
    yield child
    if child.poll() is None:
        child.kill()
        child.wait()


def write_plan(env, child_pid: int, **over) -> pathlib.Path:
    shell = stub(env["tmp"] / "shell", 'echo "shell $*" >> "$STUB_LOG"')
    plan = {
        "sessionId": SID,
        "pid": child_pid,
        "procStart": real_start(child_pid),
        "cwd": str(env["tmp"]),
        "name": "probe",
        "version": OLD,
        "installed": NEW,
        "claude": str(env["bin"] / "claude"),
        "flags": ["--model", "opus"],
        "launcher": "wt",
        "tmux": None,
        "closeShell": None,
        "shell": str(shell),
    }
    plan.update(over)
    env["state"].mkdir(parents=True, exist_ok=True)
    path = env["state"] / f"plan-{SID}.json"
    path.write_text(json.dumps(plan))
    return path


def run_handoff(env, plan: pathlib.Path, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(
        [HOOK_PYTHON, str(SCRIPT), "handoff", str(plan)],
        capture_output=True,
        text=True,
        env={**env["env"], "TECHNE_RESTART_PROC": "/proc"},
        stdin=subprocess.DEVNULL,
        timeout=30,
        **kw,
    )


def put_real_session(env, child, **over) -> None:
    put_session(env, session(child.pid, real_start(child.pid), **over))
    env["state"].mkdir(parents=True, exist_ok=True)
    (env["state"] / f"turn-{SID}.json").write_text(json.dumps({"tasks": 0, "crons": 0}))


def test_handoff_stops_the_old_process_and_resumes(env, old_claude):
    put_real_session(env, old_claude)
    plan = write_plan(env, old_claude.pid)
    proc = run_handoff(env, plan)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert old_claude.wait(timeout=5) == -signal.SIGTERM
    (call,) = calls(env)
    assert call.startswith(f"shell -lic {env['bin']}/claude --resume {SID} --model opus; ")
    assert not plan.exists()


@pytest.mark.parametrize(
    "over",
    [{"status": "busy"}, {"status": "shell"}, {"version": NEW}, {"sessionId": "other"}],
)
def test_handoff_rechecks_before_signalling(env, old_claude, over):
    put_real_session(env, old_claude, **over)
    proc = run_handoff(env, write_plan(env, old_claude.pid))
    assert proc.returncode == 1
    assert "Not restarting" in proc.stdout
    assert old_claude.poll() is None
    assert calls(env) == []


def test_handoff_refuses_a_reused_pid(env, old_claude):
    put_real_session(env, old_claude)
    proc = run_handoff(env, write_plan(env, old_claude.pid, procStart="1"))
    assert proc.returncode == 1
    assert old_claude.poll() is None


def test_handoff_never_escalates_past_sigterm(env):
    child = subprocess.Popen(["bash", "-c", "trap '' TERM; sleep 60 & wait"])
    try:
        time.sleep(0.3)
        put_real_session(env, child)
        proc = run_handoff(env, write_plan(env, child.pid))
        assert proc.returncode == 1
        assert "left running" in proc.stdout
        assert child.poll() is None
        assert calls(env) == []
    finally:
        child.kill()
        child.wait()


def test_handoff_closes_the_old_shell_that_ignores_the_marker(env, old_claude):
    shell = subprocess.Popen(["sleep", "60"])
    try:
        put_real_session(env, old_claude)
        close = {"pid": shell.pid, "start": real_start(shell.pid)}
        proc = run_handoff(env, write_plan(env, old_claude.pid, closeShell=close))
        assert proc.returncode == 0, proc.stdout
        assert shell.wait(timeout=5) == -signal.SIGHUP
        assert not (env["state"] / f"close-{shell.pid}").exists()
    finally:
        if shell.poll() is None:
            shell.kill()


def test_handoff_lets_a_snippet_shell_exit_on_its_own(env, old_claude):
    marker_dir = env["state"]
    marker_dir.mkdir(parents=True, exist_ok=True)
    # Mirrors the PROMPT_COMMAND snippet: exit 0 once the marker for this pid appears.
    shell = subprocess.Popen(
        ["bash", "-c", f'while [ ! -e "{marker_dir}/close-$$" ]; do sleep 0.05; done; exit 0']
    )
    try:
        put_real_session(env, old_claude)
        close = {"pid": shell.pid, "start": real_start(shell.pid)}
        proc = run_handoff(env, write_plan(env, old_claude.pid, closeShell=close))
        assert proc.returncode == 0, proc.stdout
        assert shell.wait(timeout=5) == 0
    finally:
        if shell.poll() is None:
            shell.kill()


def test_handoff_respawns_the_tmux_pane(env, old_claude):
    stub(env["bin"] / "tmux", 'echo "tmux $*" >> "$STUB_LOG"')
    put_real_session(env, old_claude, tmux="w:@0.%9")
    plan = write_plan(env, old_claude.pid, launcher="tmux", tmux="w:@0.%9")
    proc = run_handoff(env, plan)
    assert proc.returncode == 0, proc.stdout
    on, respawn, off = calls(env)
    assert on == "tmux set-option -p -t %9 remain-on-exit on"
    assert respawn.startswith(f"tmux respawn-pane -k -t %9 -c {env['tmp']} ")
    assert f"--resume {SID} --model opus" in respawn
    assert off == "tmux set-option -p -u -t %9 remain-on-exit"


def test_handoff_cancel_is_remembered(env, old_claude):
    put_real_session(env, old_claude)
    plan = write_plan(env, old_claude.pid)
    master, slave = pty.openpty()
    try:
        proc = subprocess.Popen(
            [HOOK_PYTHON, str(SCRIPT), "handoff", str(plan)],
            stdin=slave,
            stdout=slave,
            stderr=slave,
            env={**env["env"], "TECHNE_RESTART_PROC": "/proc", "TECHNE_RESTART_COUNTDOWN": "20"},
        )
        time.sleep(1)
        os.write(master, b"x")
        time.sleep(0.5)
        os.write(master, b"\n")
        assert proc.wait(timeout=10) == 1
    finally:
        os.close(master)
        os.close(slave)
    assert old_claude.poll() is None
    assert (env["state"] / f"declined-{SID}").read_text() == NEW
    assert calls(env) == []


# --- the session's live model, effort and permission mode ----------------------


def write_transcript(path: pathlib.Path, models: list[str]) -> pathlib.Path:
    lines = [json.dumps({"type": "user", "message": {"role": "user", "content": "hi"}})]
    for m in models:
        lines.append(json.dumps({"type": "assistant", "message": {"model": m, "content": []}}))
    lines.append(json.dumps({"type": "system", "content": "assistant"}))
    path.write_text("\n".join(lines) + "\n")
    return path


def test_last_model_takes_the_latest_real_reply(sr, tmp_path):
    t = write_transcript(
        tmp_path / "t.jsonl", ["claude-haiku-4-5", "claude-opus-5-5", "<synthetic>"]
    )
    assert sr.last_model(str(t)) == "claude-opus-5-5"
    assert sr.last_model(str(tmp_path / "missing.jsonl")) is None
    assert sr.last_model(None) is None


def test_live_flags_override_launch_flags(sr, tmp_path):
    t = write_transcript(tmp_path / "t.jsonl", ["claude-opus-5-5"])
    turn = {"effort": {"level": "xhigh"}, "permission_mode": "plan"}
    flags = ["--model", "haiku", "--effort=low", "--verbose", "--permission-mode", "default"]
    assert sr.live_flags(flags, str(t), turn) == [
        "--verbose",
        "--model",
        "claude-opus-5-5",
        "--effort",
        "xhigh",
        "--permission-mode",
        "plan",
    ]


def test_live_flags_keep_a_1m_launch_model_and_ignore_bad_values(sr, tmp_path):
    t = write_transcript(tmp_path / "t.jsonl", ["claude-opus-5-5"])
    turn = {"effort": {"level": "ludicrous"}, "permission_mode": "x"}
    assert sr.live_flags(["--model", "opus[1m]"], str(t), turn) == ["--model", "opus[1m]"]
    assert sr.live_flags([], None, {}) == []


def test_hook_plan_carries_the_live_model_effort_and_mode(tmux_env):
    t = write_transcript(tmux_env["tmp"] / "t.jsonl", ["claude-opus-5-5"])
    turn = {**QUIET_TURN, "effort": {"level": "high"}, "permission_mode": "bypassPermissions"}
    assert run_hook(tmux_env, turn) is None
    assert run_hook(tmux_env, {**IDLE, "transcript_path": str(t)}) is not None
    plan = json.loads((tmux_env["state"] / f"plan-{SID}.json").read_text())
    assert plan["flags"] == [
        "--model",
        "claude-opus-5-5",
        "--effort",
        "high",
        "--permission-mode",
        "bypassPermissions",
    ]


@pytest.mark.parametrize(
    ("turn", "reason"),
    [
        ({"background_tasks": [{"status": "running"}]}, "background tasks: 1"),
        ({"background_tasks": [{"status": "completed"}, "?"]}, "background tasks: 1"),
        ({"session_crons": [{"id": "c1"}]}, "session crons: 1"),
        ({"background_tasks": None}, "background tasks: None"),
        ({"session_crons": "x"}, "session crons: None"),
    ],
)
def test_blocker_refuses_after_a_busy_turn(sr, live, turn, reason):
    sr.record_turn({**QUIET_TURN, **turn})
    assert sr.blocker(live, NEW) == reason


def test_blocker_needs_a_recorded_turn(sr, live):
    (sr.STATE / f"turn-{SID}.json").unlink()
    assert sr.blocker(live, NEW) == "no turn recorded since the hook was enabled"


def test_blocker_clears_once_tasks_finish(sr, live):
    sr.record_turn({**QUIET_TURN, "background_tasks": [{"status": "running"}]})
    assert sr.blocker(live, NEW) is not None
    sr.record_turn({**QUIET_TURN, "background_tasks": [{"status": "completed"}]})
    assert sr.blocker(live, NEW) is None
