"""elenchus's own_checks.py: which changed files are part of the change's own checks."""

from __future__ import annotations

import os
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
        "bench/compare.py",
        "bench/baseline-ci.json",
        "plugins/phylax/.claude-plugin/plugin.json",
        "web/__tests__/app.ts",
        "CODEOWNERS",
        "build/rules.mk",
        ".golangci.yml",
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


def _own(repo, *args, env=None):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo), *args],
        capture_output=True,
        text=True,
        env=env,
    )


def _listed(out):
    lines = out.stdout.split("\n")
    assert lines[0].startswith("head "), out.stderr
    return [line for line in lines[1:] if line]


@pytest.fixture
def clone(tmp_path):
    """A clone whose two-commit PR branch moves a test out of tests/ (first commit) and edits
    app code (second), while the base moved on after the branch point."""
    up = tmp_path / "up"
    up.mkdir()
    _git(up, "init", "-q", "-b", "main")
    (up / "tests").mkdir()
    (up / "tests" / "test_a.py").write_text("def test_a():\n    assert 1\n")
    (up / "app.py").write_text("x = 1\n")
    (up / "Makefile").write_text("lint:\n\tpython tools/lint_rules.py\n")
    (up / "tools").mkdir()
    (up / "tools" / "lint_rules.py").write_text("RULES = 1\n")
    _git(up, "add", ".")
    _git(up, "commit", "-qm", "base")
    c = tmp_path / "clone"
    _git(tmp_path, "clone", "-q", str(up), str(c))
    (up / "README").write_text("later\n")
    _git(up, "add", ".")
    _git(up, "commit", "-qm", "base moves on")
    _git(c, "fetch", "-q")
    _git(c, "checkout", "-q", "-b", "pr")
    _git(c, "mv", "tests/test_a.py", "kept.py")
    (c / "tools" / "lint_rules.py").write_text("RULES = 0\n")
    _git(c, "commit", "-qam", "move the test out, loosen the lint the Makefile runs")
    (c / "app.py").write_text("x = 2\n")
    _git(c, "commit", "-qam", "app change")
    return c


EXPECTED = ["tests/test_a.py", "tools/lint_rules.py"]


def _rev(repo, rev):
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", rev], capture_output=True, text=True, check=True
    ).stdout.strip()


def test_it_lists_the_whole_branchs_checks_and_not_the_bases(clone):
    # Both commits of the branch, not the base's own later change; the file the base's
    # Makefile runs counts, though no name rule matches it.
    out = _own(clone, _rev(clone, "origin/main"))
    assert out.returncode == 0 and _listed(out) == EXPECTED


def test_it_reads_by_commit_from_any_checkout_or_subfolder(clone):
    head, base = _rev(clone, "pr"), _rev(clone, "origin/main")
    _git(clone, "checkout", "-q", "--detach", "origin/main")
    out = _own(clone / "tests", base, "--head", head)
    assert out.stdout.startswith(f"head {head}") and _listed(out) == EXPECTED


@pytest.mark.parametrize("value", ["origin/main", "main", "HEAD", ""])
def test_a_ref_name_is_refused(clone, value):
    out = _own(clone, value)
    assert out.returncode != 0 and "not a full commit id" in out.stderr and out.stdout == ""


