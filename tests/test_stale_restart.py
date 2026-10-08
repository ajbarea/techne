"""Tests for the opt-in restart_on_update hook in plugins/phylax/hooks/stale_restart.py.

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
import shlex
import shutil
import signal
import subprocess
import sys
import time

import pytest
from conftest import _load

ROOT = pathlib.Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "plugins" / "phylax"
SCRIPT = PLUGIN / "hooks" / "stale_restart.py"
HOOKS_JSON = PLUGIN / "hooks" / "hooks.json"
MANIFEST = PLUGIN / ".claude-plugin" / "plugin.json"
OPTION = "restart_on_update"
EVENTS = ("Notification", "Stop", "UserPromptSubmit", "SessionEnd")

# The hook runs on the user's system python3; `make test-hooks-oldest` sets this to 3.9.
HOOK_PYTHON = os.environ.get("TECHNE_GUARD_PYTHON", sys.executable)

OLD, NEW = "2.1.287", "2.1.288"
SID = "11111111-2222-3333-4444-555555555555"
QUIET_TURN = {
    "hook_event_name": "Stop",
    "session_id": SID,
    "background_tasks": [],
    "session_crons": [],
}
IDLE = {"hook_event_name": "Notification", "notification_type": "idle_prompt", "session_id": SID}
WSL = {"WSL_DISTRO_NAME": "Ubuntu", "WT_SESSION": "x", "PHYLAX_RESTART_PARENT": "4242"}
TMUX_STUB = (
    'case "$1" in display-message) echo "$STUB_PANE_PID" ;; '
    '*) echo "tmux $*" >> "$STUB_LOG" ;; esac'
)


@pytest.fixture(scope="module")
def sr():
    return _load("phylax_stale_restart", SCRIPT)


def stub(path: pathlib.Path, body: str) -> pathlib.Path:
    path.write_text(f"#!/bin/sh\n{body}\n")
    path.chmod(0o755)
    return path


def write_stat(proc: pathlib.Path, pid: int, comm: str, ppid: int, start: str, state="S"):
    d = proc / str(pid)
    d.mkdir(parents=True, exist_ok=True)
    # Fields 5..21 between ppid and starttime are irrelevant to the hook.
    fields = [str(pid), f"({comm})", state, str(ppid)] + ["0"] * 17 + [start, "0", "0"]
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
    sessions, proc, runtime, bin_, home = (
        tmp_path / n for n in ("sessions", "proc", "run", "bin", "home")
    )
    for d in (sessions, proc, runtime, bin_, home):
        d.mkdir()
    state = runtime / f"phylax-restart-{os.getuid()}"
    state.mkdir(mode=0o700)
    versions = tmp_path / "share" / "claude" / "versions"
    versions.mkdir(parents=True)
    stub(versions / NEW, 'echo "$@" >> "$STUB_LOG"')
    (bin_ / "claude").symlink_to(versions / NEW)
    monkeypatch.setattr(sr, "SESSIONS", sessions)
    monkeypatch.setattr(sr, "PROC", proc)
    monkeypatch.setattr(sr, "STATE", state)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    sub = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("CLAUDE_PLUGIN_OPTION_", "TMUX", "WT_", "WSL_", "ANTHROPIC_MODEL"))
    }
    sub.update(
        PATH=f"{bin_}:/usr/bin:/bin",
        HOME=str(home),
        PHYLAX_RESTART_SESSIONS=str(sessions),
        PHYLAX_RESTART_PROC=str(proc),
        XDG_RUNTIME_DIR=str(runtime),
        PHYLAX_RESTART_COUNTDOWN="0",
        PHYLAX_RESTART_TERM_WAIT="3",
        PHYLAX_RESTART_SHELL_WAIT="1",
        PHYLAX_RESTART_LATE_WAIT="1",
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
        "home": home,
    }


def calls(env) -> list[str]:
    return env["log"].read_text().splitlines() if env["log"].exists() else []


def put_session(env, data: dict) -> None:
    (env["sessions"] / f"{data['pid']}.json").write_text(json.dumps(data))


def hook_log(env) -> str:
    path = env["state"] / "log"
    return path.read_text() if path.exists() else ""


def user_settings(env, model: str) -> None:
    (env["home"] / ".claude").mkdir(exist_ok=True)
    (env["home"] / ".claude" / "settings.json").write_text(json.dumps({"model": model}))


def write_transcript(path: pathlib.Path, models: list[str]) -> str:
    lines = [json.dumps({"type": "user", "message": {"role": "user", "content": "hi"}})]
    for m in models:
        lines.append(json.dumps({"type": "assistant", "message": {"model": m, "content": []}}))
    lines.append(json.dumps({"type": "system", "content": "assistant"}))
    path.write_text("\n".join(lines) + "\n")
    return str(path)


# --- the safety check ----------------------------------------------------------


@pytest.fixture
def live(env, sr):
    """A fake live claude process 4242 with start time 777, after a quiet turn."""
    write_stat(env["proc"], 4242, "claude", 4000, "777")
    sr.record_turn(QUIET_TURN, SID, 4242)
    return session(4242, "777")


def test_session_blocker_passes_an_idle_interactive_session(sr, live):
    assert sr.session_blocker(live) is None


@pytest.mark.parametrize(
    ("over", "reason"),
    [
        ({"kind": "bg"}, "not interactive"),
        ({"status": "busy"}, "not idle"),
        ({"status": "shell"}, "not idle"),
        ({"status": None}, "not idle"),
        ({"procStart": "778"}, "pid reused"),
        ({"pid": 4243}, "pid reused"),
        ({"pid": "4242"}, "pid reused"),
    ],
)
def test_session_blocker_refuses(sr, live, over, reason):
    live.update(over)
    assert reason in sr.session_blocker(live)


def test_session_blocker_refuses_a_missing_session_or_a_zombie(sr, env, live):
    assert sr.session_blocker(None) == "no live session file"
    write_stat(env["proc"], 4242, "claude", 4000, "777", state="Z")
    assert "pid reused" in sr.session_blocker(live)


@pytest.mark.parametrize(
    ("turn", "reason"),
    [
        ({"background_tasks": [{"type": "shell", "status": "running"}]}, "running: 1"),
        ({"background_tasks": [{"type": "subagent", "status": "running"}]}, "running: 1"),
        ({"background_tasks": [{"status": "queued"}]}, "running: 1"),
        ({"background_tasks": [{"status": "completed"}, "?"]}, "running: 1"),
        ({"background_tasks": None}, "running: None"),
        ({"session_crons": [{"id": "c1"}]}, "session crons: 1"),
        ({"session_crons": "x"}, "session crons: None"),
    ],
)
def test_session_blocker_refuses_after_a_busy_turn(sr, live, turn, reason):
    sr.record_turn({**QUIET_TURN, **turn}, SID, 4242)
    assert reason in sr.session_blocker(live)


def test_session_blocker_clears_once_tasks_end(sr, live):
    sr.record_turn({**QUIET_TURN, "background_tasks": [{"status": "running"}]}, SID, 4242)
    assert sr.session_blocker(live) is not None
    sr.record_turn({**QUIET_TURN, "background_tasks": [{"status": "killed"}]}, SID, 4242)
    assert sr.session_blocker(live) is None


def test_session_blocker_ignores_a_turn_another_process_recorded(sr, env, live):
    # The same conversation open in a second process ended a quiet turn of its own.
    write_stat(env["proc"], 4250, "claude", 1, "99")
    sr.record_turn(QUIET_TURN, SID, 4250)
    assert sr.session_blocker(live) == "last turn recorded by another process"


@pytest.mark.parametrize(
    ("running", "installed", "reason"),
    [
        (OLD, NEW, None),
        ("2.1.9", "2.1.10", None),
        (NEW, NEW, "not newer"),
        ("2.1.300", NEW, "not newer"),
        (None, NEW, "unknown"),
        (OLD, None, "unknown"),
        ("2.1", NEW, "unknown"),
    ],
)
def test_version_blocker_only_moves_forward(sr, running, installed, reason):
    got = sr.version_blocker(running, installed)
    assert got is None if reason is None else reason in got


def test_session_for_takes_only_the_hooks_parent(sr, env, monkeypatch):
    for pid in (4242, 4250):
        write_stat(env["proc"], pid, "claude", 1, str(pid))
        put_session(env, session(pid, str(pid)))
    monkeypatch.setenv("PHYLAX_RESTART_PARENT", "4250")
    assert sr.session_for(SID)["pid"] == 4250
    assert sr.session_for("other") is None
    monkeypatch.setenv("PHYLAX_RESTART_PARENT", "4241")  # no session file
    assert sr.session_for(SID) is None
    put_session(env, session(4241, "1"))  # a file, but no such process
    assert sr.session_for(SID) is None


def test_installed_version_reads_the_native_symlink(sr, env):
    assert sr.installed_version(str(env["bin"] / "claude")) == NEW


def test_installed_version_falls_back_to_running_it(sr, env):
    other = stub(env["tmp"] / "claude-npm", 'echo "2.1.300 (Claude Code)"')
    assert sr.installed_version(str(other)) == "2.1.300"
    assert sr.installed_version(None) is None


def test_state_ok_trusts_only_a_private_dir_we_own(sr, tmp_path):
    fresh = tmp_path / "fresh"
    assert sr.state_ok(fresh)
    assert fresh.stat().st_mode & 0o777 == 0o700
    shared = tmp_path / "shared"
    shared.mkdir()
    shared.chmod(0o777)
    assert not sr.state_ok(shared)
    link = tmp_path / "link"
    link.symlink_to(fresh)
    assert not sr.state_ok(link)
    assert not sr.state_ok(tmp_path / "missing" / "deeper")


def test_send_signals_only_the_process_that_started_then(sr, tmp_path):
    child = subprocess.Popen(["sleep", "60"])
    try:
        start = real_start(child.pid)
        sr.PROC, saved = pathlib.Path("/proc"), sr.PROC
        try:
            assert not sr.send(child.pid, "1", signal.SIGTERM)
            assert child.poll() is None
            assert sr.send(child.pid, start, signal.SIGTERM)
            assert child.wait(timeout=5) == -signal.SIGTERM
            assert not sr.send(child.pid, start, signal.SIGTERM)  # reaped: gone
        finally:
            sr.PROC = saved
    finally:
        if child.poll() is None:
            child.kill()


# --- flags ---------------------------------------------------------------------


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
        "--allow-dangerously-skip-permissions",
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
        "--allow-dangerously-skip-permissions",
    ]


def test_carry_flags_drops_a_trailing_value_flag(sr, env):
    write_stat(env["proc"], 4242, "claude", 1, "1")
    write_cmdline(env["proc"], 4242, ["claude", "--add-dir", "--model"])
    assert sr.carry_flags(4242) == []
    assert sr.carry_flags(9999) == []


def test_last_model_takes_the_latest_real_reply(sr, tmp_path):
    t = write_transcript(
        tmp_path / "t.jsonl", ["claude-haiku-4-5", "claude-opus-5-5", "<synthetic>"]
    )
    assert sr.last_model(t) == "claude-opus-5-5"
    assert sr.last_model(str(tmp_path / "missing.jsonl")) is None
    assert sr.last_model(None) is None


@pytest.mark.parametrize(
    ("flags", "default", "live", "pinned"),
    [
        ([], "opus", "claude-opus-5-5", None),  # a plain resume lands on the same model
        ([], "opus[1m]", "claude-opus-5-5", None),  # and keeps [1m]
        ([], "opusplan", "claude-sonnet-5-5", None),  # opusplan runs sonnet too
        ([], "sonnet", "claude-opus-5-5", "claude-opus-5-5"),  # default moved elsewhere
        ([], None, "claude-opus-5-5", "claude-opus-5-5"),  # nothing to resume onto
        (["--model", "haiku"], "opus", "claude-opus-5-5", "claude-opus-5-5"),  # /model after
        (["--model", "opus"], "sonnet", "claude-opus-5-5", None),  # launch flag holds
        (["--fallback-model", "sonnet"], "opus", "claude-sonnet-5-5", None),  # a fallback reply
    ],
)
def test_resume_flags_pin_the_model_only_when_a_resume_would_change_family(
    sr, env, flags, default, live, pinned
):
    if default:
        user_settings(env, default)
    t = write_transcript(env["tmp"] / "t.jsonl", [live])
    got = sr.resume_flags(list(flags), t, {}, str(env["tmp"]))
    assert sr.flag_value(got, "--model") == (pinned or sr.flag_value(flags, "--model"))


def test_resume_flags_read_project_settings_first(sr, env):
    user_settings(env, "opus")
    (env["tmp"] / ".claude").mkdir()
    (env["tmp"] / ".claude" / "settings.local.json").write_text('{"model": "sonnet"}')
    t = write_transcript(env["tmp"] / "t.jsonl", ["claude-sonnet-5-5"])
    assert sr.resume_flags([], t, {}, str(env["tmp"])) == []


def test_resume_flags_pass_on_the_old_process_model_env(sr, env):
    # ANTHROPIC_MODEL was set for the old process only; the new tab will not have it.
    user_settings(env, "opus")
    t = write_transcript(env["tmp"] / "t.jsonl", ["claude-sonnet-5-5"])
    cwd = str(env["tmp"])
    assert sr.resume_flags([], t, {}, cwd, env_model="sonnet") == ["--model", "sonnet"]
    flags = ["--model", "haiku[1m]"]
    assert sr.resume_flags(flags, None, {}, cwd, env_model="sonnet") == flags


def test_process_env_reads_one_variable(sr, env):
    write_stat(env["proc"], 4242, "claude", 1, "1")
    (env["proc"] / "4242" / "environ").write_bytes(b"A=1\0ANTHROPIC_MODEL=opus[1m]\0B=\0")
    assert sr.process_env(4242, "ANTHROPIC_MODEL") == "opus[1m]"
    assert sr.process_env(4242, "B") is None
    assert sr.process_env(4242, "MISSING") is None
    assert sr.process_env(9999, "ANTHROPIC_MODEL") is None


def test_resume_flags_take_effort_and_mode_from_the_turn(sr, env):
    user_settings(env, "opus")
    turn = {"effort": {"level": "xhigh"}, "permission_mode": "plan"}
    flags = ["--effort=low", "--verbose", "--permission-mode", "default"]
    assert sr.resume_flags(flags, None, turn, str(env["tmp"])) == [
        "--verbose",
        "--effort",
        "xhigh",
        "--permission-mode",
        "plan",
    ]
    bad = {"effort": {"level": "ludicrous"}, "permission_mode": "x"}
    assert sr.resume_flags(["--verbose"], None, bad, str(env["tmp"])) == ["--verbose"]


@pytest.mark.parametrize(
    ("mode", "expect"),
    [
        ("default", ["--permission-mode", "default", "--allow-dangerously-skip-permissions"]),
        (
            "bypassPermissions",
            ["--dangerously-skip-permissions", "--permission-mode", "bypassPermissions"],
        ),
        (None, ["--allow-dangerously-skip-permissions"]),  # mode unknown: bypass stays off
        ("delegate", ["--allow-dangerously-skip-permissions"]),
    ],
)
def test_resume_flags_do_not_switch_bypass_back_on(sr, env, mode, expect):
    user_settings(env, "opus")
    flags = ["--dangerously-skip-permissions"]
    assert sr.resume_flags(flags, None, {"permission_mode": mode}, str(env["tmp"])) == expect


@pytest.mark.parametrize(
    "flags", [["--permission-mode", "bypassPermissions"], ["--permission-mode=bypassPermissions"]]
)
def test_resume_flags_do_not_restore_a_bypass_launch_mode_when_the_mode_is_unknown(sr, env, flags):
    user_settings(env, "opus")
    got = sr.resume_flags(flags, None, {}, str(env["tmp"]))
    assert got == ["--allow-dangerously-skip-permissions"]


# --- which shell or pane may go ------------------------------------------------


def tab(env, *, shell="bash", parent="Relay(300)", extra_child=False):
    write_stat(env["proc"], 4242, "claude", 300, "777")
    write_stat(env["proc"], 300, shell, 200, "55")
    write_stat(env["proc"], 200, parent, 1, "5")
    if extra_child:
        write_stat(env["proc"], 4300, "npm", 300, "60")


@pytest.mark.parametrize(
    ("kw", "closable"),
    [
        ({}, True),
        ({"shell": "-bash"}, True),
        ({"shell": "zsh"}, True),
        ({"parent": "bash"}, False),  # a nested shell
        ({"shell": "python3"}, False),
        ({"shell": "fish"}, False),
        ({"extra_child": True}, False),  # a job would die with the tab
    ],
)
def test_closable_shell_only_takes_a_tabs_top_shell_with_no_jobs(sr, env, kw, closable):
    tab(env, **kw)
    got = sr.closable_shell(4242)
    assert (got == {"pid": 300, "start": "55"}) if closable else got is None


@pytest.mark.parametrize(
    ("root", "setup", "expect"),
    [
        (4242, None, {"pane": "%3", "shell": None}),
        (300, None, {"pane": "%3", "shell": {"pid": 300, "start": "55"}}),
        (300, "job", None),  # npm run dev & in the same shell
        (300, "nvim", None),  # claude inside an editor's terminal
        (None, None, None),  # tmux could not say
    ],
)
def test_respawnable_pane_only_when_nothing_else_runs_there(
    sr, env, monkeypatch, root, setup, expect
):
    parent = 300
    write_stat(env["proc"], 300, "bash", 200, "55")
    if setup == "job":
        write_stat(env["proc"], 4300, "npm", 300, "60")
    if setup == "nvim":
        write_stat(env["proc"], 310, "nvim", 300, "56")
        parent = 310
    write_stat(env["proc"], 4242, "claude", parent, "777")
    monkeypatch.setattr(sr, "tmux_out", lambda *a: None if root is None else str(root))
    assert sr.respawnable_pane(session(4242, "777", tmux="w:@0.%3")) == expect


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
    assert '"${XDG_RUNTIME_DIR:-/tmp}/phylax-restart-$(id -u)/close-$$"' in script
    assert script.endswith('exec "$0" -l')


def test_resume_script_marker_matches_the_hook_state_dir(tmp_path):
    runtime = tmp_path / "rt"
    runtime.mkdir()
    out = subprocess.run(
        ["bash", "-c", 'echo "${XDG_RUNTIME_DIR:-/tmp}/phylax-restart-$(id -u)/close-$$"'],
        env={**os.environ, "XDG_RUNTIME_DIR": str(runtime)},
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert out.startswith(f"{runtime}/phylax-restart-{os.getuid()}/close-")


def test_wt_launch_argv(sr, monkeypatch, tmp_path):
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
    plan = {"name": 'a;b"c', "sessionId": SID, "cwd": "/w d", "shell": "/bin/bash"}
    argv = sr.launch_argv("wt", plan, tmp_path / "plan.json")
    assert argv is not None
    assert argv[:6] == ["wt.exe", "-w", "0", "new-tab", "--title", "claude restart: abc"]
    assert argv[6:12] == ["wsl.exe", "-d", "Ubuntu", "--cd", "/w d", "--"]
    assert argv[12:14] == ["/bin/bash", "-lic"]
    assert argv[14].startswith("exec ") and argv[14].endswith(f"handoff {tmp_path}/plan.json")


def test_wt_launch_argv_refuses_a_semicolon_it_cannot_pass(sr, monkeypatch, tmp_path):
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
    plan = {"name": "n", "sessionId": SID, "cwd": "/home/u/a;b", "shell": "/bin/bash"}
    assert sr.launch_argv("wt", plan, tmp_path / "plan.json") is None


def test_tmux_launch_argv_opens_a_window_in_the_same_session(sr, tmp_path):
    plan = {"tmux": "work:@2.%7", "cwd": "/w"}
    argv = sr.launch_argv("tmux", plan, tmp_path / "p.json")
    assert argv is not None
    assert argv[:8] == ["tmux", "new-window", "-t", "=work:", "-n", "claude-restart", "-c", "/w"]
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


@pytest.fixture
def tmux_env(env, live):
    """A stale idle session that is tmux pane %3's first process, with a logging tmux stub."""
    stub(env["bin"] / "tmux", TMUX_STUB)
    env["env"]["STUB_PANE_PID"] = "4242"
    env["env"]["PHYLAX_RESTART_PARENT"] = "4242"
    live["tmux"] = "work:@0.%3"
    put_session(env, live)
    write_cmdline(env["proc"], 4242, ["claude", "--model", "opus", "hello"])
    user_settings(env, "opus")
    return env


