"""Commit idea changes and share them. BOARD.md and LOG.md are regenerated, never merged."""

from __future__ import annotations

import datetime as dt
import os
import subprocess
from pathlib import Path

from heuresis import board

# A push that loses a race refetches and rebases; three races in a row is a real problem.
PUSH_ATTEMPTS = 3


class SyncError(Exception):
    """Publishing stopped and needs AJ: the local commit is kept, the rebase is aborted."""


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    env = {**os.environ, "GIT_EDITOR": "true"}
    done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, env=env)
    if check and done.returncode:
        raise SyncError(f"git {' '.join(args)} failed: {done.stderr.strip()}")
    return done


def _commit(root: Path, paths: list[Path], message: str) -> None:
    rel = [str(p.relative_to(root)) for p in paths]
    _git(root, "add", "--", *rel)
    if _git(root, "diff", "--cached", "--quiet", check=False).returncode:
        _git(root, "commit", "-q", "-m", message)


def _rebase(root: Path, branch: str) -> None:
    done = _git(root, "rebase", f"origin/{branch}", check=False)
    while done.returncode:
        conflicted = _git(root, "diff", "--name-only", "--diff-filter=U").stdout.split()
        if not conflicted or set(conflicted) - set(board.GENERATED):
            _git(root, "rebase", "--abort", check=False)
            names = ", ".join(conflicted) or "unknown files"
            raise SyncError(f"rebase onto origin/{branch} conflicts in {names}; resolve by hand")
        _git(root, "checkout", "--ours", "--", *conflicted)
        _git(root, "add", "--", *conflicted)
        done = _git(root, "rebase", "--continue", check=False)


def publish(root: Path, paths: list[Path], message: str, today: dt.date) -> str:
    generated = board.write(root, today)
    _commit(root, [*paths, *generated], message)
    if not _git(root, "remote", check=False).stdout.strip():
        return "local"
    branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if not _git(root, "ls-remote", "--heads", "origin", branch).stdout.strip():
        _git(root, "push", "-q", "-u", "origin", branch)
        return "pushed"
    for _ in range(PUSH_ATTEMPTS):
        _git(root, "fetch", "-q", "origin", branch)
        _rebase(root, branch)
        _commit(root, board.write(root, today), "chore: regenerate board")
        if _git(root, "push", "-q", "origin", branch, check=False).returncode == 0:
            return "pushed"
    raise SyncError(f"push to origin/{branch} lost {PUSH_ATTEMPTS} races in a row")
