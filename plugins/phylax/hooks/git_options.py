"""The git guard's options and its fail-closed exit, shared by git_guards.py and git_checks.py.

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
IMPLICIT_REPO = "block_gh_implicit_repo"
OPTIONS = (ATTRIBUTION, COMMITS_MD, MAIN_CHECKOUT, SECRETS, BODIES, IMPLICIT_REPO)
# The guards that refuse a command; MAIN_CHECKOUT only warns.
BLOCKING = (ATTRIBUTION, COMMITS_MD, SECRETS, BODIES, IMPLICIT_REPO)
FAIL_CLOSED = "phylax: the git guard could not finish its check, so this command was not run."


def option_on(key: str) -> bool:
    return os.environ.get(f"CLAUDE_PLUGIN_OPTION_{key.upper()}") == "true"


def failed() -> int:
    """The exit for a check that could not finish: 2 refuses while a blocking guard is on."""
    if any(option_on(k) for k in BLOCKING):
        print(FAIL_CLOSED, file=sys.stderr)
        return 2
    return 1
