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


def git(root: str, *args: str, deadline: float | None = None) -> str | None:
    """stdout, or None when git fails, times out, is missing or `deadline` (a
    time.monotonic() value) has passed."""
    timeout: float = GIT_TIMEOUT
    if deadline is not None:
        timeout = min(timeout, deadline - time.monotonic())
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


def _exists(root: str, ref: str, deadline: float | None) -> bool:
    return (
        git(root, "rev-parse", "--verify", "--quiet", ref + "^{commit}", deadline=deadline)
        is not None
    )


def base_ref(root: str, deadline: float | None = None) -> str:
    """The default branch to compare against: origin's HEAD when it still names a branch
    (a clone never updates it), else origin/main or master, else a local main or master;
    "" when none exists."""
    head = (
        git(
            root,
            "symbolic-ref",
            "--quiet",
            "--short",
            "refs/remotes/origin/HEAD",
            deadline=deadline,
        )
        or ""
    ).strip()
    for ref in ([head] if head else []) + ["origin/main", "origin/master", "main", "master"]:
        if _exists(root, ref, deadline):
            return ref
    return ""


def impl_matches(
    root: str, base: str, here: str | None = None, deadline: float | None = None
) -> bool | None:
    """Whether the worktree's IMPL.md (uncommitted edits included) is unchanged since HEAD
    left base. It compares at their merge-base, so main moving on, or this branch's own
    squash merge, does not decide it. `here` is IMPL.md's text when the caller has read it.

    None when the repo keeps no IMPL.md on either side, so the convention does not apply,
    or when git cannot find the merge-base (a timeout, a shallow clone), so nobody knows.
    """
    if here is None:
        here = _read(os.path.join(root, IMPL))
    if not base:
        return None if here is None else False
    fork = (git(root, "merge-base", base, "HEAD", deadline=deadline) or "").strip()
    if not fork:
        return None
    there = git(root, "show", f"{fork}:{IMPL}", deadline=deadline)
    if here is None and there is None:
        return None
    return here == there


def _read(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def repo_name(root: str, deadline: float | None = None) -> str:
    """The repository's folder name, the same from any of its worktrees, bare layouts too."""
    common = (git(root, "rev-parse", "--git-common-dir", deadline=deadline) or "").strip()
    if not common:
        return os.path.basename(root)
    common = os.path.normpath(os.path.join(root, common))  # relative from the main checkout
    name = os.path.basename(common)
    if name == ".git":
        return os.path.basename(os.path.dirname(common))
    return name[: -len(".git")] if name.endswith(".git") else name


def pushed_ref(root: str, branch: str, base: str, deadline: float | None = None) -> str:
    """The remote branch holding this branch: its upstream when that is not the base (a
    `worktree-x` pushed as `feat/x`), else <remote>/<branch>; "" when there is none."""
    upstream = git(
        root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}", deadline=deadline
    )
    upstream = (upstream or "").strip()
    if upstream and upstream != base and _exists(root, upstream, deadline):
        return upstream
    remote = (
        git(root, "config", "--get", f"branch.{branch}.remote", deadline=deadline) or "origin"
    ).strip()
    mirror = f"{remote}/{branch}"
    return mirror if mirror != base and _exists(root, mirror, deadline) else ""


@dataclass
class ResumeState:
    root: str
    repo: str
    branch: str  # "" when detached
    head: str  # short sha
    base: str  # e.g. "origin/main"; "" when the repo has no default branch to compare
    on_base: bool  # the branch is the default branch itself
    impl: str | None
    impl_matches_base: bool | None  # None on the default branch, detached, unknown, no IMPL.md
    commits: list[str] = field(default_factory=list)  # base..HEAD, newest first, capped
    ahead: int | None = 0  # None when git could not count
    dirty: list[str] | None = field(default_factory=list)  # porcelain; None when unknown
    pushed_to: str = ""  # remote branch holding this branch, "" when never pushed
    unpushed: int | None = 0
    behind: int | None = 0  # commits on pushed_to that HEAD lacks, as of the last fetch


def read(cwd: str, max_commits: int = 10) -> ResumeState | None:
    """The resume state of the worktree holding cwd, or None outside a git worktree. Every
    git call shares one READ_BUDGET; a call past it reads as unknown."""
    d = time.monotonic() + READ_BUDGET
    top = (git(cwd, "rev-parse", "--show-toplevel", deadline=d) or "").strip()
    if not top:
        return None
    branch = (git(top, "branch", "--show-current", deadline=d) or "").strip()
    head = (git(top, "rev-parse", "--short", "HEAD", deadline=d) or "").strip()
    base = base_ref(top, d)
    short = base[len("origin/") :] if base.startswith("origin/") else base
    on_base = bool(branch) and branch == short
    impl = _read(os.path.join(top, IMPL))
    state = ResumeState(
        root=top,
        repo=repo_name(top, d),
        branch=branch,
        head=head,
        base=base,
        on_base=on_base,
        impl=impl,
        impl_matches_base=None if on_base or not branch else impl_matches(top, base, impl, d),
    )
    if base and not on_base:
        log = git(top, "log", f"-n{max_commits}", "--format=%h %s", f"{base}..HEAD", deadline=d)
        state.commits = log.splitlines() if log else []
        state.ahead = _count(git(top, "rev-list", "--count", f"{base}..HEAD", deadline=d))
    status = git(top, "status", "--porcelain", "--untracked-files=normal", deadline=d)
    state.dirty = None if status is None else [ln for ln in status.splitlines() if ln.strip()]
    if branch and not on_base:
        state.pushed_to = pushed_ref(top, branch, base, d)
    elif on_base and _exists(top, base, d) and base != branch:
        state.pushed_to = base
    if state.pushed_to:
        counts = git(
            top, "rev-list", "--left-right", "--count", f"{state.pushed_to}...HEAD", deadline=d
        )
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
