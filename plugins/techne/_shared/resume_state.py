"""A branch's resume state, read from local git only: what a fresh session needs to pick up.

The convention: a repo's root IMPL.md describes the work in flight on the branch it sits on.
A branch whose IMPL.md is unchanged since it left the default branch has not said what it is
for yet. Runs on python3 3.9 (stock macOS), because the SessionStart hook imports it.
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass, field

GIT_TIMEOUT = 5
READ_BUDGET = 20  # seconds for all of read(); the hook's own timeout is 30
IMPL = "IMPL.md"
_deadline: float | None = None


def git(root: str, *args: str) -> str | None:
    """stdout, or None when git fails, times out, is missing or read()'s budget is spent."""
    timeout: float = GIT_TIMEOUT
    if _deadline is not None:
        timeout = min(timeout, _deadline - time.monotonic())
        if timeout <= 0:
            return None
    # status must not take index.lock: another session may be committing in this worktree.
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0"}
    try:
        proc = subprocess.run(
            ["git", "-C", root, *args],
            capture_output=True,
            encoding="utf-8",  # as _read decodes IMPL.md, whatever the locale
            errors="replace",
            env=env,
            timeout=timeout,
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


def impl_matches(root: str, base: str, here: str | None = None) -> bool | None:
    """Whether the worktree's IMPL.md (uncommitted edits included) is unchanged since HEAD
    left base. It compares at their merge-base, so main moving on, or this branch's own
    squash merge, does not decide it. `here` is IMPL.md's text when the caller has read it.

    None when the repo keeps no IMPL.md on either side, so the convention does not apply.
    """
    if here is None:
        here = _read(os.path.join(root, IMPL))
    fork = (git(root, "merge-base", base, "HEAD") or "").strip() if base else ""
    there = git(root, "show", f"{fork or base}:{IMPL}") if base else None
    if here is None and there is None:
        return None
    return here == there


def _read(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def repo_name(root: str) -> str:
    """The repository's folder name, the same from any of its worktrees, bare layouts too."""
    common = (git(root, "rev-parse", "--git-common-dir") or "").strip()
    if not common:
        return os.path.basename(root)
    common = os.path.normpath(os.path.join(root, common))  # relative from the main checkout
    name = os.path.basename(common)
    if name == ".git":
        return os.path.basename(os.path.dirname(common))
    return name[: -len(".git")] if name.endswith(".git") else name


@dataclass
class ResumeState:
    root: str
    repo: str
    branch: str  # "" when detached
    head: str  # short sha
    base: str  # e.g. "origin/main"; "" when the repo has no default branch to compare
    on_base: bool  # the branch is the default branch itself
    impl: str | None
    impl_matches_base: bool | None  # None on the default branch, detached, or without IMPL.md
    commits: list[str] = field(default_factory=list)  # base..HEAD, newest first, capped
    ahead: int | None = 0  # None when git could not count
    dirty: list[str] | None = field(default_factory=list)  # porcelain; None when unknown
    pushed_to: str = ""  # remote branch holding this branch, "" when never pushed
    unpushed: int | None = 0
    behind: int | None = 0  # commits on pushed_to that HEAD lacks, as of the last fetch


def read(cwd: str, max_commits: int = 10) -> ResumeState | None:
    """The resume state of the worktree holding cwd, or None outside a git worktree."""
    global _deadline
    _deadline = time.monotonic() + READ_BUDGET
    try:
        return _read_state(cwd, max_commits)
    finally:
        _deadline = None


def _read_state(cwd: str, max_commits: int) -> ResumeState | None:
    top = git(cwd, "rev-parse", "--show-toplevel")
    if not top or not top.strip():
        return None
    root = top.strip()
    branch = (git(root, "branch", "--show-current") or "").strip()
    head = (git(root, "rev-parse", "--short", "HEAD") or "").strip()
    base = base_ref(root)
    short = base[len("origin/") :] if base.startswith("origin/") else base
    on_base = bool(branch) and branch == short
    impl = _read(os.path.join(root, IMPL))
    state = ResumeState(
        root=root,
        repo=repo_name(root),
        branch=branch,
        head=head,
        base=base,
        on_base=on_base,
        impl=impl,
        impl_matches_base=None if on_base or not branch else impl_matches(root, base, impl),
    )
    if base and not on_base:
        log = git(root, "log", f"-n{max_commits}", "--format=%h %s", f"{base}..HEAD")
        state.commits = log.splitlines() if log else []
        state.ahead = _count(git(root, "rev-list", "--count", f"{base}..HEAD"))
    status = git(root, "status", "--porcelain", "--untracked-files=normal")
    state.dirty = None if status is None else [ln for ln in status.splitlines() if ln.strip()]
    if branch:
        remote = (git(root, "config", "--get", f"branch.{branch}.remote") or "origin").strip()
        mirror = f"{remote}/{branch}"
        if git(root, "rev-parse", "--verify", "--quiet", mirror + "^{commit}") is not None:
            state.pushed_to = mirror
            counts = git(root, "rev-list", "--left-right", "--count", f"{mirror}...HEAD")
            parts = (counts or "").split()
            if len(parts) == 2 and all(p.isdigit() for p in parts):
                state.behind, state.unpushed = int(parts[0]), int(parts[1])
            else:
                state.behind = state.unpushed = None
    return state


def _count(out: str | None) -> int | None:
    try:
        return int((out or "").strip())
    except ValueError:
        return None
