"""The Bash guards' options and the git guard's fail-closed exit, shared by git_guards.py,
git_checks.py and command_shapes.py.

Runs on the system python3, so it stays compatible with 3.9 (macOS's).
"""

from __future__ import annotations

import os
import sys
import time

ATTRIBUTION = "block_attribution_trailers"
COMMITS_MD = "block_commits_md"
MAIN_CHECKOUT = "warn_main_checkout_commit"
SECRETS = "block_secrets"
BODIES = "block_long_bodies"
OPTIONS = (ATTRIBUTION, COMMITS_MD, MAIN_CHECKOUT, SECRETS, BODIES)
# The guards that refuse a command; MAIN_CHECKOUT only warns.
BLOCKING = (ATTRIBUTION, COMMITS_MD, SECRETS, BODIES)
# command_shapes.py's options: they refuse a command shape, git or not, and read no repo.
BACKGROUND_LOOPS = "block_background_loops"
PKILL_FULL = "block_pkill_full"
SHAPES = (BACKGROUND_LOOPS, PKILL_FULL)
# A command without one of these cannot hold a shape the shape guards refuse. git_guards.py
# scans the raw hook input for them and command_shapes.py the decoded command; no_python3.sh
# spells the same words for when python3 is missing (a test holds the three equal).
SHAPE_WORDS = ("pkill", "pgrep", "while", "until", "((")
FAIL_CLOSED = "phylax: the git guard could not finish its check, so this command was not run."
# Seconds all of one call's git runs and secret scans may take together: under register.ts's
# 55 s and hooks.json's 75 s, so a slow repo fails the check with this guard's own text
# rather than at the hook's timeout, which names no guard.
BUDGET = 50.0
_START = time.monotonic()


def time_left(cap: float) -> float:
    """CAP, or less when the call's budget has less left; TimeoutError once it is spent."""
    left = BUDGET - (time.monotonic() - _START)
    if left <= 0:
        raise TimeoutError(f"the checks ran past their {BUDGET:g} s budget")
    return min(cap, left)


def off_switch(keys: tuple[str, ...] | list[str]) -> str:
    """How to switch off the guards among KEYS that are on, for a refusal a broken guard
    causes: only those that could have refused the call."""
    names = [k for k in keys if option_on(k)] or ["its option"]
    return (
        f"To switch it off, turn off the phylax option {', '.join(names)} in /config, "
        "or run /phylax:setup."
    )


def option_on(key: str) -> bool:
    return os.environ.get(f"CLAUDE_PLUGIN_OPTION_{key.upper()}") == "true"


def blocking_on() -> bool:
    return any(option_on(k) for k in BLOCKING)


def unchecked(why: str) -> str:
    """The warning a check that could not finish gives while only the warning guard is on."""
    return f"phylax: the {MAIN_CHECKOUT} check could not finish ({why}); the command ran unchecked."


def failed() -> int:
    """The exit for a check that could not finish: 2 refuses while a blocking guard is on. With
    only the warning guard on it is 0 (the caller emits `unchecked` as a warning), since
    hooks.json's onFailure "block" refuses on any exit but 0 and 2."""
    if blocking_on():
        print(FAIL_CLOSED, off_switch(BLOCKING), file=sys.stderr)
        return 2
    return 0
