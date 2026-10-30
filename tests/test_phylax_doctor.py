"""The phylax setup doctor: option values arrive as KEY=VALUE arguments from the skill."""

from __future__ import annotations

import os
import re
import shutil

import pytest
from conftest import (
    DOCTOR_LIB,
    EMAIL,
    MACHINE_PATH,
    ROOT,
    _load,
    doctor_lines,
    run_doctor,
    stub_dir,
)

PLUGIN = ROOT / "plugins" / "phylax"
DOCTOR = PLUGIN / "skills" / "setup" / "scripts" / "doctor.py"
AGENTS = PLUGIN / "AGENTS.md"
SKILL = PLUGIN / "skills" / "setup" / "SKILL.md"
OPTIONS = (
    "block_attribution_trailers",
    "block_commits_md",
    "warn_main_checkout_commit",
    "block_secrets",
    "block_long_bodies",
    "require_subagent_model",
    "restart_on_update",
    "budget_mode",
)
STUBS = {
    "python3": "echo 3.9.6",
    "claude": "echo '2.1.296 (Claude Code)'",
    "tmux": "echo 'tmux 3.4'",
    "gitleaks": "echo 8.30.1",
}


def args(**on):
    return [f"{key}={'true' if on.get(key) else 'false'}" for key in OPTIONS]


@pytest.fixture
def env(tmp_path):
    proc = tmp_path / "proc"
    proc.mkdir()
    runtime = tmp_path / "run"
    runtime.mkdir()
    return {"PHYLAX_RESTART_PROC": str(proc), "XDG_RUNTIME_DIR": str(runtime)}


def doctor(tmp_path, argv, env, stubs=STUBS, links=("git",), extra=None):
    proc = run_doctor(
        DOCTOR,
        *argv,
        path=stub_dir(tmp_path, stubs, links),
        home=tmp_path,
        env={**env, **(extra or {})},
    )
    return proc, doctor_lines(proc)


def state_dir(env):
    return os.path.join(env["XDG_RUNTIME_DIR"], f"phylax-restart-{os.getuid()}")


def test_all_off_is_ready_and_checks_nothing_else(tmp_path, env):
    proc, found = doctor(tmp_path, args(), env, stubs={})
    assert proc.returncode == 0
    assert all(found[k][0] == "n/a" for k in OPTIONS)
    for name in ("mod", "python3", "git", "proc", "launcher", "claude", "state-dir", "budget"):
        assert found[name][0] == "n/a", name


def test_unset_options_in_every_form_read_as_off(tmp_path, env):
    argv = [
        "block_attribution_trailers=${user_config.block_attribution_trailers}",
        "block_commits_md=",
        "unknown_key=true",
        "not-an-assignment",
    ]
    proc, found = doctor(tmp_path, argv, env)
    assert proc.returncode == 0
    for key in OPTIONS:
        assert found[key][0] == "n/a" and found[key][1].startswith("not set, so off"), key


@pytest.mark.parametrize("option", OPTIONS)
@pytest.mark.parametrize("value", ["maybe", "TRUE", "True", " true", "x:true"])
def test_a_value_the_hooks_do_not_read_as_true_is_named_and_off(tmp_path, env, option, value):
    proc, found = doctor(tmp_path, [f"{option}={value}"], env)
    assert proc.returncode == 0
    status, detail = found[option]
    assert status == "n/a" and detail.startswith(f"set to {value!r}") and "so off" in detail
    # Nothing the option needs is checked, since it is off.
    for name in ("mod", "python3", "git", "proc", "launcher", "claude", "state-dir", "budget"):
        assert found[name][0] == "n/a", (option, name)


def test_missing_arguments_read_as_off(tmp_path, env):
    proc, found = doctor(tmp_path, [], env)
    assert proc.returncode == 0
    for key in OPTIONS:
        assert found[key][0] == "n/a" and found[key][1].startswith("not set, so off"), key


def test_guards_on_needs_python3_and_git(tmp_path, env):
    proc, found = doctor(tmp_path, args(block_commits_md=True), env, links=())
    assert proc.returncode == 1 and found["git"][0] == "missing"
    assert found["python3"][0] == "ok" and found["mod"][0] == "ok"
    old = {**STUBS, "python3": "echo 3.8.10"}
    proc, found = doctor(tmp_path, args(block_commits_md=True), env, stubs=old)
    assert found["python3"][0] == "missing" and "need 3.9 or newer" in found["python3"][1]