def plan_of(env) -> dict:
    return json.loads((env["state"] / f"plan-{SID}.json").read_text())


def test_hook_launches_one_handoff_and_says_so(tmux_env):
    out = run_hook(tmux_env, IDLE)
    assert out is not None
    assert "a new tmux window" in out["systemMessage"]
    (call,) = calls(tmux_env)
    assert call.startswith("tmux new-window -t =work: -n claude-restart -c /work ")
    plan = plan_of(tmux_env)
    assert plan["flags"] == ["--model", "opus"]
    assert plan["respawn"] == {"pane": "%3", "shell": None}
    assert plan["closeShell"] is None and plan["launcher"] == "tmux"
    assert (plan["version"], plan["installed"]) == (OLD, NEW)
    # A second idle_prompt while the handoff is pending launches nothing.
    assert run_hook(tmux_env, IDLE) is None
    assert len(calls(tmux_env)) == 1


def test_hook_plan_carries_the_live_effort_and_mode(tmux_env):
    turn = {**QUIET_TURN, "effort": {"level": "high"}, "permission_mode": "bypassPermissions"}
    assert run_hook(tmux_env, turn) is None
    t = write_transcript(tmux_env["tmp"] / "t.jsonl", ["claude-opus-5-5"])
    assert run_hook(tmux_env, {**IDLE, "transcript_path": t}) is not None
    assert plan_of(tmux_env)["flags"] == [
        "--model",
        "opus",
        "--effort",
        "high",
        "--permission-mode",
        "bypassPermissions",
    ]


