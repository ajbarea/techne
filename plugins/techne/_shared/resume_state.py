"""A branch's resume state, read from local git only: what a fresh session needs to pick up.

The convention: a repo's root IMPL.md describes the work in flight on the branch it sits on.
A branch whose IMPL.md still matches the default branch has not said what it is for yet.
Runs on python3 3.9 (stock macOS), because the SessionStart hook imports it.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field

GIT_TIMEOUT = 5
IMPL = "IMPL.md"
# status must not take index.lock: another session may be committing in this worktree.
_ENV = {**os.environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0"}


def git(root: str, *args: str) -> str | None:
    """stdout, or None when git fails, times out or is missing."""
    try:
        proc = subprocess.run(
            ["git", "-C", root, *args],
            capture_output=True,
            text=True,
            env=_ENV,
            timeout=GIT_TIMEOUT,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    return proc.stdout if proc.returncode == 0 else None


def base_ref(root: str) -> str:
    """The default branch to compare against: origin's HEAD, else origin/main or master, else
    a local main or master; "" when none exists."""
    head = git(root, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    if head and head.strip():
        return head.strip()
    for ref in ("origin/main", "origin/master", "main", "master"):
        if git(root, "rev-parse", "--verify", "--quiet", ref + "^{commit}") is not None:
            return ref
    return ""


def impl_matches(root: str, base: str) -> bool | None:
    """Whether the worktree's IMPL.md (uncommitted edits included) equals base's.

    None when the repo keeps no IMPL.md on either side, so the convention does not apply.
    """
    path = os.path.join(root, IMPL)
    here = _read(path)
    there = git(root, "show", f"{base}:{IMPL}") if base else None
    if here is None and there is None:
        return None
    return here == there


def _read(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


@dataclass
class ResumeState:
    root: str
    repo: str  # the repository's folder name, the same from any of its worktrees
    branch: str  # "" when detached
    head: str  # short sha
    base: str  # e.g. "origin/main"; "" when the repo has no default branch to compare
    on_base: bool  # the branch is the default branch itself
    impl: str | None
    impl_matches_base: bool | None
    commits: list[str] = field(default_factory=list)  # base..HEAD, newest first, capped
    ahead: int = 0
    dirty: list[str] = field(default_factory=list)  # porcelain lines
    pushed_to: str = ""  # remote branch holding this branch, "" when never pushed
    unpushed: int = 0


def read(cwd: str, max_commits: int = 10) -> ResumeState | None:
    """The resume state of the worktree holding cwd, or None outside a git worktree."""
    top = git(cwd, "rev-parse", "--show-toplevel")
    if not top or not top.strip():
        return None
    root = top.strip()
    branch = (git(root, "branch", "--show-current") or "").strip()
    head = (git(root, "rev-parse", "--short", "HEAD") or "").strip()
    base = base_ref(root)
    on_base = bool(branch) and branch in (base, base[len("origin/") :])
    common = (git(root, "rev-parse", "--path-format=absolute", "--git-common-dir") or "").strip()
    repo = os.path.basename(os.path.dirname(common)) if common.endswith(".git") else ""
    state = ResumeState(
        root=root,
        repo=repo or os.path.basename(root),
        branch=branch,
        head=head,
        base=base,
        on_base=on_base,
        impl=_read(os.path.join(root, IMPL)),
        impl_matches_base=None if on_base else impl_matches(root, base),
    )
    if base and not on_base:
        log = git(root, "log", f"-n{max_commits}", "--format=%h %s", f"{base}..HEAD")
        state.commits = log.splitlines() if log else []
        state.ahead = _count(git(root, "rev-list", "--count", f"{base}..HEAD"))
    status = git(root, "status", "--porcelain", "--untracked-files=normal")
    state.dirty = [ln for ln in (status or "").splitlines() if ln.strip()]
    if branch:
        remote = (git(root, "config", "--get", f"branch.{branch}.remote") or "origin").strip()
        mirror = f"{remote}/{branch}"
        if git(root, "rev-parse", "--verify", "--quiet", mirror + "^{commit}") is not None:
            state.pushed_to = mirror
            state.unpushed = _count(git(root, "rev-list", "--count", f"{mirror}..HEAD"))
    return state


def _count(out: str | None) -> int:
    try:
        return int((out or "0").strip())
    except ValueError:
        return 0
