"""Batch-mode ssh for git that runs with nobody at the terminal to answer a prompt."""

from __future__ import annotations

import subprocess
from pathlib import Path

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