def test_hook_ignores_other_notifications_and_busy_sessions(tmux_env, live):
    assert run_hook(tmux_env, {**IDLE, "notification_type": "permission_prompt"}) is None
    put_session(tmux_env, {**live, "status": "busy"})
    assert run_hook(tmux_env, IDLE) is None
    assert calls(tmux_env) == []
    assert hook_log(tmux_env) == ""  # routine skips are not logged


def test_hook_never_moves_a_session_to_an_older_build(tmux_env, live):
    put_session(tmux_env, {**live, "version": "2.1.300"})
    assert run_hook(tmux_env, IDLE) is None
    assert calls(tmux_env) == []


def test_prompt_submit_clears_the_turn_so_an_interrupted_turn_blocks(tmux_env):
    assert run_hook(tmux_env, {**IDLE, "hook_event_name": "UserPromptSubmit"}) is None
    assert not (tmux_env["state"] / f"turn-{SID}.json").exists()
    assert run_hook(tmux_env, IDLE) is None  # Esc skipped Stop: nothing recorded
    assert run_hook(tmux_env, QUIET_TURN) is None
    assert run_hook(tmux_env, IDLE) is not None


def test_session_end_removes_its_state(tmux_env):
    for stem in ("notice", "declined"):
        (tmux_env["state"] / f"{stem}-{SID}").write_text("x")
    assert run_hook(tmux_env, {"hook_event_name": "SessionEnd", "session_id": SID}) is None
    assert sorted(p.name for p in tmux_env["state"].iterdir()) == []