def test_subagent_model_needs_python3_only(tmp_path, env):
    proc, found = doctor(tmp_path, args(require_subagent_model=True), env, links=())
    assert proc.returncode == 0
    assert found["require_subagent_model"] == ("ok", "on")
    assert found["python3"][0] == "ok"
    assert found["git"][0] == "n/a" and found["mod"][0] == "n/a"
    old = {**STUBS, "python3": "echo 3.8.10"}
    proc, found = doctor(tmp_path, args(require_subagent_model=True), env, stubs=old)
    assert found["python3"][0] == "missing" and "need 3.9 or newer" in found["python3"][1]


def test_old_claude_code_falls_back_to_the_command_hook(tmp_path, env):
    old = {**STUBS, "claude": "echo '2.1.200 (Claude Code)'"}
    proc, found = doctor(tmp_path, args(block_attribution_trailers=True), env, stubs=old)
    assert proc.returncode == 0 and found["mod"][0] == "optional"
    assert "  fix: claude update" in proc.stdout.splitlines()
    no_claude = {k: v for k, v in STUBS.items() if k != "claude"}
    proc, found = doctor(tmp_path, args(block_attribution_trailers=True), env, stubs=no_claude)
    assert proc.returncode == 0 and found["mod"][0] == "optional"


@pytest.mark.parametrize(
    ("version", "state", "says"),
    [
        ("2.1.286", "optional", "predates mods"),
        ("2.1.287", "optional", "worktree subagents"),
        ("2.1.288", "ok", "loads the guard mod"),
    ],
)
def test_mod_line_names_what_each_version_does(tmp_path, env, version, state, says):
    stubs = {**STUBS, "claude": f"echo '{version} (Claude Code)'"}
    _, found = doctor(tmp_path, args(block_attribution_trailers=True), env, stubs=stubs)
    assert found["mod"][0] == state and says in found["mod"][1]


def test_restart_on_without_proc(tmp_path, env):
    extra = {"PHYLAX_RESTART_PROC": str(tmp_path / "nowhere")}
    proc, found = doctor(tmp_path, args(restart_on_update=True), env, extra=extra)
    assert proc.returncode == 1 and found["proc"][0] == "missing"
    assert "Linux and WSL only" in found["proc"][1]


NO_TMUX = {k: v for k, v in STUBS.items() if k != "tmux"}
WT = {"WSL_DISTRO_NAME": "Ubuntu", "WT_SESSION": "abc", "TECHNE_DOCTOR_WSL": "1"}


def test_launcher_ok_inside_tmux(tmp_path, env):
    proc, found = doctor(tmp_path, args(restart_on_update=True), env, extra={"TMUX_PANE": "%3"})
    assert found["launcher"][0] == "ok" and "tmux" in found["launcher"][1]
    assert proc.returncode == 0


def test_launcher_ok_inside_windows_terminal_under_wsl(tmp_path, env):
    stubs = {**NO_TMUX, "wt.exe": "exit 0"}
    proc, found = doctor(tmp_path, args(restart_on_update=True), env, stubs=stubs, extra=WT)
    assert found["launcher"][0] == "ok" and "Windows Terminal" in found["launcher"][1]
    assert proc.returncode == 0


def test_launcher_missing_outside_tmux_even_with_tmux_installed(tmp_path, env):
    proc, found = doctor(tmp_path, args(restart_on_update=True), env)
    assert proc.returncode == 1 and found["launcher"][0] == "missing"
    assert "inside tmux or Windows Terminal" in found["launcher"][1]
    assert "configuration/#restart-on-update" in found["launcher"][1]
    assert "  fix: tmux new-session claude" in proc.stdout.splitlines()


def test_launcher_missing_in_a_non_wt_wsl_terminal_with_wt_on_path(tmp_path, env):
    stubs = {**NO_TMUX, "wt.exe": "exit 0"}
    extra = {"WSL_DISTRO_NAME": "Ubuntu", "TECHNE_DOCTOR_WSL": "1"}
    _, found = doctor(tmp_path, args(restart_on_update=True), env, stubs=stubs, extra=extra)
    assert found["launcher"][0] == "missing"


