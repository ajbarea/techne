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
IMPLICIT_REPO = "block_gh_implicit_repo"
OPTIONS = (ATTRIBUTION, COMMITS_MD, MAIN_CHECKOUT, SECRETS, BODIES, IMPLICIT_REPO)
# The guards that refuse a command; MAIN_CHECKOUT only warns.
BLOCKING = (ATTRIBUTION, COMMITS_MD, SECRETS, BODIES, IMPLICIT_REPO)
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


STALE_PENDING_SEC = 3600


def state_home() -> str:
    """XDG_STATE_HOME, or ~/.local/state when it is unset or relative (the spec says a
    relative value is to be ignored; the hook's cwd is the user's repo)."""
    state = os.environ.get("XDG_STATE_HOME", "")
    return state if state.startswith("/") else os.environ.get("HOME", "") + "/.local/state"


def pending_denials() -> str:
    """denial_log.pending_dir(), here so git_guards checks it without another import or more
    source of its own to compile on every call (a test holds the two equal)."""
    return state_home() + "/phylax/pending-denials"


def _raw_value(payload: str, key: str) -> str | None:
    """The plain string value of the first "KEY": "..." in raw hook input, without json:
    None when absent, "\\" when the value has an escape (the caller then parses fully)."""
    i = payload.find(f'"{key}"')
    if i < 0:
        return None
    rest = payload[i + len(key) + 2 :].lstrip()
    if not rest.startswith(":"):
        return "\\"
    rest = rest[1:].lstrip()
    if not rest.startswith('"'):
        return "\\"
    end = rest.find('"', 1)
    value = rest[1:end] if end > 0 else "\\"
    return "\\" if "\\" in value else value


def safe_id(actor: str) -> str:
    """ACTOR as a file name: ASCII letters, digits, `-` and `_`, at most 64 characters."""
    keep = "".join(c if c.isascii() and (c.isalnum() or c in "-_") else "_" for c in actor)
    return keep[:64] or "default"


def pending_record(payload: str) -> bool:
    """Whether this call may have a denial record waiting: its own session's (and agent's)
    record exists, its ids cannot be read cheaply, or the folder is stale and wants a sweep.
    False (one access()) while nothing waits; one more access() for another session's."""
    folder = pending_denials()
    if not os.access(folder, os.F_OK):
        return False
    session = _raw_value(payload, "session_id")
    agent = _raw_value(payload, "agent_id")
    if not session or "\\" in session or (agent is not None and "\\" in agent):
        return True
    actor = session + ("." + agent if agent else "")
    if os.access(f"{folder}/{safe_id(actor)}.json", os.F_OK):
        return True
    try:
        return time.time() - os.stat(folder).st_mtime > STALE_PENDING_SEC
    except OSError:
        return False