def test_hook_respects_a_cancel_for_the_same_version_only(tmux_env):
    (tmux_env["state"] / f"declined-{SID}").write_text(NEW)
    assert run_hook(tmux_env, IDLE) is None
    (tmux_env["state"] / f"declined-{SID}").write_text("2.1.250")
    assert run_hook(tmux_env, IDLE) is not None


def test_hook_frees_the_slot_when_the_launcher_fails(tmux_env):
    stub(tmux_env["bin"] / "tmux", 'case "$1" in display-message) echo 4242 ;; *) exit 1 ;; esac')
    assert run_hook(tmux_env, IDLE) is None
    assert not (tmux_env["state"] / f"plan-{SID}.json").exists()
    assert "launcher tmux failed: 1" in hook_log(tmux_env)


def test_hook_reclaims_an_expired_slot(tmux_env, sr):
    plan = tmux_env["state"] / f"plan-{SID}.json"
    plan.write_text("{}")
    old = time.time() - sr.PLAN_TTL - 1
    os.utime(plan, (old, old))
    assert run_hook(tmux_env, IDLE) is not None


def test_hook_does_nothing_in_a_state_dir_it_does_not_own(tmux_env):
    tmux_env["state"].chmod(0o777)
    try:
        assert run_hook(tmux_env, IDLE) is None
        assert calls(tmux_env) == []
    finally:
        tmux_env["state"].chmod(0o700)