def test_an_exported_git_dir_does_not_redirect_it(clone, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    _git(other, "init", "-q")
    env = {**os.environ, "GIT_DIR": str(other / ".git"), "GIT_WORK_TREE": str(other)}
    assert _listed(_own(clone, _rev(clone, "origin/main"), env=env)) == EXPECTED


def test_quoted_paths_are_read_as_paths(clone):
    (clone / ".github" / "workflows").mkdir(parents=True)
    (clone / ".github" / "workflows" / "ci-\u00e9.yml").write_text("on: push\n")
    (clone / "tests" / 'test_"q".py').parent.mkdir(exist_ok=True)
    (clone / "tests" / 'test_"q".py').write_text("x = 1\n")
    _git(clone, "add", ".")
    _git(clone, "commit", "-qm", "odd names")
    listed = _listed(_own(clone, _rev(clone, "origin/main")))
    assert ".github/workflows/ci-\u00e9.yml" in listed and 'tests/test_"q".py' in listed


@pytest.mark.parametrize(
    ("gate", "text", "named"),
    [
        ("Makefile", "lint:\n\tpython ./tools/g.py\n", True),
        ("Makefile", "lint:\n\tpython $(CURDIR)/tools/g.py\n", True),
        ("Makefile", 'lint:\n\tpython "tools/g.py" --strict\n', True),
        ("Makefile", "lint:\n\truff check tools/*.py\n", True),
        ("Makefile", "# tools/g.py is old\nlint:\n\techo ok\n", False),
        ("Makefile", "lint:\n\truff check *\n", False),
        (
            ".github/workflows/ci.yml",
            "jobs:\n  t:\n    steps:\n      - run: python tools/g.py\n",
            True,
        ),
        (
            ".github/workflows/ci.yml",
            "jobs:\n  t:\n    steps:\n      - run: python ${{ github.workspace }}/tools/g.py\n",
            True,
        ),
        (".github/workflows/ci.yml", "on:\n  push:\n    paths:\n      - 'tools/**'\n", False),
        (".github/workflows/ci.yml", "on:\n  push:\n    paths: ['tools/g.py']\n", False),
        (".pre-commit-config.yaml", "repos:\n  - hooks:\n      - entry: python tools/g.py\n", True),
    ],
)
def test_a_file_a_gate_runs_is_listed_however_it_is_named(tmp_path, gate, text, named):
    up = tmp_path / "up"
    (up / "tools").mkdir(parents=True)
    _git(up, "init", "-q", "-b", "main")
    (up / gate).parent.mkdir(parents=True, exist_ok=True)
    (up / gate).write_text(text)
    (up / "tools" / "g.py").write_text("x = 1\n")
    _git(up, "add", ".")
    _git(up, "commit", "-qm", "base")
    base = _rev(up, "HEAD")
    _git(up, "checkout", "-q", "-b", "pr")
    (up / "tools" / "g.py").write_text("x = 0\n")
    _git(up, "commit", "-qam", "loosen it")
    assert (_listed(_own(up, base)) == ["tools/g.py"]) is named


def test_no_merge_base_is_said_in_one_line(clone, tmp_path):
    shallow = tmp_path / "shallow"
    _git(
        tmp_path,
        "clone",
        "-q",
        "--depth=1",
        "--single-branch",
        "-b",
        "pr",
        f"file://{clone}",
        str(shallow),
    )
    base = _rev(clone, "origin/main")
    _git(shallow, "fetch", "-q", "--depth=1", "origin", base)
    out = _own(shallow, base)
    assert out.returncode != 0 and out.stderr.startswith("own_checks:")
    assert "Traceback" not in out.stderr


def test_a_branch_with_no_checks_prints_none(clone):
    _git(clone, "checkout", "-q", "-b", "docs", "origin/main")
    (clone / "README").write_text("x\n")
    _git(clone, "add", ".")
    _git(clone, "commit", "-qm", "docs")
    out = _own(clone, _rev(clone, "origin/main"))
    assert out.stdout.split("\n")[1] == "none"


def test_a_workflow_named_file_is_listed_from_a_subfolder(tmp_path):
    up = tmp_path / "up"
    (up / "tools").mkdir(parents=True)
    (up / ".github" / "workflows").mkdir(parents=True)
    _git(up, "init", "-q", "-b", "main")
    (up / ".github" / "workflows" / "ci.yml").write_text(
        "jobs:\n  t:\n    steps:\n      - run: python tools/g.py\n"
    )
    (up / "tools" / "g.py").write_text("x = 1\n")
    _git(up, "add", ".")
    _git(up, "commit", "-qm", "base")
    base = _rev(up, "HEAD")
    _git(up, "checkout", "-q", "-b", "pr")
    (up / "tools" / "g.py").write_text("x = 0\n")
    _git(up, "commit", "-qam", "loosen it")
    assert _listed(_own(up / "tools", base)) == ["tools/g.py"]
