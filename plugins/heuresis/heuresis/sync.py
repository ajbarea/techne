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
    env = {**os.environ, "GIT_EDITOR": "true", "LC_ALL": "C", "LANG": "C"}
    done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, env=env)
    if check and done.returncode:
        raise SyncError(f"git {' '.join(args)} failed: {done.stderr.strip()}")
    return done


def _commit(root: Path, paths: list[Path], message: str) -> None:
    rel = [str(p.relative_to(root)) for p in paths]
    _git(root, "add", "--", *rel)
    if _git(root, "diff", "--cached", "--quiet", "--", *rel, check=False).returncode:
        _git(root, "commit", "-q", "-m", message, "--only", "--", *rel)


def _resolve_generated_conflicts(
    root: Path, branch: str, done: subprocess.CompletedProcess
) -> None:
    while done.returncode:
        out = _git(root, "diff", "--name-only", "-z", "--diff-filter=U").stdout
        conflicted = [name for name in out.split("\0") if name]
        if not conflicted:
            detail = done.stderr.strip() or done.stdout.strip()
            raise SyncError(f"rebase onto origin/{branch} failed: {detail}")
        if set(conflicted) - set(board.GENERATED):
            raise SyncError(
                f"rebase onto origin/{branch} conflicts in {', '.join(conflicted)}; resolve by hand"
            )
        _git(root, "checkout", "--ours", "--", *conflicted)
        _git(root, "add", "--", *conflicted)
        done = _git(root, "rebase", "--continue", check=False)


def _rebase(root: Path, branch: str) -> None:
    if (
        _git(
            root, "merge-base", "--is-ancestor", f"origin/{branch}", "HEAD", check=False
        ).returncode
        == 0
    ):
        return
    dirty = _git(root, "status", "--porcelain", "--untracked-files=no").stdout.splitlines()
    if dirty:
        paths = ", ".join(line[3:] for line in dirty)
        raise SyncError(f"uncommitted changes in {paths}; commit or stash them, then publish again")
    done = _git(root, "rebase", f"origin/{branch}", check=False)
    try:
        _resolve_generated_conflicts(root, branch, done)
    except SyncError:
        _git(root, "rebase", "--abort", check=False)
        raise


_IN_PROGRESS = (
    (("rebase-merge", "rebase-apply", "MERGE_HEAD"), "a rebase or merge"),
    (("CHERRY_PICK_HEAD", "REVERT_HEAD"), "a cherry-pick or revert"),
)


def _preflight(root: Path) -> str:
    for names, what in _IN_PROGRESS:
        for name in names:
            marker = _git(root, "rev-parse", "--git-path", name).stdout.strip()
            if (root / marker).exists():
                raise SyncError(f"{what} is in progress in {root}; finish it first")
    head = _git(root, "symbolic-ref", "-q", "--short", "HEAD", check=False)
    if head.returncode:
        raise SyncError("HEAD is detached; check out main first")
    branch = head.stdout.strip()
    if branch != "main":
        raise SyncError(f"heuresis publishes from main; current branch is {branch}")
    return branch


def _push(root: Path, branch: str, *args: str) -> bool:
    """True when pushed, False when the remote moved first; any other rejection raises."""
    done = _git(root, "push", "-q", *args, "origin", branch, check=False)
    if done.returncode == 0:
        return True
    err = done.stderr.strip()
    if "non-fast-forward" in err or "fetch first" in err:
        return False
    raise SyncError(f"git push to origin/{branch} failed: {err}")


def publish(root: Path, paths: list[Path], message: str, today: dt.date) -> str:
    branch = _preflight(root)
    generated = board.write(root, today)
    _commit(root, [*paths, *generated], message)
    if _git(root, "remote", "get-url", "origin", check=False).returncode:
        return "local"
    if not _git(root, "ls-remote", "--heads", "origin", branch).stdout.strip():
        if _push(root, branch, "-u"):
            return "pushed"
    for _ in range(PUSH_ATTEMPTS):
        _git(root, "fetch", "-q", "origin", branch)
        _rebase(root, branch)
        _commit(root, board.write(root, today), "chore: regenerate board")
        if _push(root, branch, "-u"):
            return "pushed"
    raise SyncError(f"push to origin/{branch} lost {PUSH_ATTEMPTS} races in a row")
