#!/usr/bin/env python3
"""Validate that every SKILL.md under plugins/*/skills/ has well-formed
frontmatter with the required ``name:`` and ``description:`` keys.

Extracted from the inline heredoc in ``.github/workflows/validate.yml`` so the
check is testable, reusable, and lintable (rather than living as a YAML-quoted
Python blob). Called both from CI and from local audit runs.

Exit codes:
    0 — every SKILL.md found has well-formed frontmatter
    1 — at least one SKILL.md is missing frontmatter or required keys
    2 — no SKILL.md files found at the expected paths (usage error)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_GLOB = "plugins/*/skills/*/SKILL.md"
REQUIRED_KEYS = ("name:", "description:")
_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
# The description value: the rest of its line plus indented continuation lines, past any
# YAML block-scalar indicator (`>`, `|-`, ...), which is syntax rather than text.
_DESCRIPTION_RE = re.compile(
    r"^description:[ \t]*(?:[>|][+-]?[ \t]*\n)?(.*(?:\n[ \t]+.*)*)", re.MULTILINE
)
_NAME_RE = re.compile(r"^name:[ \t]*[\"']?([^\"'\n]*?)[\"']?[ \t]*$", re.MULTILINE)
# Agent Skills spec (agentskills.io/specification): name 1-64 lowercase letters, digits and
# hyphens, matching the skill's folder; description at most 1024 characters.
_NAME_OK = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
NAME_MAX = 64
DESCRIPTION_MAX = 1024


def check_skill(path: Path) -> str | None:
    """Return None if the file passes, otherwise a one-line failure reason."""
    content = path.read_text(encoding="utf-8")
    match = _FRONTMATTER_RE.match(content)
    if not match:
        return f"{path}: missing frontmatter"
    fm = match.group(1)
    for required in REQUIRED_KEYS:
        if required not in fm:
            return f"{path}: missing {required}"
    # claude.ai strips angle brackets from a description when it syncs the plugin.
    desc = _DESCRIPTION_RE.search(fm)
    if desc and re.search(r"[<>]", desc.group(1)):
        return f"{path}: description contains < or >, which claude.ai strips"
    if desc:
        text = " ".join(line.strip() for line in desc.group(1).splitlines()).strip()
        if len(text) > DESCRIPTION_MAX:
            limit = DESCRIPTION_MAX
            return f"{path}: description is {len(text)} characters; the spec allows {limit}"
    name = _NAME_RE.search(fm)
    value = name.group(1) if name else ""
    if len(value) > NAME_MAX or not _NAME_OK.fullmatch(value):
        return f"{path}: name {value!r} must be 1-{NAME_MAX} lowercase letters, digits and hyphens"
    if value != path.parent.name:
        return f"{path}: name {value!r} does not match its folder {path.parent.name!r}"
    return None


def main() -> int:
    skill_paths = sorted(REPO_ROOT.glob(SKILLS_GLOB))
    if not skill_paths:
        print(f"no SKILL.md files matched {SKILLS_GLOB}", file=sys.stderr)
        return 2

    failures: list[str] = []
    for path in skill_paths:
        reason = check_skill(path)
        if reason:
            failures.append(reason)
        else:
            print(f"{path.relative_to(REPO_ROOT)}: ok")

    if failures:
        print("", file=sys.stderr)
        for f in failures:
            print(f, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
