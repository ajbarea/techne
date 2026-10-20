"""git run by a script: batch-mode ssh with nobody at the terminal, and no variable that would
point it at another repository."""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Mapping
from pathlib import Path

# What `git rev-parse --local-env-vars` lists, minus GIT_CONFIG, GIT_CONFIG_PARAMETERS and
# GIT_CONFIG_COUNT: those carry config a container or CI job injects on purpose (safe.directory,
# a credential helper), not a different repository. A hook or wrapper that exports any of these
# points `git -C <dir>` at another repository than <dir>.
LOCAL_ENV = (
    "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_OBJECT_DIRECTORY", "GIT_DIR", "GIT_WORK_TREE",
    "GIT_IMPLICIT_WORK_TREE", "GIT_GRAFT_FILE", "GIT_INDEX_FILE", "GIT_NO_REPLACE_OBJECTS",
    "GIT_REPLACE_REF_BASE", "GIT_PREFIX", "GIT_SHALLOW_FILE", "GIT_COMMON_DIR",
)  # fmt: skip
# A remote on github.com (or its www. and ssh. hosts): scp form (git@github.com:o/r) or URL
# form, with or without a scheme, user or port. Anchored at the start, so a mirror path that
# merely contains "github.com/o/r" on another host does not count.
GITHUB_REMOTE = re.compile(
    r"^(?:[\w+.-]+://)?(?:[^@/\s]+@)?(?:www\.|ssh\.)?github\.com(?::\d+)?[:/]"
    r"([^/\s]+)/([^/\s]+?)(?:\.git)?/?$",
    re.IGNORECASE,
)


def without_repo_overrides(env: Mapping[str, str] | None = None) -> dict[str, str]:
    """env (os.environ by default) without the variables that redirect git to another repo."""
    return {k: v for k, v in (os.environ if env is None else env).items() if k not in LOCAL_ENV}


# Without a prompt or a key passphrase to answer, ssh fails at once instead of waiting.
BATCH_SSH = "ssh -o BatchMode=yes -o ConnectTimeout=5"
CONFIG_TIMEOUT = 10


def batch_ssh(env: dict[str, str], repo: str | Path) -> dict[str, str]:
    """env plus GIT_SSH_COMMAND=BATCH_SSH, unless the user chose how git runs ssh.

    The choice is GIT_SSH_COMMAND, GIT_SSH or the repo's core.sshCommand; git applies it, so
    env comes back unchanged and the user's key, proxy or wrapper keeps working.
    """
    if {"GIT_SSH_COMMAND", "GIT_SSH"} & env.keys():
        return env
    try:
        chosen = subprocess.run(
            ["git", "-C", str(repo), "config", "--get", "core.sshCommand"],
            capture_output=True,
            text=True,
            env=env,
            timeout=CONFIG_TIMEOUT,
        ).stdout
    except (subprocess.TimeoutExpired, OSError):
        chosen = ""  # the git call that follows meets the same problem and reports it
    if chosen.strip():
        return env
    return {**env, "GIT_SSH_COMMAND": BATCH_SSH}