def test_launcher_without_tmux_installed_names_the_install(tmp_path, env):
    proc, found = doctor(tmp_path, args(restart_on_update=True), env, stubs=NO_TMUX)
    assert found["launcher"][0] == "missing"
    assert "  fix: sudo apt install tmux" in proc.stdout.splitlines()


def test_launcher_agrees_with_the_hook(tmp_path, env, monkeypatch):
    hook = _load("phylax_stale_restart_agree", PLUGIN / "hooks" / "stale_restart.py")
    cases = [
        ({"TMUX_PANE": "%1"}, {}, "tmux"),
        ({}, WT, "wt"),
        ({}, {}, None),
    ]
    real_path = os.environ["PATH"]
    for hook_env, extra, want in cases:
        monkeypatch.setenv("PATH", real_path)
        stubs = {**STUBS, "wt.exe": "exit 0"}
        _, found = doctor(
            tmp_path, args(restart_on_update=True), env, stubs=stubs, extra={**hook_env, **extra}
        )
        for key in ("TMUX_PANE", "WSL_DISTRO_NAME", "WT_SESSION"):
            monkeypatch.delenv(key, raising=False)
        for key, value in {**hook_env, **extra}.items():
            monkeypatch.setenv(key, value)
        monkeypatch.setenv("PATH", stub_dir(tmp_path, stubs))
        session = {"tmux": "s:0.%1"} if "TMUX_PANE" in hook_env else {}
        assert hook.pick_launcher(session) == want
        assert (found["launcher"][0] == "ok") == (want is not None)


def test_restart_needs_claude_on_path(tmp_path, env):
    no_claude = {k: v for k, v in STUBS.items() if k != "claude"}
    proc, found = doctor(tmp_path, args(restart_on_update=True), env, stubs=no_claude)
    assert found["claude"][0] == "missing"
    assert "  fix: curl -fsSL https://claude.ai/install.sh | bash" in proc.stdout.splitlines()


def test_state_dir_is_read_only_and_judged_by_state_ok(tmp_path, env):
    path = state_dir(env)
    _, found = doctor(tmp_path, args(restart_on_update=True), env)
    assert found["state-dir"][0] == "ok" and not os.path.exists(path)

    os.mkdir(path, 0o755)
    os.chmod(path, 0o755)
    proc, found = doctor(tmp_path, args(restart_on_update=True), env)
    assert found["state-dir"][0] == "missing"
    assert f"  fix: chmod 700 {path}" in proc.stdout.splitlines()

    os.chmod(path, 0o700)
    _, found = doctor(tmp_path, args(restart_on_update=True), env)
    assert found["state-dir"] == ("ok", path)

    os.rmdir(path)
    os.symlink(str(tmp_path), path)
    proc, found = doctor(tmp_path, args(restart_on_update=True), env)
    assert found["state-dir"][0] == "missing" and "symlink" in found["state-dir"][1]
    assert f"  fix: rm {path}" in proc.stdout.splitlines()


def test_running_the_doctor_leaves_no_bytecode(tmp_path, env):
    plugin = tmp_path / "plugin" / "phylax"
    shutil.copytree(
        PLUGIN,
        plugin,
        ignore=shutil.ignore_patterns("__pycache__", "evals", "eval-fixtures", "tests"),
    )

    def listing():
        return sorted(p.relative_to(plugin).as_posix() for p in plugin.rglob("*"))

    before = listing()
    script = plugin / "skills" / "setup" / "scripts" / "doctor.py"
    argv = args(block_commits_md=True, restart_on_update=True)
    proc = run_doctor(
        script,
        *argv,
        path=stub_dir(tmp_path, STUBS, ("git",)),
        home=tmp_path,
        env={**env, "PYTHONDONTWRITEBYTECODE": ""},
    )
    assert "Traceback" not in proc.stderr and "state-dir" in proc.stdout
    assert listing() == before
    assert not list(plugin.rglob("__pycache__"))


