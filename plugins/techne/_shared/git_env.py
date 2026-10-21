"""git run by a script: batch-mode ssh with nobody at the terminal, and no variable that would
point it at another repository."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

# What `git rev-parse --local-env-vars` lists (git 2.43), minus GIT_CONFIG, GIT_CONFIG_PARAMETERS
# and GIT_CONFIG_COUNT: those carry config a container or CI job injects on purpose
# (safe.directory, a credential helper), not a different repository. A hook or wrapper that
# exports any of these points `git -C <dir>` at another repository than <dir>. Used only when
# the installed git cannot be asked; local_env() prefers git's own list.
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


_CONFIG_ENV = frozenset({"GIT_CONFIG", "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT"})
_local_env_cache: frozenset[str] | None = None


def local_env() -> frozenset[str]:
    """The variables the installed git treats as repository-local (`git rev-parse
    --local-env-vars`), minus the config variables; LOCAL_ENV when git cannot be asked.
    Asked once per process."""
    global _local_env_cache
    if _local_env_cache is None:
        reported: set[str] = set()
        try:
            done = subprocess.run(
                ["git", "rev-parse", "--local-env-vars"],
                capture_output=True,
                text=True,
                timeout=CONFIG_TIMEOUT,
            )
            if done.returncode == 0:
                reported = {n for n in done.stdout.split() if n.startswith("GIT_")}
        except (subprocess.TimeoutExpired, OSError):
            pass
        _local_env_cache = frozenset(reported - _CONFIG_ENV) if reported else frozenset(LOCAL_ENV)
    return _local_env_cache


def without_repo_overrides(env: Mapping[str, str] | None = None) -> dict[str, str]:
    """env (os.environ by default) without the variables that redirect git to another repo."""
    drop = local_env()
    return {k: v for k, v in (os.environ if env is None else env).items() if k not in drop}


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


# A remote through an ssh host alias: host, owner, name. scp form (git@github-work:o/r) has no
# port, so an all-digit owner is an owner; URL form (ssh://git@github-work:22/o/r) needs the
# scheme, so a relative path (../o/r) is neither.
_ALIAS_SCP = re.compile(r"^(?:[^@/\s]+@)?([^:/\s]+):([^/\s]+)/([^/\s]+?)(?:\.git)?/?$")
_ALIAS_URL = re.compile(
    r"^(?:git\+ssh|ssh\+git|ssh)://(?:[^@/\s]+@)?([^:/\s]+)(?::\d+)?/"
    r"([^/\s]+)/([^/\s]+?)(?:\.git)?/?$",
    re.IGNORECASE,
)


def github_slug(url: str) -> tuple[str, str] | None:
    """(owner, name) of a GitHub remote, or None. An ssh host alias (git@github-work:o/r or
    ssh://git@github-work/o/r, as several-account setups use) counts when `ssh -G` resolves it
    to github.com."""
    found = GITHUB_REMOTE.search(url)
    if found:
        return found.group(1), found.group(2)
    alias = _ALIAS_URL.match(url) or _ALIAS_SCP.match(url)
    if not alias or alias.group(1).startswith("-"):  # never hand ssh an option from a remote URL
        return None
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:  # loaded by file path: doctor_lib sits beside this file
        sys.path.append(here)
    import doctor_lib

    # Its own session, stdin closed, the process group killed on timeout: a slow `Match exec`
    # helper in ~/.ssh/config cannot outlive the call.
    code, out = doctor_lib.run(
        ("ssh", "-G", "--", alias.group(1)), timeout=CONFIG_TIMEOUT, merge_stderr=False
    )
    if code != 0:
        return None
    host = next((ln.split()[1] for ln in out.splitlines() if ln.startswith("hostname ")), "")
    if host.lower() in ("github.com", "ssh.github.com"):
        return alias.group(2), alias.group(3)
    return None
