#!/usr/bin/env python3
"""Check that each sister keeps its instructions in AGENTS.md and no CLAUDE-family file.

Usage:
    agents_md.py WORKSPACE REPO [REPO ...]

Claude Code reads AGENTS.md only when no CLAUDE.md, .claude/CLAUDE.md or
CLAUDE.local.md sits in the working directory or above it. A CLAUDE.md that
imports @AGENTS.md does not help: for a session started in a subdirectory the
import is external, so it loads only after an approval dialog, and `claude -p`
skips it. The check therefore flags every such file in the repo, at any depth,
whether tracked, untracked or ignored, and every one in a directory above the
repo. An ignored file is listed unless it sits below the top level of a wholly
ignored folder, which holds vendored code such as node_modules; that folder's own
top level is checked, since a session can start there, unless it is a clone of another
project. .claude/CLAUDE.local.md is not a file
Claude Code reads, so it is not flagged. The user's ~/.claude/CLAUDE.md is not
flagged.

Prints one line per finding, or one passing line per repo. Always exits 0.
"""

from __future__ import annotations

import io
import os
import subprocess
import sys
from pathlib import Path

ROOT_FILES = ("CLAUDE.md", ".claude/CLAUDE.md", "CLAUDE.local.md")
NAMES = {"CLAUDE.md", "CLAUDE.local.md"}
GLOBS = (":(glob)**/CLAUDE.md", ":(glob)**/CLAUDE.local.md")


def above(root: Path) -> list[str]:
    """CLAUDE-family files in the directories above root, which shadow its AGENTS.md."""
    user = Path.home() / ".claude" / "CLAUDE.md"
    found = []
    for parent in root.resolve().parents:
        for rel in ROOT_FILES:
            path = parent / rel
            if (os.path.islink(path) or os.path.isfile(path)) and path != user:
                found.append(f"{path} sits above the repo and replaces AGENTS.md → move it out")
    return found


class GitError(Exception):
    pass


def git_files(root: Path, *args: str) -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", *args],
        capture_output=True,
        check=False,
        env={**os.environ, "GIT_LITERAL_PATHSPECS": "0"},
    )
    if out.returncode != 0:
        lines = os.fsdecode(out.stderr).strip().splitlines()
        raise GitError(lines[0] if lines else f"exit {out.returncode}")
    return [p for p in os.fsdecode(out.stdout).split("\0") if p]


def candidates(root: Path, files: list[str]) -> list[str]:
    """Tracked, untracked and ignored CLAUDE-family files, as repo-relative paths."""
    untracked = git_files(root, "-o", "--exclude-standard", "--", *GLOBS)
    ignored = git_files(root, "-o", "-i", "--exclude-standard", "--directory")
    files = [*files, *untracked, *ignored]
    found = {p for p in files if Path(p.rstrip("/")).name in NAMES}
    found |= {p for p in ROOT_FILES if os.path.lexists(root / p)}
    # A wholly ignored folder's own top level, unless it is a clone of another project.
    tops = [d for d in ignored if d.endswith("/") and not os.path.lexists(root / d / ".git")]
    found |= {d + rel for d in tops for rel in ROOT_FILES}
    found = {p for p in found if not ("/" + p).endswith("/.claude/CLAUDE.local.md")}
    return sorted(p for p in found if os.path.islink(root / p) or os.path.isfile(root / p))


def check(root: Path) -> list[str]:
    if not root.is_dir():
        return [f"not cloned at {root}"]
    try:
        files = git_files(root)
        found = candidates(root, files)
    except GitError as err:
        return [f"git ls-files failed in {root}: {err}"]
    findings = []
    if "AGENTS.md" not in files:
        findings.append("no committed AGENTS.md → add one")
    findings += above(root)
    for rel in found:
        path = root / rel
        level = path.parent.parent if path.parent.name == ".claude" else path.parent
        if path.is_symlink():
            findings.append(
                f"{rel} is a symlink, which a Windows clone checks out as a one-line "
                "text file → delete it; Claude Code reads AGENTS.md directly"
            )
        elif Path(rel).name == "CLAUDE.local.md":
            where = level.relative_to(root).as_posix()
            scope = "" if level == root else f" in a session started in {where}/"
            findings.append(
                f"{rel} stops Claude Code reading AGENTS.md for you{scope} → move it to "
                "~/.claude/CLAUDE.md, or set Project instructions to claude-md-and-agents-md"
            )
        elif level != root:
            where = level.relative_to(root).as_posix()
            findings.append(
                f"{rel} replaces AGENTS.md for a session started in {where}/ → "
                "move its content into AGENTS.md and delete it"
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
    # A path git returns that is not UTF-8 decodes to surrogates, which a strict stdout rejects.
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(errors="backslashreplace")
    workspace = Path(argv[0]).expanduser()
    for name in argv[1:]:
        findings = check(workspace / name)
        for line in findings or ["AGENTS.md, nothing shadows it ✓"]:
            print(f"{name}: {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
