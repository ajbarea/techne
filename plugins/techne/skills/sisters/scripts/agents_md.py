#!/usr/bin/env python3
"""Check that each sister's AGENTS.md is the file Claude Code loads.

Usage:
    agents_md.py WORKSPACE REPO [REPO ...]

Claude Code reads AGENTS.md only when no CLAUDE.md, .claude/CLAUDE.md or
CLAUDE.local.md sits in the working directory or above it, so any of those
replaces AGENTS.md unless it imports it. An import resolves relative to the
file that holds it, and is not parsed inside a code span or a fenced block.
A nested CLAUDE.md shadows only the AGENTS.md in its own directory.

Prints one line per finding, or one passing line per repo. Always exits 0.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT_FILES = ("CLAUDE.md", ".claude/CLAUDE.md", "CLAUDE.local.md")
NAMES = {"CLAUDE.md", "CLAUDE.local.md"}
FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
SPAN = re.compile(r"(`+).*?\1")
IMPORT = re.compile(r"(?<![\w@])@((?:\\ |[^\s`])+)")


def imports(text: str) -> list[str]:
    """The @path imports in a CLAUDE.md, outside code spans and fences."""
    found: list[str] = []
    fence = ""
    for line in text.splitlines():
        mark = FENCE.match(line)
        if mark:
            run = mark.group(1)
            if not fence:
                fence = run
            elif run[0] == fence[0] and len(run) >= len(fence):
                fence = ""
            continue
        if fence:
            continue
        for token in IMPORT.findall(SPAN.sub("", line)):
            found.append(token.replace("\\ ", " ").rstrip(".,;:!?)"))
    return found


def resolve(holder: Path, token: str) -> Path:
    path = Path(os.path.expanduser(token))
    return (path if path.is_absolute() else holder.parent / path).resolve()


def tracked(root: Path) -> list[str] | None:
    out = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"], capture_output=True, check=False
    )
    if out.returncode != 0:
        return None
    return [p for p in out.stdout.decode("utf-8", "replace").split("\0") if p]


def check(root: Path) -> list[str]:
    if not root.is_dir():
        return [f"not cloned at {root}"]
    files = tracked(root)
    if files is None:
        return [f"{root} is not a git repository"]
    findings = []
    if "AGENTS.md" not in files:
        findings.append("no committed AGENTS.md → add one")
    candidates = {p for p in files if Path(p).name in NAMES}
    candidates |= {p for p in ROOT_FILES if os.path.lexists(root / p)}
    for rel in sorted(candidates):
        holder = root / rel
        level = holder.parent.parent if holder.parent.name == ".claude" else holder.parent
        target = level / "AGENTS.md"
        if not os.path.lexists(holder) or not target.is_file():
            continue
        if holder.is_symlink():
            findings.append(
                f"{rel} is a symlink, which a Windows clone checks out as a one-line "
                "text file → delete it; Claude Code reads AGENTS.md directly"
            )
            continue
        text = holder.read_text(encoding="utf-8", errors="replace")
        if any(resolve(holder, t) == target.resolve() for t in imports(text)):
            continue
        shown = target.relative_to(root).as_posix()
        want = os.path.relpath(target, holder.parent).replace(os.sep, "/")
        findings.append(
            f"{rel} does not import {shown}, so Claude Code reads it instead → "
            f"move its content into {shown}, or add @{want}"
        )
    return findings


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__.strip().splitlines()[2].strip())
        return 0
    workspace = Path(argv[0]).expanduser()
    for name in argv[1:]:
        findings = check(workspace / name)
        for line in findings or ["AGENTS.md, nothing shadows it ✓"]:
            print(f"{name}: {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
