"""elenchus's own_checks.py: which changed files are part of the change's own checks."""

from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "plugins" / "techne" / "skills" / "elenchus" / "scripts" / "own_checks.py"
sys.path.insert(0, str(SCRIPT.parent))

import own_checks  # noqa: E402  # ty: ignore[unresolved-import]


@pytest.mark.parametrize(
    "path",
    [
        ".github/workflows/validate.yml",
        ".github/actions/check-action-pins/action.yml",
        ".claude/skill-context.md",
        ".claude/settings.json",
        "plugins/phylax/hooks/git_guards.py",
        "plugins/phylax/hooks/hooks.json",
        "plugins/techne/skills/elenchus/references/bug-classes.md",
        "plugins/techne/skills/elenchus/SKILL.md",
        "tests/test_git_guards.py",
        "src/pkg/test_util.py",
        "web/app.spec.ts",
        "pkg/thing_test.go",
        "scripts/check_action_pins.sh",
        "Makefile",
        "pyproject.toml",
        ".pre-commit-config.yaml",
        ".gitleaksignore",
        "mutation/equivalent.toml",
        "REVIEW.md",
        "docs/sub/conftest.py",
        # Files these repos use today.
        ".gitlab-ci.yml",
        "ruff.toml",
        ".gitleaks.toml",
        "biome.json",
        "eslint.config.mjs",
        "vitest.config.mts",
        "scripts/mutation.py",
        "scripts/validate_skill_frontmatter.py",
        "scripts/install_gitleaks.sh",
        "plugins/techne/_shared/skill_context.sh",
        "plugins/techne/hooks/board_add.py",
        "plugins/phylax/skills/setup/scripts/doctor.py",
        "hooks/stop.sh",
        "justfile",
        ".coveragerc",
        "codecov.yaml",
        ".codecov.yml",
        ".pre-commit-config.yml",
        "crate/src/lib_test.rs",
        "spec/models/user_spec.rb",
    ],
)
def test_a_check_is_listed(path):
    assert own_checks.is_check(path)


@pytest.mark.parametrize(
    "path",
    [
        "README.md",
        "docs/skills/elenchus.md",
        "plugins/schole/schole/d2l.py",
        "plugins/techne/skills/sisters/SKILL.md",
        "src/testing_utils.py",
        "contest.py",
        "scripts/checker.sh",
        "hooksmith/notes.md",
        "src/hooks/useAuth.ts",
        "app/hooks/session.py",
        "docs/hooks/intro.md",
        "src/check_balance.py",
    ],
)
def test_other_files_are_not(path):
    assert not own_checks.is_check(path)


def _git(cwd, *args):
    subprocess.run(
        ["git", "-c", "user.email=a@example.com", "-c", "user.name=A", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def _own(repo, *args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo), *args],
        capture_output=True,
        text=True,
    )


@pytest.fixture
def clone(tmp_path):
    """A clone whose PR branch moves a test out of tests/ and edits app code, while the
    base moved on after the branch point."""
    up = tmp_path / "up"
    up.mkdir()
    _git(up, "init", "-q", "-b", "main")
    (up / "tests").mkdir()
    (up / "tests" / "test_a.py").write_text("def test_a():\n    assert 1\n")
    (up / "app.py").write_text("x = 1\n")
    _git(up, "add", ".")
    _git(up, "commit", "-qm", "base")
    c = tmp_path / "clone"
    _git(tmp_path, "clone", "-q", str(up), str(c))
    (up / "Makefile").write_text("all:\n")
    _git(up, "add", ".")
    _git(up, "commit", "-qm", "base moves on")
    _git(c, "fetch", "-q")
    _git(c, "checkout", "-q", "-b", "pr")
    _git(c, "mv", "tests/test_a.py", "kept.py")
    (c / "app.py").write_text("x = 2\n")
    _git(c, "commit", "-qam", "move the test out")
    return c


@pytest.mark.parametrize("args", [["origin/main"], [], ["refs/remotes/origin/main"]])
def test_it_lists_a_branchs_checks_by_old_name_and_not_the_bases(clone, args):
    # Three dots: the base's own later Makefile change is not the PR's.
    out = _own(clone, *args)
    assert out.returncode == 0 and out.stdout.split() == ["tests/test_a.py"]


def test_a_shadowing_tag_is_refused_not_used(clone):
    _git(clone, "tag", "origin/main")
    out = _own(clone, "origin/main")
    assert out.returncode != 0 and "ambiguous" in out.stderr and out.stdout == ""


def test_a_branch_with_no_checks_prints_none(clone):
    _git(clone, "checkout", "-q", "-b", "docs", "origin/main")
    (clone / "README").write_text("x\n")
    _git(clone, "add", ".")
    _git(clone, "commit", "-qm", "docs")
    assert _own(clone).stdout.strip() == "none"
