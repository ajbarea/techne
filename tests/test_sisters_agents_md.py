"""Tests for techne:sisters' agent instruction file check (check 15).

The failure the check exists for is silent: a CLAUDE.md that Claude Code loads
in place of the repo's AGENTS.md. Each test builds a real git repository so
git decides what is tracked, and asserts on the line the check prints.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from conftest import AGENTS_MD_SCRIPT

OK = "AGENTS.md, nothing shadows it ✓"


def repo(tmp_path: Path, files: dict[str, str], untracked: dict[str, str] | None = None) -> Path:
    root = tmp_path / "r"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8", newline="")
    if files:
        subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    for rel, text in (untracked or {}).items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    return root


ROOT = (
    " stops Claude Code reading AGENTS.md directly, and an @AGENTS.md import in it is "
    "external for a session started in a subdirectory → move its content into AGENTS.md "
    "and delete it"
)
LOCAL = (
    " stops Claude Code reading AGENTS.md for you → move it to ~/.claude/CLAUDE.md, "
    "or set Project instructions to claude-md-and-agents-md"
)


def nested(rel: str, where: str) -> str:
    return (
        f"{rel} replaces AGENTS.md for a session started in {where}/ → "
        "move its content into AGENTS.md and delete it"
    )


@pytest.mark.parametrize(
    "files",
    [
        {"AGENTS.md": "# a\n"},
        {"AGENTS.md": "# a\n", "sub/AGENTS.md": "# s\n"},
    ],
    ids=["agents-only", "nested-agents"],
)
def test_passes(am, tmp_path, files):
    assert am.check(repo(tmp_path, files)) == []


def test_no_agents(am, tmp_path):
    assert am.check(repo(tmp_path, {"README.md": "x\n"})) == ["no committed AGENTS.md → add one"]


@pytest.mark.parametrize(
    ("files", "untracked", "expect"),
    [
        ({"AGENTS.md": "# a\n", "CLAUDE.md": "@AGENTS.md\n"}, None, "CLAUDE.md" + ROOT),
        ({"AGENTS.md": "# a\n", "CLAUDE.md": "rules\n"}, None, "CLAUDE.md" + ROOT),
        ({"AGENTS.md": "# a\n"}, {"CLAUDE.md": "written by /init\n"}, "CLAUDE.md" + ROOT),
        (
            {"AGENTS.md": "# a\n", ".claude/CLAUDE.md": "@../AGENTS.md\n"},
            None,
            ".claude/CLAUDE.md" + ROOT,
        ),
        ({"AGENTS.md": "# a\n"}, {".claude/CLAUDE.md": "x\n"}, ".claude/CLAUDE.md" + ROOT),
        ({"AGENTS.md": "# a\n", "CLAUDE.local.md": "mine\n"}, None, "CLAUDE.local.md" + LOCAL),
        ({"AGENTS.md": "# a\n"}, {"CLAUDE.local.md": "mine\n"}, "CLAUDE.local.md" + LOCAL),
        (
            {"AGENTS.md": "# a\n", "sub/AGENTS.md": "# s\n", "sub/CLAUDE.md": "x\n"},
            None,
            nested("sub/CLAUDE.md", "sub"),
        ),
        ({"AGENTS.md": "# a\n"}, {"sub/CLAUDE.md": "x\n"}, nested("sub/CLAUDE.md", "sub")),
        (
            {"AGENTS.md": "# a\n", ".gitignore": "CLAUDE.local.md\n"},
            {"sub/CLAUDE.local.md": "x\n"},
            nested("sub/CLAUDE.local.md", "sub"),
        ),
        (
            {"AGENTS.md": "# a\n", ".gitignore": "CLAUDE.local.md\n"},
            {"CLAUDE.local.md": "x\n"},
            "CLAUDE.local.md" + LOCAL,
        ),
        (
            {"AGENTS.md": "# a\n"},
            {"sub/.claude/CLAUDE.md": "x\n"},
            nested("sub/.claude/CLAUDE.md", "sub"),
        ),
        (
            {"AGENTS.md": "# a\n", "my dir/CLAUDE.md": "x\n"},
            None,
            nested("my dir/CLAUDE.md", "my dir"),
        ),
        ({"AGENTS.md": "# a\n", "dé/CLAUDE.md": "x\n"}, None, nested("dé/CLAUDE.md", "dé")),
    ],
    ids=[
        "root-import",
        "root-plain",
        "root-untracked",
        "dot-claude",
        "dot-claude-untracked",
        "local-tracked",
        "local-untracked",
        "nested-tracked",
        "nested-untracked",
        "nested-local-ignored",
        "root-local-ignored",
        "nested-dot-claude-untracked",
        "space-in-path",
        "non-ascii-path",
    ],
)
def test_flags(am, tmp_path, files, untracked, expect):
    assert am.check(repo(tmp_path, files, untracked)) == [expect]


def test_ignored_vendored_claude_md_is_not_flagged(am, tmp_path):
    root = repo(
        tmp_path,
        {"AGENTS.md": "# a\n", ".gitignore": "node_modules/\n"},
        {"node_modules/pkg/CLAUDE.md": "vendored\n"},
    )
    assert am.check(root) == []


def test_ignored_vendored_claude_local_md_is_not_flagged(am, tmp_path):
    root = repo(
        tmp_path,
        {"AGENTS.md": "# a\n", ".gitignore": "node_modules/\n"},
        {"node_modules/pkg/CLAUDE.local.md": "vendored\n"},
    )
    assert am.check(root) == []


def test_ignored_nested_claude_md_is_flagged(am, tmp_path):
    root = repo(
        tmp_path,
        {"AGENTS.md": "# a\n", ".gitignore": "CLAUDE.md\n"},
        {"sub/CLAUDE.md": "x\n"},
    )
    assert am.check(root) == [nested("sub/CLAUDE.md", "sub")]


def test_ignored_root_claude_md_is_flagged(am, tmp_path):
    root = repo(
        tmp_path,
        {"AGENTS.md": "# a\n", ".gitignore": "CLAUDE.md\n"},
        {"CLAUDE.md": "x\n"},
    )
    assert am.check(root) == ["CLAUDE.md" + ROOT]


def test_dot_claude_local_md_is_not_flagged(am, tmp_path):
    root = repo(tmp_path, {"AGENTS.md": "# a\n", ".claude/CLAUDE.local.md": "x\n"})
    assert am.check(root) == []


def test_literal_pathspecs_env_does_not_hide_files(am, tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_LITERAL_PATHSPECS", "1")
    root = repo(tmp_path, {"AGENTS.md": "# a\n"}, {"sub/CLAUDE.md": "x\n"})
    assert am.check(root) == [nested("sub/CLAUDE.md", "sub")]


def test_directory_named_claude_md_is_not_flagged(am, tmp_path):
    root = repo(tmp_path, {"AGENTS.md": "# a\n", "CLAUDE.md/notes.txt": "x\n"})
    (root / "other" / "CLAUDE.local.md").mkdir(parents=True)
    assert am.check(root) == []


def test_symlink_is_flagged(am, tmp_path):
    root = repo(tmp_path, {"AGENTS.md": "# a\n"})
    (root / "CLAUDE.md").symlink_to("AGENTS.md")
    subprocess.run(["git", "-C", str(root), "add", "CLAUDE.md"], check=True)
    [finding] = am.check(root)
    assert "symlink" in finding and "delete it" in finding


def test_missing_and_non_git(am, tmp_path):
    assert am.check(tmp_path / "absent") == [f"not cloned at {tmp_path / 'absent'}"]
    plain = tmp_path / "plain"
    plain.mkdir()
    assert "not a git repository" in am.check(plain)[0]


def test_cli_prints_per_repo_and_exits_zero(tmp_path):
    repo(tmp_path, {"README.md": "x\n"})
    out = subprocess.run(
        ["python3", str(AGENTS_MD_SCRIPT), str(tmp_path), "r", "absent"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert out.returncode == 0
    assert out.stdout.splitlines() == [
        "r: no committed AGENTS.md → add one",
        f"absent: not cloned at {tmp_path / 'absent'}",
    ]


def test_clean_repo_prints_pass_line(tmp_path):
    repo(tmp_path, {"AGENTS.md": "# a\n"})
    out = subprocess.run(
        ["python3", str(AGENTS_MD_SCRIPT), str(tmp_path), "r"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert out.stdout == f"r: {OK}\n"


def test_claude_md_above_the_repo_is_flagged(am, tmp_path):
    root = repo(tmp_path, {"AGENTS.md": "# a\n"})
    (tmp_path / "CLAUDE.md").write_text("workspace notes\n")
    assert am.check(root) == [
        f"{tmp_path / 'CLAUDE.md'} sits above the repo and replaces AGENTS.md → move it out"
    ]


def test_directory_named_claude_md_above_the_repo_is_not_flagged(am, tmp_path):
    root = repo(tmp_path, {"AGENTS.md": "# a\n"})
    (tmp_path / "CLAUDE.md").mkdir()
    assert am.check(root) == []


def test_user_claude_md_is_not_above_the_repo(am, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "CLAUDE.md").write_text("user memory\n")
    assert am.check(repo(tmp_path, {"AGENTS.md": "# a\n"})) == []
