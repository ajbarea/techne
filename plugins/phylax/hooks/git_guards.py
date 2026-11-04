#!/usr/bin/env python3
"""Guards on the Bash tool for git commit, git add, git push and gh pr/issue/api writes.

register.ts runs this from its tool.call hook on each main-thread Bash command
that names git or gh, passing the PreToolUse JSON on stdin and each userConfig
option as CLAUDE_PLUGIN_OPTION_<KEY>, and reads the decision from stdout. The
hooks.json PreToolUse hook runs it too, for subagents' commands and for every
command when the module did not load; mod_checks() stands it down for a command
the module already checked. A repo turns an enabled guard off for itself with
`git config phylax.<optionInCamelCase> false`.

This file only decides whether a command needs checking; git_checks.py holds the
checks. The fallback runs on every Bash call, so a command that cannot name git or
gh exits before git_checks.py loads. Python recompiles the script it runs on every
start but caches the bytecode of a module it imports, so the checks live in an
imported module.

A crash in one subcommand's check, or a git call that cannot run or times out,
still checks the rest and emits the denies already found; with none found, the
check fails closed while a blocking guard is on (exit 2, which both callers
treat as a refusal).

Runs on the system python3, so it stays compatible with 3.9 (macOS's).
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def mod_checks(data: dict) -> bool:
    """Whether register.ts already checked this call: the hooks.json fallback then stands down.

    The mod names the one call its check passed in PHYLAX_GUARD_CHECKED while that call runs,
    and clears it after. Any other call (a subagent's, which the mod leaves here because only
    this hook gets its cwd, or any call when the module did not load) is checked here.
    """
    checked = os.environ.get("PHYLAX_GUARD_CHECKED")
    return bool(checked) and checked == data.get("tool_use_id")


def cannot_name_git(payload: str) -> bool:
    """Whether the raw hook input cannot hold a command naming git or gh.

    JSON writes a letter as itself or as a \\u escape, so input with neither word and no
    \\u escape has no such command, whatever else it holds.
    """
    return "git" not in payload and "gh" not in payload and "\\u" not in payload


def main() -> int:
    from git_options import OPTIONS, option_on

    payload = sys.stdin.read()
    if not any(option_on(k) for k in OPTIONS) or cannot_name_git(payload):
        return 0
    import json
    import re

    data = json.loads(payload or "{}")
    if mod_checks(data):
        return 0
    raw = (data.get("tool_input") or {}).get("command") or ""
    if not re.search(r"\b(git|gh)\b", raw):
        return 0
    import git_checks

    return git_checks.check(data, raw)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"phylax git guard error: {exc}", file=sys.stderr)
        try:
            from git_options import BLOCKING, option_on

            blocking = any(option_on(k) for k in BLOCKING)
        except Exception:
            blocking = True  # which guards are on cannot be read, so the check fails closed
        sys.exit(2 if blocking else 1)