PARENT = {"PHYLAX_RESTART_PARENT": "4242"}


def test_hook_notices_an_unsupported_terminal_once(env, live):
    put_session(env, live)
    first = run_hook(env, IDLE, PARENT)
    assert first is not None
    assert "supports tmux and Windows Terminal" in first["systemMessage"]
    assert run_hook(env, IDLE, PARENT) is None


def test_hook_picks_windows_terminal_under_wsl(env, live):
    stub(env["bin"] / "wt.exe", 'echo "wt $*" >> "$STUB_LOG"')
    tab(env)
    put_session(env, live)
    out = run_hook(env, IDLE, WSL)
    assert out is not None
    assert "a new tab" in out["systemMessage"]
    (call,) = calls(env)
    assert call.startswith("wt -w 0 new-tab --title claude restart: probe wsl.exe -d Ubuntu")
    assert plan_of(env)["closeShell"] == {"pid": 300, "start": "55"}


def test_hook_logs_why_a_stale_session_waits_once_per_reason(env, sr, live):
    """A restart that never comes is read in the log, not guessed at."""
    put_session(env, live)
    sr.record_turn({**QUIET_TURN, "background_tasks": [{"status": "running"}]}, SID, 4242)
    assert run_hook(env, IDLE, PARENT) is None
    assert run_hook(env, IDLE, PARENT) is None
    assert hook_log(env).count("held: background tasks or subagents running: 1") == 1
    sr.record_turn({**QUIET_TURN, "session_crons": [{}]}, SID, 4242)
    assert run_hook(env, IDLE, PARENT) is None
    assert "held: session crons: 1" in hook_log(env)
    assert calls(env) == []


def test_hook_logs_nothing_for_a_held_session_with_no_update_waiting(env, sr, live):
    put_session(env, {**live, "version": NEW})
    sr.record_turn({**QUIET_TURN, "background_tasks": [{"status": "running"}]}, SID, 4242)
    assert run_hook(env, IDLE, PARENT) is None
    assert hook_log(env) == ""


