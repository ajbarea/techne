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
    "restart_on_update",
)
STUBS = {
    "python3": "echo 3.9.6",
    "claude": "echo '2.1.296 (Claude Code)'",
    "tmux": "echo 'tmux 3.4'",
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
    for name in ("mod", "python3", "git", "proc", "launcher", "claude", "state-dir"):
        assert found[name][0] == "n/a", name


# Review Focus 4: an unset option in every form it can arrive in.
def test_unset_options_in_every_form_read_as_off(tmp_path, env):
    argv = [
        "block_attribution_trailers=${user_config.block_attribution_trailers}",
        "block_commits_md=",
        "warn_main_checkout_commit=maybe",
        "unknown_key=true",
        "not-an-assignment",
    ]
    proc, found = doctor(tmp_path, argv, env)
    assert proc.returncode == 0
    for key in OPTIONS:
        assert found[key][0] == "n/a" and found[key][1].startswith("not set, so off"), key
    proc, found = doctor(tmp_path, ["block_commits_md=TRUE"], env)
    assert found["block_commits_md"] == ("ok", "on")


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


def test_old_claude_code_falls_back_to_the_command_hook(tmp_path, env):
    old = {**STUBS, "claude": "echo '2.1.200 (Claude Code)'"}
    proc, found = doctor(tmp_path, args(block_attribution_trailers=True), env, stubs=old)
    assert proc.returncode == 0 and found["mod"][0] == "optional"
    assert "  fix: claude update" in proc.stdout.splitlines()
    no_claude = {k: v for k, v in STUBS.items() if k != "claude"}
    proc, found = doctor(tmp_path, args(block_attribution_trailers=True), env, stubs=no_claude)
    assert proc.returncode == 0 and found["mod"][0] == "optional"


def test_restart_on_without_proc(tmp_path, env):
    extra = {"PHYLAX_RESTART_PROC": str(tmp_path / "nowhere")}
    proc, found = doctor(tmp_path, args(restart_on_update=True), env, extra=extra)
    assert proc.returncode == 1 and found["proc"][0] == "missing"
    assert "Linux and WSL only" in found["proc"][1]


def test_restart_launcher(tmp_path, env):
    no_tmux = {k: v for k, v in STUBS.items() if k != "tmux"}
    proc, found = doctor(tmp_path, args(restart_on_update=True), env, stubs=no_tmux)
    assert found["launcher"][0] == "missing"
    assert "  fix: sudo apt install tmux" in proc.stdout.splitlines()
    wsl = {**no_tmux, "wt.exe": "exit 0"}
    proc, found = doctor(
        tmp_path, args(restart_on_update=True), env, stubs=wsl, extra={"TECHNE_DOCTOR_WSL": "1"}
    )
    assert found["launcher"][0] == "ok" and "Windows Terminal" in found["launcher"][1]


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
    for name, key in by_row.items():
        fix = lib.FIXES[key] if key else None
        needs_user = fix and ("sudo" in (fix.apt or "") or "xcode-select" in (fix.brew or ""))
        if needs_user:
            assert "The user runs the fix line with `!`" in row(name), name
        else:
            assert "after the user approves" in row(name), name
    assert "the fix line with `!`" not in row("claude")
