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

ATTRIBUTION = "block_attribution_trailers"
COMMITS_MD = "block_commits_md"
MAIN_CHECKOUT = "warn_main_checkout_commit"
SECRETS = "block_secrets"
BODIES = "block_long_bodies"
OPTIONS = (ATTRIBUTION, COMMITS_MD, MAIN_CHECKOUT, SECRETS, BODIES)
# The guards that refuse a command; MAIN_CHECKOUT only warns.
BLOCKING = (ATTRIBUTION, COMMITS_MD, SECRETS, BODIES)
FAIL_CLOSED = "phylax: the git guard could not finish its check, so this command was not run."


def option_on(key: str) -> bool:
    return os.environ.get(f"CLAUDE_PLUGIN_OPTION_{key.upper()}") == "true"


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


def failed() -> int:
    """The exit for a check that could not finish: 2 refuses while a blocking guard is on."""
    if any(option_on(k) for k in BLOCKING):
        print(FAIL_CLOSED, file=sys.stderr)
        return 2
    return 1


def main() -> int:
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
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import git_checks

    return git_checks.check(data, raw)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"phylax git guard error: {exc}", file=sys.stderr)
        sys.exit(2 if any(option_on(k) for k in BLOCKING) else 1)