def test_hook_skips_a_cwd_wt_cannot_pass(env, live):
    stub(env["bin"] / "wt.exe", 'echo "wt $*" >> "$STUB_LOG"')
    tab(env)
    put_session(env, {**live, "cwd": "/home/u/a;b"})
    assert run_hook(env, IDLE, WSL) is None
    assert calls(env) == []
    assert not (env["state"] / f"plan-{SID}.json").exists()
    assert "holds ';'" in hook_log(env)


@pytest.mark.parametrize(
    "payload",
    [
        "",
        "[]",
        "not json",
        '{"session_id": 5, "notification_type": "idle_prompt"}',
        '{"session_id": "../x", "notification_type": "idle_prompt"}',
        '{"session_id": "../x", "hook_event_name": "Stop"}',
    ],
)
def test_hook_tolerates_bad_input(env, payload):
    proc = subprocess.run(
        [HOOK_PYTHON, str(SCRIPT)], input=payload, capture_output=True, text=True, env=env["env"]
    )
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, "", "")
    assert sorted(p.name for p in env["state"].iterdir()) == []


# --- hooks.json and the manifest -----------------------------------------------


def _handlers(event: str) -> list[dict]:
    config = json.loads(HOOKS_JSON.read_text())
    return [h for group in config["hooks"][event] for h in group["hooks"]]


def test_hooks_json_wires_the_option_to_its_events():
    config = json.loads(HOOKS_JSON.read_text())
    assert config["hooks"]["Notification"][0]["matcher"] == "idle_prompt"
    for event in EVENTS:
        (handler,) = _handlers(event)
        assert f"$CLAUDE_PLUGIN_OPTION_{OPTION.upper()}" in handler["command"]
        assert '"${CLAUDE_PLUGIN_ROOT}/hooks/stale_restart.py"' in handler["command"]


def test_hooks_json_skips_python_when_off(tmp_path):
    empty = tmp_path / "bin"
    empty.mkdir()
    for event in EVENTS:
        (handler,) = _handlers(event)
        shell = handler["command"].replace("${CLAUDE_PLUGIN_ROOT}", str(PLUGIN))
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


@pytest.fixture
def job_shell():
    """A real shell with a background job, standing in for a shell that must not close."""
    shell = subprocess.Popen(["bash", "-c", "sleep 60 & wait"])
    time.sleep(0.3)
    yield shell
    shell.kill()
    shell.wait()


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
        "respawn": None,
        "closeShell": None,
        "shell": str(shell),
    }
    plan.update(over)
    path = env["state"] / f"plan-{SID}.json"
    path.write_text(json.dumps(plan))
    return path


def run_handoff(env, plan: pathlib.Path, **extra) -> subprocess.CompletedProcess:
    return subprocess.run(
        [HOOK_PYTHON, str(SCRIPT), "handoff", str(plan)],
        capture_output=True,
        text=True,
        env={**env["env"], "PHYLAX_RESTART_PROC": "/proc", **extra},
        stdin=subprocess.DEVNULL,
        timeout=30,
    )


def put_real_session(env, child, **over) -> None:
    put_session(env, session(child.pid, real_start(child.pid), **over))
    write_turn(env, child.pid, tasks=0)


def write_turn(env, pid: int, tasks: int) -> None:
    turn = {"pid": pid, "start": real_start(pid), "tasks": tasks, "crons": 0}
    (env["state"] / f"turn-{SID}.json").write_text(json.dumps(turn))


def shell_of(proc: subprocess.Popen) -> dict:
    return {"pid": proc.pid, "start": real_start(proc.pid)}


def test_handoff_stops_the_old_process_and_resumes(env, old_claude):
    put_real_session(env, old_claude)
    plan = write_plan(env, old_claude.pid)
    proc = run_handoff(env, plan)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert old_claude.wait(timeout=5) == -signal.SIGTERM
    (call,) = calls(env)
    assert call.startswith(f"shell -lic {env['bin']}/claude --resume {SID} --model opus; ")
    assert not plan.exists()


def test_handoff_uses_the_plans_state_dir_not_its_own_env(env, old_claude, tmp_path):
    put_real_session(env, old_claude)
    other = tmp_path / "elsewhere"
    other.mkdir()
    proc = run_handoff(env, write_plan(env, old_claude.pid), XDG_RUNTIME_DIR=str(other))
    assert proc.returncode == 0, proc.stdout
    assert "stopped" in hook_log(env)


@pytest.mark.parametrize(
    ("session_over", "plan_over"),
    [
        ({"status": "busy"}, {}),
        ({"status": "shell"}, {}),
        ({"sessionId": "other"}, {}),
        ({}, {"version": NEW}),
        ({}, {"procStart": "1"}),
    ],
)
def test_handoff_rechecks_before_signalling(env, old_claude, session_over, plan_over):
    put_real_session(env, old_claude, **session_over)
    proc = run_handoff(env, write_plan(env, old_claude.pid, **plan_over))
    assert proc.returncode == 1
    assert "Not restarting" in proc.stdout
    assert old_claude.poll() is None
    assert calls(env) == []
    assert not (env["state"] / f"plan-{SID}.json").exists()


def test_handoff_rechecks_the_turn(env, old_claude):
    put_real_session(env, old_claude)
    write_turn(env, old_claude.pid, tasks=1)
    proc = run_handoff(env, write_plan(env, old_claude.pid))
    assert proc.returncode == 1
    assert old_claude.poll() is None


