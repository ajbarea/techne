"""The techne setup doctor, run as /techne:setup runs it: system python3, stub PATH."""

from __future__ import annotations

import re
import shutil
import subprocess

import pytest
from conftest import DOCTOR_LIB, EMAIL, MACHINE_PATH, ROOT, _load, run_doctor, stub_dir
from conftest import doctor as run_checks

DOCTOR = ROOT / "plugins" / "techne" / "skills" / "setup" / "scripts" / "doctor.py"
PLUGIN = ROOT / "plugins" / "techne"
AGENTS = PLUGIN / "AGENTS.md"
SKELETON = ROOT / "plugins" / "techne" / "skills" / "setup" / "skill-context.template.md"
GH = (
    'case "$1" in --version) echo "gh version 2.45.0 (2025-07-18)";; '
    'auth) [ "$4" = "${SIGNED_IN_HOST:-github.com}" ] && exit 0; '
    'echo "You are not logged into any accounts on $4" >&2; exit 1;; esac'
)
STUBS = {
    "gh": GH,
    "uv": "echo 'uv 0.11.5 (x86_64-unknown-linux-gnu)'",
    "python3": "echo 3.12.3",
    "tmux": "echo 'tmux 3.4'",
}
TOML = 'github_user = "u"\nworkspace_root = "~/w"\n\n[[sisters]]\nname = "a"\n'
GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
}


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, env=GIT_ENV)


@pytest.fixture
def machine(tmp_path):
    """A home with a sister config and Chromium, and a repo with a skill context."""
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "techne.toml").write_text(TOML)
    (home / "ms-playwright" / "chromium-1243").mkdir(parents=True)
    repo = tmp_path / "repo"
    (repo / ".claude").mkdir(parents=True)
    (repo / ".claude" / "skill-context.md").write_text("# ctx\n")
    git(repo, "init", "-q")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "init")
    return home, repo


def doctor(tmp_path, home, repo, stubs=STUBS, env=None, cwd=None, links=("git",)):
    return run_checks(DOCTOR, tmp_path, home, stubs=stubs, links=links, cwd=cwd or repo, env=env)


def test_all_present_is_ready(tmp_path, machine):
    home, repo = machine
    proc, found = doctor(tmp_path, home, repo)
    assert proc.returncode == 0, proc.stdout
    assert proc.stdout.splitlines()[-1] == "result: ready"
    assert {k: v[0] for k, v in found.items()} == {
        "git": "ok",
        "gh": "ok",
        "gh-auth": "ok",
        "uv": "ok",
        "python3": "ok",
        "tmux": "ok",
        "chromium": "ok",
        "lsof": "n/a",
        "skill-context": "ok",
        "techne.toml": "ok",
    }


@pytest.mark.parametrize(
    "drop, fix",
    [
        ("gh", "sudo apt install gh -y"),
        ("uv", "fix: curl -LsSf https://astral.sh/uv/install.sh | sh"),
        ("python3", "fix: uv python install --default 3.12 && uv python update-shell"),
        ("tmux", "fix: sudo apt install tmux"),
    ],
)
def test_each_missing_tool_names_its_fix(tmp_path, machine, drop, fix):
    home, repo = machine
    stubs = {k: v for k, v in STUBS.items() if k != drop}
    proc, found = doctor(tmp_path, home, repo, stubs)
    assert proc.returncode == 1
    assert found[drop][0] == "missing"
    assert fix in proc.stdout
    assert proc.stdout.splitlines()[-1].startswith("result: missing ")


# gh 2.45 exits 0 and prints these lines for a dead token, a bad GH_TOKEN or an unknown host.
def failed_gh(first):
    return (
        'case "$1" in --version) echo "gh version 2.45.0 (2025-07-18)";; '
        f'auth) echo "$4"; echo "  {first}"; echo "  - The token is invalid."; exit 0;; esac'
    )


@pytest.mark.parametrize(
    "marker",
    [
        "X Failed to log in to github.com account u (/c/hosts.yml)",
        "X Failed to log in to github.com using token (GH_TOKEN)",
        "X Failed to log in to ghe.example.com using token (/c/hosts.yml)",
    ],
)
def test_gh_auth_exit_zero_with_a_failure_marker_is_missing(tmp_path, machine, marker):
    home, repo = machine
    proc, found = doctor(tmp_path, home, repo, {**STUBS, "gh": failed_gh(marker)})
    assert proc.returncode == 1 and found["gh-auth"][0] == "missing"
    assert found["gh-auth"][1] == f"github.com: {marker[2:]}"
    assert "  fix: gh auth login --hostname github.com" in proc.stdout.splitlines()


def test_gh_auth_marker_without_the_failed_wording_is_missing(tmp_path, machine):
    home, repo = machine
    _, found = doctor(tmp_path, home, repo, {**STUBS, "gh": failed_gh("X something else")})
    assert found["gh-auth"][0] == "missing"