def test_every_doctor_ships_doctor_lib():
    doctors = sorted(ROOT.glob("plugins/*/skills/*/scripts/doctor.py"))
    assert len(doctors) >= 3
    assert PLUGIN / "skills" / "setup" / "scripts" / "doctor.py" in doctors
    for script in doctors:
        plugin = script.parents[3]
        copy = plugin / "_shared" / "doctor_lib.py"
        assert copy.read_bytes() == DOCTOR_LIB.read_bytes(), plugin.name


def test_skill_passes_each_option_single_quoted():
    text = SKILL.read_text(encoding="utf-8")
    for key in OPTIONS:
        assert f"'{key}=${{user_config.{key}}}'" in text, key


def test_runbook_restates_only_fixes_from_the_table():
    lib = _load("phylax_doctor_lib_runbook", DOCTOR_LIB)
    known = {v for fix in lib.FIXES.values() for v in (fix.apt, fix.brew, fix.cmd) if v}
    spans = re.findall(r"`([^`\n]+)`", AGENTS.read_text(encoding="utf-8"))
    quoted = [
        s
        for s in spans
        if re.match(
            r"(sudo apt install|brew install|xcode-select|uv python install|claude update|curl)",
            s,
        )
    ]
    assert quoted
    assert [s for s in quoted if s not in known] == []


def test_published_text_has_no_email_or_machine_path():
    for path in (AGENTS, SKILL):
        text = path.read_text(encoding="utf-8")
        assert not EMAIL.search(text) and not MACHINE_PATH.search(text), path
        assert "—" not in text, path


def agents_rows():
    rows = {}
    for line in AGENTS.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip("|").split("|")]
        if line.startswith("| `") and len(cells) == 3:
            rows[cells[0]] = cells[2]
    return rows


def test_runbook_gives_every_sudo_fix_to_the_user():
    text = AGENTS.read_text(encoding="utf-8")
    assert "contains `sudo`" in text
    rows = agents_rows()
    lib = _load("phylax_doctor_lib_rows", DOCTOR_LIB)

    def row(name):
        return next(cell for names, cell in rows.items() if f"`{name}`" in names)

    by_row = {
        "mod": "claude-update",
        "python3": "python3",
        "git": "git",
        "launcher": "tmux",
        "claude": "claude",
        "state-dir": None,
    }
    mixed = {"python3": "The user runs a `sudo` or `xcode-select --install` line with `!`"}
    for name, key in by_row.items():
        fix = lib.FIXES[key] if key else None
        needs_user = fix and ("sudo" in (fix.apt or "") or "xcode-select" in (fix.brew or ""))
        if name in mixed:
            assert mixed[name] in row(name) and "after the user approves" in row(name), name
        elif name == "launcher":
            assert "the user runs the install line with `!`" in row(name), name
        elif needs_user:
            assert "The user runs the fix line with `!`" in row(name), name
        else:
            assert "after the user approves" in row(name), name
    assert "the fix line with `!`" not in row("claude")


def budget_args(**values):
    return [*args(budget_mode=True), *(f"{k}={v}" for k, v in values.items())]


def test_budget_on_without_a_snapshot_says_how_to_chain_it(tmp_path, env):
    proc, found = doctor(tmp_path, budget_args(plugin_data="/data/phylax"), env)
    assert proc.returncode == 0
    status, detail = found["budget"]
    assert status == "optional" and "no snapshot yet" in detail and "so normal" in detail
    assert str(tmp_path / ".claude" / "phylax-budget.json") in detail
    assert (
        "{ python3 /data/phylax/budget_snapshot.py || cat; } | <your status line command>"
        in proc.stdout
    )
    assert found["python3"][0] == "ok"  # the budget hooks run on python3


def test_budget_on_with_a_snapshot_names_the_level_and_the_file(tmp_path, env):
    import json
    import time

    state = tmp_path / ".claude" / "phylax-budget.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    resets = time.time() + 0.8 * 7 * 86400  # a fifth of the week gone
    limits = {"seven_day": {"used_percentage": 40, "resets_at": resets}}
    state.write_text(json.dumps({"rate_limits": limits}))
    _, found = doctor(tmp_path, budget_args(budget_lean_pace="abc"), env)
    status, detail = found["budget"]
    assert status == "ok" and detail.startswith("lean: 7-day window 40% used with 20% of it gone")
    assert str(state) in detail and "budget_lean_pace not a number" in detail