def test_handoff_refuses_a_shared_state_dir(env, old_claude):
    put_real_session(env, old_claude)
    plan = write_plan(env, old_claude.pid)
    env["state"].chmod(0o777)
    try:
        proc = run_handoff(env, plan)
    finally:
        env["state"].chmod(0o700)
    assert proc.returncode == 1
    assert "not a private state directory" in proc.stdout
    assert old_claude.poll() is None


def test_handoff_never_escalates_past_sigterm(env):
    child = subprocess.Popen(["bash", "-c", "trap '' TERM; sleep 60 & wait"])
    try:
        time.sleep(0.3)
        put_real_session(env, child)
        proc = run_handoff(env, write_plan(env, child.pid))
        assert proc.returncode == 1
        assert "has not exited" in proc.stdout
        assert f"--resume {SID}" in proc.stdout  # the command to run once it exits
        assert child.poll() is None
        assert calls(env) == []
    finally:
        child.kill()
        child.wait()


def test_handoff_closes_the_old_shell_that_ignores_the_marker(env, old_claude):
    shell = subprocess.Popen(["sleep", "60"])
    try:
        put_real_session(env, old_claude)
        proc = run_handoff(env, write_plan(env, old_claude.pid, closeShell=shell_of(shell)))
        assert proc.returncode == 0, proc.stdout
        assert shell.wait(timeout=5) == -signal.SIGHUP
        assert not (env["state"] / f"close-{shell.pid}").exists()
    finally:
        if shell.poll() is None:
            shell.kill()


def test_handoff_leaves_an_old_shell_that_gained_a_job(env, old_claude, job_shell):
    put_real_session(env, old_claude)
    proc = run_handoff(env, write_plan(env, old_claude.pid, closeShell=shell_of(job_shell)))
    assert proc.returncode == 0, proc.stdout
    assert job_shell.poll() is None
    assert "has a new child; left open" in hook_log(env)


def test_handoff_lets_a_snippet_shell_exit_on_its_own(env, old_claude):
    # Mirrors the PROMPT_COMMAND snippet: exit 0 once the marker for this pid appears.
    shell = subprocess.Popen(
        ["bash", "-c", f'while [ ! -e "{env["state"]}/close-$$" ]; do sleep 0.05; done; exit 0']
    )
    try:
        put_real_session(env, old_claude)
        proc = run_handoff(env, write_plan(env, old_claude.pid, closeShell=shell_of(shell)))
        assert proc.returncode == 0, proc.stdout
        assert shell.wait(timeout=5) == 0
    finally:
        if shell.poll() is None:
            shell.kill()


def test_handoff_respawns_a_pane_the_session_started(env, old_claude):
    stub(env["bin"] / "tmux", 'echo "tmux $*" >> "$STUB_LOG"')
    put_real_session(env, old_claude, tmux="w:@0.%9")
    respawn = {"pane": "%9", "shell": None}
    plan = write_plan(env, old_claude.pid, launcher="tmux", tmux="w:@0.%9", respawn=respawn)
    proc = run_handoff(env, plan)
    assert proc.returncode == 0, proc.stdout
    on, respawned, off = calls(env)
    assert on == "tmux set-option -p -t %9 remain-on-exit on"
    assert respawned.startswith(f"tmux respawn-pane -k -t %9 -c {env['tmp']} ")
    assert f"--resume {SID} --model opus" in respawned
    assert off == "tmux set-option -p -u -t %9 remain-on-exit"


def test_handoff_respawns_a_shell_pane_only_while_the_shell_is_empty(env, old_claude, job_shell):
    stub(env["bin"] / "tmux", 'echo "tmux $*" >> "$STUB_LOG"')
    put_real_session(env, old_claude, tmux="w:@0.%9")
    respawn = {"pane": "%9", "shell": shell_of(job_shell)}
    plan = write_plan(env, old_claude.pid, launcher="tmux", tmux="w:@0.%9", respawn=respawn)
    proc = run_handoff(env, plan)
    assert proc.returncode == 0, proc.stdout
    assert "resuming here instead" in proc.stdout
    # No respawn: the job in the pane's shell lives, and the resume runs in this window.
    assert not any("respawn-pane" in c for c in calls(env))
    assert any(c.startswith("shell -lic ") for c in calls(env))
    assert job_shell.poll() is None


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
            env={**env["env"], "PHYLAX_RESTART_PROC": "/proc", "PHYLAX_RESTART_COUNTDOWN": "20"},
        )
        time.sleep(1)
        os.write(master, b"x")
        time.sleep(0.5)
        # The slot is already free while the tab waits for Enter.
        assert not plan.exists()
        os.write(master, b"\n")
        assert proc.wait(timeout=10) == 1
    finally:
        os.close(master)
        os.close(slave)
    assert old_claude.poll() is None
    assert (env["state"] / f"declined-{SID}").read_text() == NEW
    assert calls(env) == []


def test_handoff_keeps_waiting_for_a_late_exit_and_resumes(env):
    # Slow SessionEnd hooks: the process exits well after TERM_WAIT.
    child = subprocess.Popen(["bash", "-c", "trap 'sleep 2; exit 0' TERM; sleep 60 & wait"])
    try:
        time.sleep(0.3)
        put_real_session(env, child)
        plan = write_plan(env, child.pid)
        proc = run_handoff(env, plan, PHYLAX_RESTART_TERM_WAIT="1", PHYLAX_RESTART_LATE_WAIT="10")
        assert proc.returncode == 0, proc.stdout
        assert child.wait(timeout=5) == 0
        assert any(c.startswith("shell -lic ") for c in calls(env))
    finally:
        if child.poll() is None:
            child.kill()


