#!/usr/bin/env python3
"""Check that each sister keeps its instructions in AGENTS.md and no CLAUDE-family file.

Usage:
    agents_md.py WORKSPACE REPO [REPO ...]

Claude Code reads AGENTS.md only when no CLAUDE.md, .claude/CLAUDE.md or
CLAUDE.local.md sits in the working directory or above it. A CLAUDE.md that
imports @AGENTS.md does not help: for a session started in a subdirectory the
import is external, so it loads only after an approval dialog, and `claude -p`
skips it. The check therefore flags every such file in the repo, at any depth,
whether tracked, untracked or ignored (an ignored CLAUDE.md is not listed, as it
is vendored, but an ignored CLAUDE.local.md is), and every one in a directory
above the repo. The user's ~/.claude/CLAUDE.md is not flagged.

Prints one line per finding, or one passing line per repo. Always exits 0.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT_FILES = ("CLAUDE.md", ".claude/CLAUDE.md", "CLAUDE.local.md")
NAMES = {"CLAUDE.md", "CLAUDE.local.md"}


def above(root: Path) -> list[str]:
    """CLAUDE-family files in the directories above root, which shadow its AGENTS.md."""
    user = Path.home() / ".claude" / "CLAUDE.md"
    found = []
    for parent in root.resolve().parents:
        for rel in ROOT_FILES:
            path = parent / rel
            if os.path.lexists(path) and path != user:
                found.append(f"{path} sits above the repo and replaces AGENTS.md → move it out")
    return found


def git_files(root: Path, *args: str) -> list[str] | None:
    out = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", *args], capture_output=True, check=False
    )
    if out.returncode != 0:
        return None
    return [p for p in out.stdout.decode("utf-8", "replace").split("\0") if p]


def candidates(root: Path, files: list[str]) -> list[str]:
    """Tracked, untracked and ignored CLAUDE-family files, as repo-relative paths."""
    found = {p for p in files if Path(p).name in NAMES}
    for args in (
        ("-o", "--exclude-standard", "--", ":(glob)**/CLAUDE.md", ":(glob)**/CLAUDE.local.md"),
        ("-o", "-i", "--exclude-standard", "--", ":(glob)**/CLAUDE.local.md"),
    ):
        found |= set(git_files(root, *args) or [])
    found |= {p for p in ROOT_FILES if os.path.lexists(root / p)}
    return sorted(p for p in found if os.path.islink(root / p) or os.path.isfile(root / p))


def check(root: Path) -> list[str]:
    if not root.is_dir():
        return [f"not cloned at {root}"]
    files = git_files(root)
    if files is None:
        return [f"{root} is not a git repository"]
    findings = []
    if "AGENTS.md" not in files:
        findings.append("no committed AGENTS.md → add one")
    findings += above(root)
    for rel in candidates(root, files):
        path = root / rel
        level = path.parent.parent if path.parent.name == ".claude" else path.parent
        if path.is_symlink():
            findings.append(
                f"{rel} is a symlink, which a Windows clone checks out as a one-line "
                "text file → delete it; Claude Code reads AGENTS.md directly"
            )
        elif level != root:
            where = level.relative_to(root).as_posix()
            findings.append(
                f"{rel} replaces AGENTS.md for a session started in {where}/ → "
                "move its content into AGENTS.md and delete it"
            )
        elif Path(rel).name == "CLAUDE.local.md":
            findings.append(
                f"{rel} stops Claude Code reading AGENTS.md for you → move it to "
                "~/.claude/CLAUDE.md, or set Project instructions to claude-md-and-agents-md"
            )
        else:
            findings.append(
                f"{rel} stops Claude Code reading AGENTS.md directly, and an @AGENTS.md "
                "import in it is external for a session started in a subdirectory → "
                "move its content into AGENTS.md and delete it"
            )
    return findings


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__.strip())
        return 0
    workspace = Path(argv[0]).expanduser()
    for name in argv[1:]:
        findings = check(workspace / name)
        for line in findings or ["AGENTS.md, nothing shadows it ✓"]:
            print(f"{name}: {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