def test_budget_state_file_is_read_and_passed_to_the_snapshot(tmp_path, env):
    target = tmp_path / "elsewhere.json"
    proc, found = doctor(tmp_path, budget_args(budget_state_file=str(target)), env)
    assert str(target) in found["budget"][1]
    assert f"budget_snapshot.py {target} || cat; }} | <your status line command>" in proc.stdout


def test_budget_without_a_data_folder_names_the_default_copy(tmp_path, env):
    proc, _ = doctor(tmp_path, budget_args(), env)
    copy = tmp_path / ".claude" / "plugins" / "data" / "phylax-techne" / "budget_snapshot.py"
    assert f"{{ python3 {copy} || cat; }}" in proc.stdout


def test_a_stale_snapshot_asks_whether_the_step_still_runs(tmp_path, env):
    import os
    import time

    state = tmp_path / ".claude" / "phylax-budget.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text('{"rate_limits": {"five_hour": {"used_percentage": 1, "resets_at": 1}}}')
    old = time.time() - 2 * 86400
    os.utime(state, (old, old))
    proc, found = doctor(tmp_path, budget_args(), env)
    assert found["budget"][0] == "optional" and "h old" in found["budget"][1]
    assert "still runs" in proc.stdout and "|| cat" not in proc.stdout  # not asked to chain again


def test_a_broken_snapshot_gets_its_own_fix(tmp_path, env):
    state = tmp_path / ".claude" / "phylax-budget.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text("not json")
    proc, found = doctor(tmp_path, budget_args(), env)
    assert found["budget"][0] == "optional" and "unreadable" in found["budget"][1]
    assert "is the file the status line step writes" in proc.stdout


def test_crossed_thresholds_are_named(tmp_path, env):
    _, found = doctor(tmp_path, budget_args(budget_lean_pace="30"), env)
    assert "budget_lean_pace above budget_frugal_pace" in found["budget"][1]


def test_budget_line_names_the_session_role(tmp_path, env):
    _, found = doctor(tmp_path, budget_args(), {**env, "PHYLAX_BUDGET_ROLE": "background"})
    assert "this session is background, routed by budget mode" in found["budget"][1]
    _, found = doctor(tmp_path, budget_args(), env)
    assert "this session is interactive, normal routing" in found["budget"][1]


@pytest.mark.parametrize(
    "role",
    [
        {},
        {"PHYLAX_BUDGET": "on"},
        {"PHYLAX_BUDGET_ROLE": "background"},
        {"PHYLAX_BUDGET": "normal"},
    ],
)
def test_budget_line_shows_a_running_pause_under_every_role(tmp_path, env, role):
    import json
    import time

    pause = tmp_path / ".claude" / "phylax-budget-override.json"
    pause.parent.mkdir(parents=True, exist_ok=True)
    pause.write_text(json.dumps({"until": time.time() + 3600}))
    _, found = doctor(tmp_path, budget_args(), {**env, **role})
    assert found["budget"][1].count("paused until") == 1, found["budget"][1]


def _doctor_module():
    return _load("phylax_doctor_timezone", DOCTOR)


@pytest.mark.parametrize(
    ("name", "status"),
    [("", "ok"), ("America/New_York", "ok"), ("Mars/Olympus", "missing"), ("../etc", "missing")],
)
def test_email_timezone_check(name, status):
    check = _doctor_module().timezone(name)
    assert (check.name, check.status) == ("email-timezone", status)
    assert status == "ok" or any("email_timezone" in f for f in check.fixes)


def test_email_timezone_is_na_while_the_greeting_is_off():
    m = _doctor_module()
    platform = m.d.Platform("other", False)
    found = {c.name: c for c in m.checks(platform, m.parse_options([]), m.parse_values([]))}
    assert found["email-timezone"].status == "n/a"
    padded = m.parse_values(["email_timezone=America/New_York "])
    on = m.parse_options(["email_greeting=true"])
    found = {c.name: c for c in m.checks(platform, on, padded)}
    assert found["email-timezone"].status == "ok"  # the hook strips it too
    on = m.parse_options(["email_greeting=true", "email_timezone=Mars/Olympus"])
    found = {
        c.name: c for c in m.checks(platform, on, m.parse_values(["email_timezone=Mars/Olympus"]))
    }
    assert found["email-timezone"].status == "missing"
