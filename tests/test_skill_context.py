"""Tests for _shared/skill_context.sh, which every skill uses to load the target repo's context."""

from __future__ import annotations

import os
import pathlib
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
RESOLVER = ROOT / "plugins" / "techne" / "_shared" / "skill_context.sh"


def _repo(path: pathlib.Path, marker: str | None) -> pathlib.Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    if marker is not None:
        (path / ".claude").mkdir()
        (path / ".claude" / "skill-context.md").write_text(f"## {marker}\n")
    (path / "docs").mkdir()
    (path / "docs" / "README.md").write_text("x\n")
    return path


@pytest.fixture
def repos(tmp_path):
    return _repo(tmp_path / "here", "HERE"), _repo(tmp_path / "there", "THERE")


def _run(cwd: pathlib.Path, *args: str, env: dict[str, str] | None = None) -> str:
    return subprocess.run(
        ["bash", str(RESOLVER), *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    ).stdout


def test_no_argument_reads_the_cwd_repo(repos):
    here, _ = repos
    out = _run(here)
    assert "## HERE" in out
    assert out.splitlines()[0] == f"<!-- skill-context: {here} -->"


def test_subdirectory_cwd_still_finds_the_repo_root(repos):
    here, _ = repos
    assert "## HERE" in _run(here / "docs")


@pytest.mark.parametrize("target", ["docs/README.md", "docs", "."])
def test_path_in_another_repo_reads_that_repo(repos, target):
    here, there = repos
    out = _run(here, str(there / target))
    assert "## THERE" in out
    assert "## HERE" not in out


def test_relative_path_into_another_repo(repos):
    here, _ = repos
    assert "## THERE" in _run(here, "../there/docs/README.md")


@pytest.mark.parametrize("arg", ["42", "high", "fix/some-branch", "nonexistent/file.md"])
def test_non_path_argument_falls_back_to_cwd(repos, arg):
    here, _ = repos
    assert "## HERE" in _run(here, arg)


def test_repo_without_context_names_the_root(repos, tmp_path):
    here, _ = repos
    bare = _repo(tmp_path / "bare", None)
    out = _run(here, str(bare))
    assert out.startswith("(no .claude/skill-context.md in ")
    assert str(bare) in out


def test_directory_outside_any_repo(tmp_path):
    loose = tmp_path / "loose"
    loose.mkdir()
    out = _run(loose)
    assert out.startswith("(no .claude/skill-context.md in ")
    assert str(loose) in out


def test_exported_git_dir_does_not_redirect_resolution(repos):
    """A git hook exports GIT_DIR; the resolver must still follow the target path."""
    here, there = repos
    env = {**os.environ, "GIT_DIR": str(here / ".git"), "GIT_WORK_TREE": str(here)}
    assert "## THERE" in _run(here, str(there / "docs"), env=env)


# The load-time line is inlined in each skill because a `bash <script>` injection fails
# the permission check outside bypass mode, while a read-only cat passes. It must stay
# identical everywhere and keep resolving the git root.
LOAD_LINE = (
    'echo "<!-- skill-context: $(git rev-parse --show-toplevel 2>/dev/null || pwd) -->"; '
    'cat "$(git rev-parse --show-toplevel 2>/dev/null || pwd)/.claude/skill-context.md" '
    '2>/dev/null || echo "(no .claude/skill-context.md in this repo)"'
)
SKILLS = ROOT / "plugins" / "techne" / "skills"


def _injection_lines() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for skill in sorted(SKILLS.glob("*/SKILL.md")):
        blocks = skill.read_text(encoding="utf-8").split("```!\n")[1:]
        lines = [b.split("\n```", 1)[0] for b in blocks]
        hits = [ln for ln in lines if "skill-context.md" in ln]
        if hits:
            found[skill.parent.name] = hits
    return found


def test_every_skill_uses_the_canonical_load_line():
    found = _injection_lines()
    assert len(found) >= 7, found.keys()
    for name, lines in found.items():
        assert lines == [LOAD_LINE], name


def _load(cwd: pathlib.Path) -> str:
    return subprocess.run(
        ["bash", "-c", LOAD_LINE], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def test_load_line_reads_the_root_from_a_subdirectory(repos):
    here, _ = repos
    out = _load(here / "docs")
    assert out.splitlines()[0] == f"<!-- skill-context: {here} -->"
    assert "## HERE" in out


def test_load_line_outside_a_repo(tmp_path):
    out = _load(tmp_path)
    assert out.splitlines() == [
        f"<!-- skill-context: {tmp_path} -->",
        "(no .claude/skill-context.md in this repo)",
    ]
