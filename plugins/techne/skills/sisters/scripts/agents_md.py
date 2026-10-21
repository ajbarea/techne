#!/usr/bin/env python3
"""Check that each sister's AGENTS.md is the file Claude Code loads.

Usage:
    agents_md.py WORKSPACE REPO [REPO ...]

Claude Code reads AGENTS.md only when no CLAUDE.md, .claude/CLAUDE.md or
CLAUDE.local.md sits in the working directory or above it, so those files
replace AGENTS.md unless one of them imports it. Imports are parsed as Claude
Code parses them: `@path` after whitespace or at a line start, cut at `#`,
resolved from the importing file, followed up to four hops, and ignored in code
spans, fenced or indented code, and HTML comments. A nested CLAUDE.md shadows
only the AGENTS.md in its own directory.

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
HOPS = 4
FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
INDENTED = re.compile(r"^( {4}|\t)")
SPAN = re.compile(r"(`+).*?\1")
COMMENT = re.compile(r"<!--.*?-->", re.S)
IMPORT = re.compile(r"(?:^|\s)@((?:[^\s\\]|\\ )+)")


def imports(text: str) -> list[str]:
    """The @path imports Claude Code would expand in an instruction file."""
    found: list[str] = []
    fence = ""
    for line in COMMENT.sub("", text).splitlines():
        mark = FENCE.match(line)
        if mark:
            run = mark.group(1)
            if not fence:
                fence = run
            elif run[0] == fence[0] and len(run) >= len(fence):
                fence = ""
            continue
        if fence or INDENTED.match(line):
            continue
        for token in IMPORT.findall(SPAN.sub("", line)):
            path = token.replace("\\ ", " ").split("#", 1)[0]
            if path:
                found.append(path)
    return found


def resolve(holder: Path, token: str) -> Path:
    path = Path(os.path.expanduser(token))
    return (path if path.is_absolute() else holder.parent / path).resolve()


def reaches(holder: Path, target: Path, hops: int = HOPS, seen: frozenset = frozenset()) -> bool:
    """Whether holder's imports reach target within the hop limit."""
    try:
        text = holder.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    for token in imports(text):
        path = resolve(holder, token)
        if path == target:
            return True
        if hops > 1 and path.is_file() and path not in seen:
            if reaches(path, target, hops - 1, seen | {path}):
                return True
    return False


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
    levels: dict[Path, list[str]] = {}
    for rel in sorted(candidates):
        holder = root / rel
        if not os.path.lexists(holder):
            continue
        level = holder.parent.parent if holder.parent.name == ".claude" else holder.parent
        levels.setdefault(level, []).append(rel)
    for level, rels in levels.items():
        target = level / "AGENTS.md"
        if not target.is_file():
            continue
        plain = []
        for rel in rels:
            if (root / rel).is_symlink():
                findings.append(
                    f"{rel} is a symlink, which a Windows clone checks out as a one-line "
                    "text file → delete it; Claude Code reads AGENTS.md directly"
                )
            else:
                plain.append(rel)
        if any(reaches(root / rel, target.resolve()) for rel in plain):
            continue
        shown = target.relative_to(root).as_posix()
        for rel in plain:
            want = os.path.relpath(target, (root / rel).parent).replace(os.sep, "/")
            fix = (
                f"add @{want} to it"
                if Path(rel).name == "CLAUDE.local.md"
                else f"move its content into {shown}, or add @{want}"
            )
            findings.append(
                f"{rel} does not import {shown}, so Claude Code reads it instead → {fix}"
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