def test_missing_gh_makes_sign_in_not_applicable(tmp_path, machine):
    home, repo = machine
    _, found = doctor(tmp_path, home, repo, {k: v for k, v in STUBS.items() if k != "gh"})
    assert found["gh-auth"] == ("n/a", "gh is missing")


def test_missing_git_names_its_fix_and_skips_the_repo_check(tmp_path, machine):
    home, repo = machine
    proc, found = doctor(tmp_path, home, repo, links=())
    assert found["git"][0] == "missing" and "fix: sudo apt install git" in proc.stdout
    assert found["skill-context"] == ("n/a", "git is missing")


def test_old_python3_is_missing(tmp_path, machine):
    home, repo = machine
    proc, found = doctor(tmp_path, home, repo, {**STUBS, "python3": "echo 3.10.12"})
    assert found["python3"][0] == "missing"
    assert "3.10.12" in found["python3"][1] and "need 3.11 or newer" in found["python3"][1]
    fixes = [line for line in proc.stdout.splitlines() if line.startswith("  fix")]
    assert fixes == ["  fix: uv python install --default 3.12 && uv python update-shell"]


def test_macos_lines(tmp_path, machine):
    home, repo = machine
    stubs = {k: v for k, v in STUBS.items() if k != "gh"}
    proc, found = doctor(tmp_path, home, repo, stubs, env={"TECHNE_DOCTOR_OS": "macos"})
    assert "  fix: brew install gh" in proc.stdout.splitlines()
    assert found["lsof"][0] == "missing"
    assert "fix: echo 'export PATH=\"$PATH:/usr/sbin\"' >> ~/.zprofile" in proc.stdout
    proc, found = doctor(
        tmp_path, home, repo, {**STUBS, "lsof": "exit 0"}, env={"TECHNE_DOCTOR_OS": "macos"}
    )
    assert found["lsof"][0] == "ok"


def test_unknown_platform_prints_both_labelled_lines(tmp_path, machine):
    home, repo = machine
    stubs = {k: v for k, v in STUBS.items() if k != "tmux"}
    proc, _ = doctor(tmp_path, home, repo, stubs, env={"TECHNE_DOCTOR_OS": "other"})
    lines = proc.stdout.splitlines()
    assert "  fix (Debian/Ubuntu): sudo apt install tmux" in lines
    assert "  fix (macOS): brew install tmux" in lines


def test_optional_gaps_leave_it_ready(tmp_path, machine):
    home, repo = machine
    (home / ".claude" / "techne.toml").unlink()
    (home / "ms-playwright" / "chromium-1243").rmdir()
    proc, found = doctor(tmp_path, home, repo)
    assert proc.returncode == 0
    assert found["chromium"][0] == "optional" and found["techne.toml"][0] == "optional"
    assert "playwright==1.63.0 playwright install chromium" in proc.stdout


def test_partial_sister_config_names_what_it_lacks(tmp_path, machine):
    home, repo = machine
    (home / ".claude" / "techne.toml").write_text('workspace_root = "~/w"\n')
    _, found = doctor(tmp_path, home, repo)
    assert found["techne.toml"] == ("optional", "missing github_user, [[sisters]]")


# Review Focus 3: gh signed in to another host, or GH_HOST set.
def test_gh_signed_in_to_another_host(tmp_path, machine):
    home, repo = machine
    other = {"SIGNED_IN_HOST": "ghe.example.com"}
    proc, found = doctor(tmp_path, home, repo, env=other)
    assert found["gh-auth"][0] == "missing"
    assert found["gh-auth"][1].startswith("github.com: You are not logged into")
    assert "  fix: gh auth login --hostname github.com" in proc.stdout.splitlines()
    proc, found = doctor(tmp_path, home, repo, env={**other, "GH_HOST": "ghe.example.com"})
    assert found["gh-auth"] == ("ok", "signed in to ghe.example.com")


# Review Focus 5: run from a subdirectory, a linked worktree, or outside any repo.
def test_skill_context_resolves_the_toplevel(tmp_path, machine):
    home, repo = machine
    sub = repo / "a" / "b"
    sub.mkdir(parents=True)
    _, found = doctor(tmp_path, home, repo, cwd=sub)
    assert found["skill-context"] == ("ok", str(repo / ".claude" / "skill-context.md"))

    linked = tmp_path / "linked"
    git(repo, "worktree", "add", "-q", str(linked))
    _, found = doctor(tmp_path, home, repo, cwd=linked)
    assert found["skill-context"] == ("ok", str(linked / ".claude" / "skill-context.md"))

    outside = tmp_path / "outside"
    outside.mkdir()
    _, found = doctor(
        tmp_path, home, repo, cwd=outside, env={"GIT_CEILING_DIRECTORIES": str(tmp_path)}
    )
    assert found["skill-context"][0] == "n/a"