def test_handoff_refuses_before_signalling_when_the_directory_is_gone(env, old_claude):
    put_real_session(env, old_claude)
    proc = run_handoff(env, write_plan(env, old_claude.pid, cwd=str(env["tmp"] / "gone")))
    assert proc.returncode == 1
    assert "no longer exists" in proc.stdout
    assert old_claude.poll() is None


@pytest.mark.parametrize("sig", [signal.SIGHUP, signal.SIGINT])
def test_handoff_closing_or_interrupting_the_countdown_cancels(env, old_claude, sig):
    put_real_session(env, old_claude)
    plan = write_plan(env, old_claude.pid)
    proc = subprocess.Popen(
        [HOOK_PYTHON, str(SCRIPT), "handoff", str(plan)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        text=True,
        env={**env["env"], "PHYLAX_RESTART_PROC": "/proc", "PHYLAX_RESTART_COUNTDOWN": "20"},
    )
    time.sleep(1)
    proc.send_signal(sig)
    assert proc.wait(timeout=10) == 1
    assert old_claude.poll() is None
    assert (env["state"] / f"declined-{SID}").read_text() == NEW
    assert not plan.exists()


def test_handoff_respawns_a_pane_whose_shell_held_only_the_session(env, old_claude):
    stub(env["bin"] / "tmux", 'echo "tmux $*" >> "$STUB_LOG"')
    shell = subprocess.Popen(["sleep", "60"])  # a shell with no other child
    try:
        put_real_session(env, old_claude, tmux="w:@0.%9")
        respawn = {"pane": "%9", "shell": shell_of(shell)}
        plan = write_plan(env, old_claude.pid, launcher="tmux", tmux="w:@0.%9", respawn=respawn)
        proc = run_handoff(env, plan)
        assert proc.returncode == 0, proc.stdout
        (respawned,) = calls(env)  # no remain-on-exit: the shell keeps the pane
        assert respawned.startswith("tmux respawn-pane -k -t %9 ")
    finally:
        shell.kill()
        shell.wait()


def test_docs_list_every_carried_flag(sr):
    docs = (ROOT / "docs" / "configuration.md").read_text()
    section = docs[docs.index("## Restart on update") : docs.index("## Per-skill configuration")]
    for flag in sr.CARRY_VALUE | sr.CARRY_VARIADIC | sr.CARRY_BOOL:
        if flag in ("--allowed-tools", "--disallowed-tools") or "system-prompt" in flag:
            continue  # aliases, and the system-prompt flags named as a group
        assert f"`{flag}`" in section, flag


def test_handoff_ctrl_c_while_waiting_stops_the_wait_without_a_traceback(env):
    child = subprocess.Popen(["bash", "-c", "trap '' TERM; sleep 60 & wait"])
    try:
        time.sleep(0.3)
        put_real_session(env, child)
        proc = subprocess.Popen(
            [HOOK_PYTHON, str(SCRIPT), "handoff", str(write_plan(env, child.pid))],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={
                **env["env"],
                "PHYLAX_RESTART_PROC": "/proc",
                "PHYLAX_RESTART_TERM_WAIT": "1",
                "PHYLAX_RESTART_LATE_WAIT": "60",
            },
        )
        time.sleep(2.5)  # past TERM_WAIT, inside the late wait
        proc.send_signal(signal.SIGINT)
        proc.send_signal(signal.SIGINT)  # a second press must not hide the resume command
        out, err = proc.communicate(timeout=10)
        assert proc.returncode == 1
        assert "has not exited" in out and f"--resume {SID}" in out
        assert err == ""
        assert child.poll() is None
    finally:
        child.kill()
        child.wait()


def test_handoff_resets_signals_python_ignores_before_exec(env, old_claude):
    put_real_session(env, old_claude)
    shell = stub(env["tmp"] / "sigshell", 'grep SigIgn /proc/$$/status >> "$STUB_LOG"')
    proc = run_handoff(env, write_plan(env, old_claude.pid, shell=str(shell)))
    assert proc.returncode == 0, proc.stdout
    (line,) = calls(env)
    ignored = int(line.split()[1], 16)
    for sig in (signal.SIGPIPE, signal.SIGXFSZ, signal.SIGINT, signal.SIGHUP):
        assert not ignored & (1 << (sig - 1)), sig


@pytest.mark.skipif(not shutil.which("tmux"), reason="needs tmux")
def test_handoff_window_killed_during_countdown_records_the_cancel(env, old_claude):
    put_real_session(env, old_claude)
    plan = write_plan(env, old_claude.pid)
    server = f"phylax-test-{os.getpid()}"
    cmd = shlex.join([HOOK_PYTHON, str(SCRIPT), "handoff", str(plan)])
    tenv = {**env["env"], "PHYLAX_RESTART_PROC": "/proc", "PHYLAX_RESTART_COUNTDOWN": "30"}
    run = ["tmux", "-L", server, "-f", "/dev/null"]
    subprocess.run([*run, "new-session", "-d", "-x", "80", "-y", "10", cmd], env=tenv, check=True)
    try:
        time.sleep(1.5)  # inside the countdown, with the terminal in cbreak mode
        subprocess.run([*run, "kill-server"], check=True)
        deadline = time.monotonic() + 10
        declined = env["state"] / f"declined-{SID}"
        while not declined.exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        assert declined.read_text() == NEW
        assert old_claude.poll() is None
    finally:
        subprocess.run([*run, "kill-server"], capture_output=True)
