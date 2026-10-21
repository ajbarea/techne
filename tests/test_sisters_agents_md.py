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


@pytest.mark.parametrize(
    "files",
    [
        {"AGENTS.md": "# a\n"},
        {"AGENTS.md": "# a\n", "CLAUDE.md": "@AGENTS.md\n"},
        {"AGENTS.md": "# a\n", "CLAUDE.md": "<!-- c -->\n@./AGENTS.md\n\n## Claude\n"},
        {"AGENTS.md": "# a\n", "CLAUDE.md": "Read @AGENTS.md first.\n"},
        {"AGENTS.md": "# a\n", "CLAUDE.md": "@AGENTS.md\r\n## Claude\r\n"},
        {"AGENTS.md": "# a\n", ".claude/CLAUDE.md": "@../AGENTS.md\n"},
        {"AGENTS.md": "# a\n", "CLAUDE.md": "@AGENTS.md#setup\n"},
        {
            "AGENTS.md": "# a\n",
            "CLAUDE.md": "@docs/claude.md\n",
            "docs/claude.md": "@../AGENTS.md\n",
        },
        # One file at a level importing AGENTS.md loads it for the whole level.
        {"AGENTS.md": "# a\n", "CLAUDE.md": "@AGENTS.md\n", "CLAUDE.local.md": "mine\n"},
        {"AGENTS.md": "# a\n", "CLAUDE.md": "@AGENTS.md\n", ".claude/CLAUDE.md": "x\n"},
    ],
    ids=[
        "agents-only",
        "import",
        "dot-slash-mid-file",
        "inline",
        "crlf",
        "dot-claude-up",
        "anchor",
        "via-another-file",
        "local-beside-import",
        "dot-claude-beside-import",
    ],
)
def test_passes(am, tmp_path, files):
    assert am.check(repo(tmp_path, files)) == []


@pytest.mark.parametrize(
    ("files", "untracked", "expect"),
    [
        ({"README.md": "x\n"}, None, "no committed AGENTS.md"),
        ({"AGENTS.md": "# a\n", "CLAUDE.md": "rules\n"}, None, "does not import AGENTS.md"),
        ({"AGENTS.md": "# a\n"}, {"CLAUDE.md": "written by /init\n"}, "CLAUDE.md does not import"),
        ({"AGENTS.md": "# a\n"}, {".claude/CLAUDE.md": "x\n"}, ".claude/CLAUDE.md does not import"),
        ({"AGENTS.md": "# a\n"}, {"CLAUDE.local.md": "mine\n"}, "CLAUDE.local.md does not import"),
        # Imports resolve from the importing file: this one names .claude/AGENTS.md.
        ({"AGENTS.md": "# a\n", ".claude/CLAUDE.md": "@AGENTS.md\n"}, None, "or add @../AGENTS.md"),
        ({"AGENTS.md": "# a\n", "CLAUDE.md": "```\n@AGENTS.md\n```\n"}, None, "does not import"),
        ({"AGENTS.md": "# a\n", "CLAUDE.md": "See `@AGENTS.md`.\n"}, None, "does not import"),
        # Claude Code keeps trailing punctuation and needs whitespace before the @.
        ({"AGENTS.md": "# a\n", "CLAUDE.md": "See @AGENTS.md.\n"}, None, "does not import"),
        ({"AGENTS.md": "# a\n", "CLAUDE.md": "(@AGENTS.md)\n"}, None, "does not import"),
        ({"AGENTS.md": "# a\n", "CLAUDE.md": "see:@AGENTS.md\n"}, None, "does not import"),
        ({"AGENTS.md": "# a\n", "CLAUDE.md": "<!-- @AGENTS.md -->\n"}, None, "does not import"),
        ({"AGENTS.md": "# a\n", "CLAUDE.md": "x\n\n    @AGENTS.md\n"}, None, "does not import"),
        ({"AGENTS.md": "# a\n"}, {"CLAUDE.local.md": "mine\n"}, "add @AGENTS.md to it"),
        (
            {"AGENTS.md": "# a\n", "sub/AGENTS.md": "# s\n", "sub/CLAUDE.md": "x\n"},
            None,
            "sub/CLAUDE.md replaces AGENTS.md for a session started in sub/",
        ),
        (
            {"AGENTS.md": "# a\n", "my dir/AGENTS.md": "# s\n", "my dir/CLAUDE.md": "x\n"},
            None,
            "my dir/CLAUDE.md replaces AGENTS.md",
        ),
        (
            {"AGENTS.md": "# a\n", "dé/AGENTS.md": "# s\n", "dé/CLAUDE.md": "x\n"},
            None,
            "dé/CLAUDE.md replaces AGENTS.md",
        ),
    ],
    ids=[
        "no-agents",
        "no-import",
        "untracked-init",
        "untracked-dot-claude",
        "local",
        "wrong-dir",
        "fenced",
        "code-span",
        "trailing-period",
        "parenthesised",
        "no-space-before",
        "html-comment",
        "indented-code",
        "local-advice",
        "nested-shadow",
        "space-in-path",
        "non-ascii-path",
    ],
)
def test_flags(am, tmp_path, files, untracked, expect):
    findings = am.check(repo(tmp_path, files, untracked))
    assert len(findings) == 1 and expect in findings[0], findings


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


@pytest.mark.parametrize(
    "files",
    [
        {"AGENTS.md": "# a\n", "sub/CLAUDE.md": "nested, and sub/ has no AGENTS.md\n"},
        {"AGENTS.md": "# a\n", "sub/AGENTS.md": "# s\n", "sub/CLAUDE.md": "@AGENTS.md\n"},
        {"AGENTS.md": "# a\n", "CLAUDE.md": "@AGENTS.md\n", "sub/CLAUDE.md": "@../AGENTS.md\n"},
    ],
    ids=["nested-no-sibling", "nested-imports-sibling", "nested-imports-root"],
)
def test_nested_claude_md_is_flagged(am, tmp_path, files):
    # A session started in sub/ loads sub/CLAUDE.md and skips every AGENTS.md.
    findings = am.check(repo(tmp_path, files))
    assert findings == [
        "sub/CLAUDE.md replaces AGENTS.md for a session started in sub/ → "
        "move its content into AGENTS.md and delete it"
    ]


def test_claude_md_above_the_repo_is_flagged(am, tmp_path):
    root = repo(tmp_path, {"AGENTS.md": "# a\n"})
    (tmp_path / "CLAUDE.md").write_text("workspace notes\n")
    assert am.check(root) == [
        f"{tmp_path / 'CLAUDE.md'} sits above the repo and replaces AGENTS.md → move it out"
    ]


def test_user_claude_md_is_not_above_the_repo(am, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "CLAUDE.md").write_text("user memory\n")
    assert am.check(repo(tmp_path, {"AGENTS.md": "# a\n"})) == []