def test_missing_skill_context_is_optional_and_offers_the_template(tmp_path, machine):
    home, repo = machine
    git(repo, "rm", "-q", "--cached", ".claude/skill-context.md")
    (repo / ".claude" / "skill-context.md").unlink()
    proc, found = doctor(tmp_path, home, repo)
    assert proc.returncode == 0 and found["skill-context"][0] == "optional"
    assert proc.stdout.splitlines()[-1] == "result: ready"
    fix = next(line for line in proc.stdout.splitlines() if "skill-context.template.md" in line)
    assert fix.startswith("  fix: mkdir -p ")
    assert str(SKELETON) in fix and not (repo / ".claude" / "skill-context.md").exists()


def test_skill_context_fix_quotes_a_path_with_a_space(tmp_path, machine):
    home, _ = machine
    spaced = tmp_path / "sp ace"
    spaced.mkdir()
    git(spaced, "init", "-q")
    proc, found = doctor(tmp_path, home, spaced, cwd=spaced)
    assert found["skill-context"][0] == "optional"
    fix = next(line for line in proc.stdout.splitlines() if "skill-context.template.md" in line)
    assert f"mkdir -p '{spaced}/.claude'" in fix and f"'{spaced}/.claude/skill-context.md'" in fix


def test_techne_toml_keys_inside_a_sisters_table_do_not_count(tmp_path, machine):
    home, repo = machine
    (home / ".claude" / "techne.toml").write_text(
        'workspace_root = "~/w"\n\n[[sisters]]\nname = "a"\ngithub_user = "u"\n'
    )
    _, found = doctor(tmp_path, home, repo)
    assert found["techne.toml"] == ("optional", "missing github_user")


def test_running_the_doctor_leaves_no_bytecode(tmp_path, machine):
    home, repo = machine
    plugin = tmp_path / "plugin" / "techne"
    shutil.copytree(PLUGIN, plugin, ignore=shutil.ignore_patterns("__pycache__", "evals"))

    def listing():
        return sorted(p.relative_to(plugin).as_posix() for p in plugin.rglob("*"))

    before = listing()
    path = stub_dir(tmp_path, STUBS, ("git",))
    script = plugin / "skills" / "setup" / "scripts" / "doctor.py"
    proc = run_doctor(script, path=path, home=home, cwd=repo, env={"PYTHONDONTWRITEBYTECODE": ""})
    assert "Traceback" not in proc.stderr and proc.stdout
    assert listing() == before


def test_skeleton_is_the_conventions_sections():
    text = SKELETON.read_text(encoding="utf-8")
    assert text.startswith("# Skill context\n") and "## audit" in text and "## elenchus" in text
    assert "````" not in text


def test_runbook_restates_only_fixes_from_the_table():
    """Every install command AGENTS.md quotes is a FIXES value, and the Playwright pin matches."""
    lib = _load("techne_doctor_lib_runbook", DOCTOR_LIB)
    known = {v for fix in lib.FIXES.values() for v in (fix.apt, fix.brew, fix.cmd) if v}
    spans = re.findall(r"`([^`\n]+)`", AGENTS.read_text(encoding="utf-8"))
    quoted = [
        s
        for s in spans
        if re.match(r"(sudo apt install|brew install|xcode-select|uv python install|uv run)", s)
    ]
    assert quoted
    assert [s for s in quoted if s not in known] == []
    assert lib.PLAYWRIGHT_PIN.split("==")[1] in AGENTS.read_text(encoding="utf-8")


def test_published_text_has_no_email_or_machine_path():
    for path in (AGENTS, SKELETON, DOCTOR.parent.parent / "SKILL.md"):
        text = path.read_text(encoding="utf-8")
        assert not EMAIL.search(text) and not MACHINE_PATH.search(text), path


def agents_rows():
    rows = {}
    for line in AGENTS.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip("|").split("|")]
        if line.startswith("| `") and len(cells) == 3:
            rows[cells[0]] = cells[2]
    return rows


def test_runbook_gives_every_sudo_and_browser_fix_to_the_user():
    text = AGENTS.read_text(encoding="utf-8")
    assert "contains `sudo`" in text and "!gh auth login --hostname" in text
    rows = agents_rows()
    lib = _load("techne_doctor_lib_rows", DOCTOR_LIB)

    def row(key):
        return next(cell for name, cell in rows.items() if f"`{key}`" in name)

    for key in ("git", "gh", "tmux"):
        assert "sudo" in (lib.FIXES[key].apt or ""), key
        assert "The user runs the fix line with `!`" in row(key), key
    for key in ("uv", "chromium"):
        assert "after the user approves" in row(key), key
