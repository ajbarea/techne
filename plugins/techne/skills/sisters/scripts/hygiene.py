#!/usr/bin/env python3
"""Branch, worktree and stash hygiene across the sister repos, with a guarded clean mode.

Usage:
    hygiene.py [--repo NAME ...] [--json] [--plan-out FILE]
    hygiene.py --apply FILE
    hygiene.py --auto [--path DIR ...] [--min-interval SECONDS] [--hook]
    hygiene.py --env

Report mode (the default) reads every active sister in ~/.claude/techne.toml, or
the --repo names, and sorts what it finds into three groups per repo:

  remove   provably finished: a PR merged into the default branch whose head is
           the branch tip (or contains it), or a local branch with no PR already
           inside the default branch; a worktree on such a branch that is clean,
           idle and unused; a prunable worktree
  review   anything a person should decide: unmerged commits, commits added after
           the PR merged, a PR merged elsewhere or closed unmerged, a dirty,
           locked, busy, recently active or ignored-work-holding worktree, a
           remote branch with no PR or someone else's. A dirty, idle worktree whose
           IMPL.md is unchanged since its branch left the default branch is marked
           not resumable.
  info     branches of open PRs, stashes, uncommitted changes in the main checkout

Squash merges leave a branch's own commits outside main forever, so "ahead of
main" says nothing about whether it shipped. The PR's state does: a branch is
finished when its PR merged and the tip is the head that merged.

--plan-out writes the remove group as JSON. --apply takes that file, collects
every repo in it afresh, and runs only the actions that are still in the remove
group with the same tip. Every deletion is compare-and-delete on that tip, so a
branch that moved after the plan was shown is left alone.

--auto skips the plan: it surveys the roster plus each --path repo, removes the
remove group straight away (execute() checks again at the last moment), and prints
what a merge left behind that will not clear on its own. It prints nothing when
there is nothing to say, and never fails: a missing gh, no network or an old
python3 ends it quietly. --hook is the SessionStart form: it reads the hook JSON
on stdin, adds its cwd, and prints the report as hook output.

Two kinds are report-only, never removed: `issue` (an open issue that a merged PR
mentions or connects to, with no comment since the merge) and `pr` (an open PR
whose changes are already in the default branch).

Writes the report to stdout; diagnostics to stderr. Needs git and an
authenticated gh.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

sys.dont_write_bytecode = True  # the plugin cache stays as installed
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "_shared"))
import doctor_lib  # noqa: E402  # ty: ignore[unresolved-import]
from git_env import batch_ssh, github_slug, without_repo_overrides  # noqa: E402  # ty: ignore[unresolved-import]
from resume_state import impl_matches  # noqa: E402  # ty: ignore[unresolved-import]

# Stock macOS python3 is 3.9; stop with the fix before the 3.11-only import below.
# A hook run has nobody to read the fix, so it ends quietly instead.
if sys.version_info < (3, 11) and {"--auto", "--hook"} & set(sys.argv):
    sys.exit(0)
doctor_lib.require_python((3, 11), "sisters", "/techne:setup")

import tomllib  # noqa: E402

TECHNE_TOML = Path.home() / ".claude" / "techne.toml"

# A worktree touched this recently may belong to a session that is still working
# in it, even when nothing is uncommitted.
IDLE_SECONDS = 2 * 60 * 60

# Ignored paths a worktree can lose without losing work: environments, caches
# and build output, all rebuilt by a command. Any other ignored path (COMMITS.md,
# .env, a nested .claude/worktrees/) holds the worktree for review.
REGENERABLE = {
    ".venv", "venv", "node_modules", "site", "build", "dist", "out", "target", "logs",
    "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".cache", ".coverage",
    "htmlcov", ".tox", ".nox", ".ipynb_checkpoints", ".DS_Store", "mutants",
}  # fmt: skip
# Generated directories matched only at the repo root, where their tools write them;
# deeper down the same name may be a folder a person made. Astro's types and content
# store, husky's shims (rebuilt on `npm install`), Playwright and Lighthouse CI reports.
REGENERABLE_PATHS = (".astro", ".husky/_", "test-results", "playwright-report", ".lighthouseci")
# chrome-launcher's throwaway Chrome profile (Lighthouse CI): a folder `lighthouse.` plus
# exactly 8 digits. Under WSL its Windows temp path lands in the repo as one folder name,
# which git quotes: "C:\\Users\\...\\lighthouse.80415069/".
LIGHTHOUSE_PROFILE = re.compile(
    r'^lighthouse\.\d{8}/$|^"[A-Za-z]:\\\\(?:[^"/\\]+\\\\)*lighthouse\.\d{8}/"$'
)
REGENERABLE_SUFFIXES = (
    ".egg-info", ".pyc", ".aux", ".bbl", ".blg", ".log", ".out", ".toc", ".fls",
    ".fdb_latexmk", ".synctex.gz", ".bcf", ".run.xml",
)  # fmt: skip


def unquote(entry: str) -> str:
    """A path as `git status` prints it, without git's C quoting of unusual names."""
    if len(entry) > 1 and entry[0] == entry[-1] == '"':
        return entry[1:-1].encode("latin-1", "backslashreplace").decode("unicode_escape")
    return entry


def is_chrome_profile(folder: Path) -> bool:
    """chrome-launcher's profile holds Chrome's own `Local State`; a reports folder does not."""
    return (folder / "Local State").is_file()


def is_latex_main(tex: Path) -> bool:
    """A .tex with its own \\documentclass: a fragment beside an exported figure does not count."""
    try:
        return "\\documentclass" in tex.read_text(errors="ignore")
    except OSError:
        return False


def regenerable(ignored: str, root: str | None = None) -> bool:
    if root and LIGHTHOUSE_PROFILE.match(ignored):
        return is_chrome_profile(Path(root, unquote(ignored)))
    path = ignored.rstrip("/")
    parts = path.split("/")
    # LaTeX output: x.pdf beside a document x.tex in the same worktree is rebuilt by latexmk.
    if root and path.endswith(".pdf") and is_latex_main(Path(root, path[:-4] + ".tex")):
        return True
    return bool(
        REGENERABLE & set(parts)
        or any(path == p or path.startswith(p + "/") for p in REGENERABLE_PATHS)
        or parts[-1].endswith(REGENERABLE_SUFFIXES)
        or any("cache" in part.lower() for part in parts)
    )


# Enough to cover every branch a working repo still carries. A branch whose PR
# falls past this is judged by ancestry alone, which only ever errs towards review.
PR_LIMIT = 500


@dataclass
class Item:
    kind: str  # worktree | local-branch | remote-branch | prune | stash | dirty-main
    name: str
    group: str  # remove | review | info
    reason: str
    sha: str = ""
    path: str = ""
    branch: str = ""
    # What a merge left behind, for --auto: "held" (a merged branch something blocks),
    # "closed" (its PR closed unmerged), "" (nothing, or a hold that clears by itself).
    left: str = ""
    # --auto removes only this: the branch's PR merged into the default branch at this tip,
    # or the worktree directory is gone. A branch merely inside the default branch (a fresh
    # `worktree add -b x origin/main`) is removable on request, never unasked.
    auto: bool = False


@dataclass
class Repo:
    name: str
    slug: str
    path: str
    items: list[Item] = field(default_factory=list)
    error: str = ""


# --auto runs unattended inside an async hook, which Claude Code does not kill on its
# timeout: it carries its own deadline, a cap on each call, and git that never prompts.
AUTO_DEADLINE = 240
CALL_TIMEOUT = 90
_deadline: float | None = None
_env: dict[str, str] | None = None


def over_deadline() -> bool:
    return _deadline is not None and time.time() >= _deadline


def sp(cmd: list[str], cwd: str | None = None) -> subprocess.CompletedProcess:
    """subprocess.run with captured text; under --auto it times out and obeys the deadline."""
    timeout = None
    if _deadline is not None:
        timeout = min(CALL_TIMEOUT, _deadline - time.time())
        if timeout <= 0:
            raise RuntimeError("deadline passed")
    try:
        return subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=without_repo_overrides() if _env is None else _env,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"{' '.join(cmd[:4])}: timed out") from None


def run(cmd: list[str], cwd: str | None = None, check: bool = True) -> str:
    proc = sp(cmd, cwd)
    if check and proc.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)}: {proc.stderr.strip() or proc.returncode}")
    return proc.stdout


def git(path: str, *args: str, check: bool = True) -> str:
    # --no-optional-locks: `status` must not refresh the index, or reading a
    # worktree would reset the idle clock this script relies on.
    return run(["git", "--no-optional-locks", "-C", path, *args], check=check)


def is_ancestor(path: str, a: str, b: str) -> bool:
    return sp(["git", "-C", path, "merge-base", "--is-ancestor", a, b]).returncode == 0


def has_object(path: str, sha: str) -> bool:
    return sp(["git", "-C", path, "cat-file", "-e", f"{sha}^{{commit}}"]).returncode == 0


def fetch_prs(slug: str) -> dict[str, dict]:
    """One same-repo PR per head branch name: an open one if any, else the newest."""
    out = run(
        [
            "gh", "pr", "list", "-R", slug, "--state", "all", "--limit", str(PR_LIMIT),
            "--json", "number,state,headRefName,headRefOid,baseRefName,isCrossRepository,author",
        ]
    )  # fmt: skip
    latest: dict[str, dict] = {}
    for pr in json.loads(out):
        if pr.get("isCrossRepository"):
            continue
        name, cur = pr["headRefName"], latest.get(pr["headRefName"])
        rank = (pr["state"] == "OPEN", pr["number"])
        if cur is None or rank > (cur["state"] == "OPEN", cur["number"]):
            latest[name] = pr
    return latest


def default_branch(slug: str) -> str:
    """From GitHub, not origin/HEAD, which a clone never updates on its own."""
    out = run(["gh", "repo", "view", slug, "--json", "defaultBranchRef"])
    return json.loads(out)["defaultBranchRef"]["name"]


def judge_branch(
    path: str, tip: str, default: str, pr: dict | None, me: str, remote: bool
) -> tuple[str, str]:
    """(group, reason) for one branch tip."""
    base = f"origin/{default}"
    if pr:
        num, state = pr["number"], pr["state"]
        if state == "OPEN":
            return "info", f"PR #{num} is open"
        if remote and pr.get("author", {}).get("login") != me:
            return "review", f"PR #{num} {state.lower()}, but the branch is not yours"
        head = pr["headRefOid"]
        if tip != head and not (has_object(path, head) and is_ancestor(path, tip, head)):
            if has_object(path, head) and is_ancestor(path, head, tip):
                ahead = git(path, "rev-list", "--count", f"{head}..{tip}").strip()
                return "review", f"{ahead} commit(s) added after PR #{num} {state.lower()}"
            return "review", f"tip differs from PR #{num}'s head"
        if state == "MERGED" and pr.get("baseRefName") != default:
            return "review", f"PR #{num} merged into {pr.get('baseRefName')}, not {default}"
        if state == "MERGED":
            return "remove", f"PR #{num} merged"
        return "review", f"PR #{num} closed without merging"
    if remote:  # a branch with no PR of yours may be anyone's: develop, a teammate's
        return "review", "no PR"
    if is_ancestor(path, tip, base):
        return "remove", f"already in {default}"
    ahead = git(path, "rev-list", "--count", f"{base}..{tip}").strip()
    return "review", f"no PR; {ahead} commit(s) not in {default}"


def worktrees(path: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    cur: dict[str, str] = {}
    for line in [*git(path, "worktree", "list", "--porcelain").splitlines(), ""]:
        if not line:
            if cur:
                out.append(cur)
            cur = {}
            continue
        key, _, value = line.partition(" ")
        cur[key] = value
    return out


def process_paths() -> list[str] | None:
    """Working directories and open files of live processes; None when the platform will not say."""
    proc = Path("/proc")
    if not proc.is_dir():
        try:  # macOS and the BSDs: one lsof for every process's cwd and open files
            out = sp(["lsof", "-Fn"])
        except (OSError, RuntimeError):
            return None
        if out.returncode not in (0, 1):
            return None
        return [line[1:] for line in out.stdout.splitlines() if line.startswith("n/")]
    paths: list[str] = []
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        targets = [entry / "cwd"]
        try:
            targets += list((entry / "fd").iterdir())
        except OSError:
            pass
        for target in targets:
            try:
                link = os.readlink(target)
            except OSError:
                continue
            if link.startswith("/"):  # sockets, pipes and anon inodes are not paths
                paths.append(link.removesuffix(" (deleted)"))
    return paths


def busy_paths() -> list[str] | None:
    return process_paths()


# Files walked under ignored paths before the search for recent activity gives up. A cap hit
# with nothing recent means the age cannot be told, which holds the worktree for a person.
ACTIVITY_FILE_CAP = 20000

# Installed environments and caches: only the entry itself is stat'ed, never walked. A write
# inside one is an install, not work, and a uv .venv alone holds tens of thousands of files.
ENVIRONMENTS = {".venv", "venv", "node_modules", ".tox", ".nox", "__pycache__"}


def _environment(rel: str) -> bool:
    parts = rel.rstrip("/").split("/")
    return bool(ENVIRONMENTS & set(parts)) or any("cache" in p.lower() for p in parts)


def last_activity(wt: str, ignored: tuple[str, ...] | list[str] = ()) -> float | None:
    """Newest mtime of HEAD, the index and anything ignored (a log, a build tree), or None
    when there are too many ignored files to tell.

    Stops at the first entry newer than the idle window: it only has to tell recent from not.
    Environments and caches are stat'ed but not walked, and come last.
    """
    gitdir = git(wt, "rev-parse", "--absolute-git-dir").strip()
    newest = max(
        (Path(gitdir, f).stat().st_mtime for f in ("HEAD", "index") if Path(gitdir, f).exists()),
        default=0.0,
    )
    cutoff = time.time() - IDLE_SECONDS
    if newest > cutoff:
        return newest
    seen = 0
    for rel in sorted(ignored, key=_environment):
        walk = not _environment(rel)
        stack = [os.path.join(wt, rel.rstrip("/"))]
        while stack:
            cur = stack.pop()
            try:
                st = os.lstat(cur)
            except OSError:
                continue
            newest = max(newest, st.st_mtime)
            if st.st_mtime > cutoff:
                return newest
            if not walk:
                break
            seen += 1
            if seen >= ACTIVITY_FILE_CAP:
                return None
            if stat.S_ISDIR(st.st_mode):
                try:
                    stack.extend(e.path for e in os.scandir(cur))
                except OSError:
                    pass
    return newest


BUSY_UNKNOWN = "cannot tell whether a process is using it"
UNCOMMITTED = " uncommitted change(s)"
ACTIVITY_UNKNOWN = "too many ignored files"
BUSY_LIVE = "a live process is using it"
ACTIVE_PREFIX = "active "


def worktree_blockers(wpath: str, others: list[str], busy: list[str] | None) -> list[str]:
    """Why a worktree must not be removed now; empty when nothing holds it."""
    # Explicit flags: a user's status.showUntrackedFiles=no must not hide work.
    lines = git(
        wpath, "status", "--porcelain", "--untracked-files=all", "--ignored=matching"
    ).splitlines()
    changes = [ln for ln in lines if not ln.startswith("!!")]
    kept = []
    for ln in lines:
        if ln.startswith("!!"):
            if not regenerable(ln[3:].strip(), wpath):
                kept.append(ln[3:].strip())
    nested = [o for o in others if o.startswith(wpath + os.sep)]
    ignored = [ln[3:].strip() for ln in lines if ln.startswith("!!")]
    last = last_activity(wpath, ignored)
    idle = IDLE_SECONDS if last is None else time.time() - last
    blockers = [
        f"{ACTIVITY_UNKNOWN} (over {ACTIVITY_FILE_CAP}) to tell whether it was used recently"
        if last is None
        else "",
        f"{len(changes)}{UNCOMMITTED}" if changes else "",
        f"ignored files that are not build output: {', '.join(kept[:3])}" if kept else "",
        f"{len(nested)} worktree(s) inside it" if nested else "",
        BUSY_UNKNOWN if busy is None else "",
        BUSY_LIVE if busy and any(c == wpath or c.startswith(wpath + os.sep) for c in busy) else "",
        f"{ACTIVE_PREFIX}{int(idle // 60)} min ago" if idle < IDLE_SECONDS else "",
    ]
    return [b for b in blockers if b]


def transient(blockers: list[str]) -> bool:
    """True when a hold clears by itself: a session working in it, or no way to tell."""
    return any(b in (BUSY_UNKNOWN, BUSY_LIVE) or b.startswith(ACTIVE_PREFIX) for b in blockers)


UNRESUMABLE = "not resumable from the branch: its IMPL.md is unchanged since it left "


def resume_gap(wpath: str, branch: str, base: str, blockers: list[str], merged: bool) -> str:
    """Uncommitted work in an idle worktree whose IMPL.md never said what the branch is for.

    A fresh session there, after a restart, has only the diff to go on. Empty when nobody
    is or may be at work in it, it is clean, it is detached, its PR merged (the work is
    finished), the repo keeps no IMPL.md, or git cannot tell.
    """
    dirty = any(b.endswith(UNCOMMITTED) for b in blockers)
    unsure = any(b.startswith(ACTIVITY_UNKNOWN) for b in blockers)
    if not branch or merged or not dirty or unsure or transient(blockers):
        return ""
    return UNRESUMABLE + base if impl_matches(wpath, base) is True else ""


def leftover(after: str, pr: dict | None, hold: list[str]) -> str:
    """Item.left for a branch or worktree: `after` is its group with its holds applied.

    A lasting hold (changes, kept ignored files) is reported even when a session is also at
    work in it; only holds that all clear by themselves are left out.
    """
    lasting = [b for b in hold if not transient([b])]
    if hold and not lasting:
        return ""  # only a session at work: a later run decides
    if pr and pr["state"] == "CLOSED":
        return "closed"
    finished = bool(pr and pr["state"] == "MERGED")  # only a merged PR leaves something behind
    return "held" if finished and after == "review" else ""


def collect(name: str, path: str, slug: str, me: str, prs: dict[str, dict]) -> list[Item]:
    items: list[Item] = []
    git(path, "fetch", "--quiet", "--prune", "origin")
    default = default_branch(slug)
    base = f"origin/{default}"
    now, busy = time.time(), busy_paths()

    trees = worktrees(path)
    main_tree = trees[0]["worktree"] if trees else path
    checked_out: dict[str, str] = {}
    for wt in trees:
        if "branch" in wt:
            checked_out[wt["branch"].removeprefix("refs/heads/")] = wt["worktree"]

    locals_ = {}
    for line in git(
        path, "for-each-ref", "--format=%(refname:lstrip=2) %(objectname)", "refs/heads/"
    ).splitlines():
        branch, sha = line.split()
        locals_[branch] = sha

    judged: dict[str, tuple[str, str]] = {}
    for branch, sha in locals_.items():
        if branch == default:
            continue
        judged[branch] = judge_branch(path, sha, default, prs.get(branch), me, remote=False)

    for wt in trees[1:]:
        wpath, head = wt["worktree"], wt.get("HEAD", "")
        label = os.path.relpath(wpath, path)
        if "prunable" in wt:
            items.append(Item("prune", label, "remove", "directory is gone", path=wpath, auto=True))
            continue
        branch = wt.get("branch", "").removeprefix("refs/heads/")
        if branch:
            group, reason = judged.get(branch, ("review", "unknown branch"))
        elif is_ancestor(path, head, base):
            group, reason = "remove", f"detached at a commit already in {default}"
        else:
            group, reason = "review", "detached with commits not in " + default
        others = [t["worktree"] for t in trees if t["worktree"] != wpath]
        blockers = ["locked"] if "locked" in wt else []
        blockers += worktree_blockers(wpath, others, busy)
        merged = bool(prs.get(branch) and prs[branch]["state"] == "MERGED")
        if blockers:
            group, reason = "review", reason + "; " + ", ".join(blockers)
            gap = resume_gap(wpath, branch, base, blockers, merged)
            reason += f"; {gap}" if gap else ""
        left = leftover(group, prs.get(branch), blockers) if group == "review" else ""
        items.append(
            Item(
                "worktree", label, group, reason, sha=head, path=wpath, branch=branch,
                left=left, auto=group == "remove" and merged,
            )
        )  # fmt: skip
        if branch:
            judged.pop(branch, None)  # removed with its worktree, or held with it

    for branch, (group, reason) in judged.items():
        if branch in checked_out and checked_out[branch] == main_tree:
            group, reason = "review", reason + "; checked out in the main checkout"
        left = leftover(group, prs.get(branch), []) if group == "review" else ""
        merged = bool(prs.get(branch) and prs[branch]["state"] == "MERGED")
        items.append(
            Item(
                "local-branch", branch, group, reason, sha=locals_[branch],
                left=left, auto=group == "remove" and merged,
            )
        )  # fmt: skip

    for line in git(
        path, "for-each-ref", "--format=%(refname:lstrip=3) %(objectname)", "refs/remotes/origin/"
    ).splitlines():
        branch, sha = line.split()
        if branch in ("HEAD", default):
            continue
        pr = prs.get(branch)
        group, reason = judge_branch(path, sha, default, pr, me, remote=True)
        mine = bool(pr and pr.get("author", {}).get("login") == me)
        left = leftover(group, pr, []) if group == "review" and mine else ""
        items.append(
            Item("remote-branch", branch, group, reason, sha=sha, left=left, auto=group == "remove")
        )

    for line in git(path, "stash", "list", "--format=%gd%x09%ct%x09%gs").splitlines():
        ref, ts, msg = line.split("\t", 2)
        days = int((now - int(ts)) // 86400)
        items.append(Item("stash", ref, "info", f"{days}d old: {msg}"))

    dirty = git(main_tree, "status", "--porcelain").strip()
    if dirty:
        on = git(main_tree, "branch", "--show-current").strip() or "detached"
        items.append(
            Item(
                "dirty-main",
                on,
                "info",
                f"{len(dirty.splitlines())} uncommitted change(s) in the main checkout",
            )
        )
    items += landed_prs(path, default, prs, me)
    try:
        items += stale_issues(fetch_issue_links(slug), slug, time.time(), me)
    except (RuntimeError, OSError, ValueError, KeyError, TypeError):
        pass  # issues are a courtesy; a GraphQL failure must not hide the branch survey
    return items


# git merge-tree --write-tree arrived in 2.38.
MERGE_TREE_GIT = (2, 38)
ISSUE_AGE_SECONDS = 24 * 60 * 60

ISSUE_QUERY = """
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    issues(states: OPEN, first: 100, orderBy: {field: UPDATED_AT, direction: DESC}) {
      nodes {
        number
        comments(last: 1) { nodes { createdAt } }
        reopened: timelineItems(itemTypes: [REOPENED_EVENT], last: 1) {
          nodes { ... on ReopenedEvent { createdAt } }
        }
        closedByPullRequestsReferences(includeClosedPrs: true, first: 10) {
          nodes {
            number merged mergedAt baseRefName
            author { login }
            baseRepository { nameWithOwner }
          }
        }
      }
    }
  }
}
"""


def git_version() -> tuple[int, int]:
    m = re.search(r"(\d+)\.(\d+)", run(["git", "--version"], check=False))
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def landed_prs(path: str, default: str, prs: dict[str, dict], me: str) -> list[Item]:
    """Open same-repo PRs whose changes the default branch already holds.

    Merging the head into the default branch in memory yields the default branch's own
    tree exactly when the head adds nothing: a squash or rebase merged elsewhere, or a
    cherry-pick. Report-only, and only for the configured user's PRs.
    """
    if git_version() < MERGE_TREE_GIT:
        return []
    base = f"origin/{default}"
    try:
        base_tree = git(path, "rev-parse", f"{base}^{{tree}}").strip()
    except RuntimeError:
        return []
    items = []
    for branch, pr in sorted(prs.items()):
        if pr["state"] != "OPEN" or pr.get("baseRefName") != default:
            continue
        if (pr.get("author") or {}).get("login") != me:
            continue  # someone else's PR is theirs to close
        proc = sp(["git", "-C", path, "merge-tree", "--write-tree", base, f"origin/{branch}"])
        lines = proc.stdout.splitlines()
        if proc.returncode == 0 and lines and lines[0].strip() == base_tree:
            reason = f"open, but its changes are already in {default}; close it"
            items.append(Item("pr", f"#{pr['number']}", "review", reason, branch=branch))
    return items


def fetch_issue_links(slug: str) -> dict:
    owner, name = slug.split("/", 1)
    out = run(
        ["gh", "api", "graphql", "-f", f"query={ISSUE_QUERY}", "-f", f"owner={owner}",
         "-f", f"name={name}"]
    )  # fmt: skip
    return json.loads(out)


def parse_time(stamp: str) -> float:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()


def stale_issues(payload: dict, slug: str, now: float, me: str) -> list[Item]:
    """Open issues that one of the user's merged same-repo PRs was linked to close.

    GitHub clears `willCloseTarget` once a PR merges, so the link is read from the issue
    (`closedByPullRequestsReferences`: a closing keyword or a manual link; a bare mention is
    not one, and a follow-up issue is often filed from the PR that spawned it). The merge must
    be a day old; a comment or a reopen after it counts as someone having looked.
    Report-only.
    """
    items = []
    for issue in payload["data"]["repository"]["issues"]["nodes"]:
        merges = []
        for pr in issue["closedByPullRequestsReferences"]["nodes"]:
            repo = (pr.get("baseRepository") or {}).get("nameWithOwner", "")
            author = (pr.get("author") or {}).get("login", "")
            if pr.get("merged") and repo.lower() == slug.lower() and author.lower() == me.lower():
                merges.append((parse_time(pr["mergedAt"]), pr["number"], pr["mergedAt"]))
        if not merges:
            continue
        merged_at, number, stamp = max(merges)
        if now - merged_at < ISSUE_AGE_SECONDS:
            continue
        looked = [c["createdAt"] for c in issue["comments"]["nodes"]]
        looked += [e["createdAt"] for e in issue["reopened"]["nodes"] if e.get("createdAt")]
        if any(parse_time(t) > merged_at for t in looked):
            continue
        reason = f"PR #{number} merged {stamp[:10]}; close it, or comment what is left"
        items.append(Item("issue", f"#{issue['number']}", "review", reason))
    return items


def canonical_slug(slug: str) -> str:
    """owner/name as GitHub now knows it, so a transferred repo matches; SLUG when it cannot say."""
    try:
        return json.loads(run(["gh", "repo", "view", slug, "--json", "nameWithOwner"]))[
            "nameWithOwner"
        ]
    except (RuntimeError, OSError, ValueError, KeyError):
        return slug


def read_config() -> tuple[str, str, list[dict]]:
    """(workspace_root, github_user, [[sisters]] tables), or exit with a message."""
    where = f"Run /techne:setup, or see {doctor_lib.CONFIG_DOCS}"
    try:
        with TECHNE_TOML.open("rb") as f:
            cfg = tomllib.load(f)
        ws, me, sisters = cfg["workspace_root"], cfg["github_user"], cfg["sisters"]
    except FileNotFoundError:
        sys.exit(f"sisters: {TECHNE_TOML} not found. {where}")
    except tomllib.TOMLDecodeError as exc:
        sys.exit(f"sisters: {TECHNE_TOML} is not valid TOML ({exc}). {where}")
    except KeyError as exc:
        sys.exit(f"sisters: {TECHNE_TOML} has no {exc.args[0]}. {where}")
    if not isinstance(sisters, list) or not all(isinstance(s, dict) for s in sisters):
        sys.exit(f"sisters: sisters in {TECHNE_TOML} must be a list of tables. {where}")
    for number, sister in enumerate(sisters, 1):
        if not isinstance(sister.get("name"), str):
            sys.exit(f"sisters: [[sisters]] entry {number} in {TECHNE_TOML} has no name. {where}")
    return str(ws), str(me), sisters


def load_sisters(names: list[str]) -> tuple[list[tuple[str, str, str]], str]:
    ws, me, sisters = read_config()
    active = [s["name"] for s in sisters if s.get("status", "active") == "active"]
    chosen = names or active
    return [(n, f"{me}/{n}", str(Path(ws) / n)) for n in chosen], me


def print_env() -> None:
    """The audit preamble's shell variables, quoted for eval."""
    ws, me, sisters = read_config()
    active = [s for s in sisters if s.get("status", "active") == "active"]
    if not active:
        sys.exit(f"sisters: no active sisters in {TECHNE_TOML}. Run /techne:setup.")
    team = [s["name"] for s in active if str(s.get("kind", "")).strip().lower() == "team"]
    print(f"SISTERS={shlex.quote(' '.join(s['name'] for s in active))}")
    print(f"TEAM_SISTERS={shlex.quote(' '.join(team))}")
    print(f"WORKSPACE={shlex.quote(ws)}")
    print(f"GITHUB_USER={shlex.quote(me)}")


def survey(targets: list[tuple[str, str, str]], me: str) -> list[Repo]:
    repos = []
    for name, slug, path in targets:
        repo = Repo(name, slug, path)
        try:
            repo.items = collect(name, path, slug, me, fetch_prs(slug))
        except (RuntimeError, OSError) as exc:  # one broken repo never stops the rest
            repo.error = str(exc)
        repos.append(repo)
    return repos


def report(repos: list[Repo]) -> str:
    lines = []
    for repo in repos:
        lines.append(f"### {repo.name}")
        if repo.error:
            lines.append(f"- error: {repo.error}")
            continue
        if not repo.items:
            lines.append("- Clean. ✓")
        for group, title in (
            ("remove", "Safe to remove"),
            ("review", "Needs a look"),
            ("info", "Info"),
        ):
            chosen = [i for i in repo.items if i.group == group]
            if chosen:
                lines.append(f"{title}:")
                lines += [f"- {i.kind} `{i.name}`: {i.reason}" for i in chosen]
        lines.append("")
    total = sum(1 for r in repos for i in r.items if i.group == "remove")
    lines.append(f"{total} item(s) safe to remove.")
    return "\n".join(lines)


def key(repo: str, item: Item) -> tuple:
    return (repo, item.kind, item.name, item.sha)


def execute(repo: Repo, item: Item) -> str:
    if item.kind == "prune":
        git(repo.path, "worktree", "prune")
    elif item.kind == "worktree":
        # Checked again at the last moment: a session may have started in it since
        # the survey. No --force, so git refuses on its own if a file lands after this.
        others = [t["worktree"] for t in worktrees(repo.path) if t["worktree"] != item.path]
        held = worktree_blockers(item.path, others, busy_paths())
        if held:
            raise RuntimeError("held: " + ", ".join(held))
        git(repo.path, "worktree", "remove", item.path)
        if item.branch:
            git(repo.path, "update-ref", "-d", f"refs/heads/{item.branch}", item.sha)
    elif item.kind == "local-branch":
        ref = f"refs/heads/{item.name}"
        # A worktree may have taken the branch since the survey (the main checkout included).
        if any(t.get("branch") == ref for t in worktrees(repo.path)):
            raise RuntimeError("checked out in a worktree")
        git(repo.path, "update-ref", "-d", ref, item.sha)
    elif item.kind == "remote-branch":
        ref = f"refs/heads/{item.name}"
        # --no-verify: a pre-push hook has nothing to check on a delete.
        git(
            repo.path,
            "push",
            "--quiet",
            "--no-verify",
            f"--force-with-lease={ref}:{item.sha}",
            "origin",
            f":{ref}",
        )
    else:
        raise ValueError(f"not removable: {item.kind}")
    return f"removed {item.kind} `{item.name}`"


def apply(plan_file: Path) -> int:
    plan = json.loads(plan_file.read_text())
    approved = {(p["repo"], p["kind"], p["name"], p["sha"]) for p in plan["remove"]}
    names = sorted({p["repo"] for p in plan["remove"]})
    targets, me = load_sisters(names)
    failures = 0
    for repo in survey(targets, me):
        if repo.error:
            print(f"{repo.name}: skipped, {repo.error}")
            failures += 1
            continue
        still = {key(repo.name, i): i for i in repo.items if i.group == "remove"}
        for k in sorted(a for a in approved if a[0] == repo.name):
            item = still.get(k)
            if not item:
                print(f"{repo.name}: kept {k[1]} `{k[2]}`, no longer safe or it moved")
                continue
            try:
                print(f"{repo.name}: {execute(repo, item)}")
            except RuntimeError as exc:
                print(f"{repo.name}: failed {k[1]} `{k[2]}`: {exc}")
                failures += 1
    return 1 if failures else 0


AUTO_INTERVAL = 30 * 60


def cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "techne"


def repo_for_path(
    directory: str, me: str, roster: dict[str, str], slugs: frozenset[str] = frozenset()
) -> tuple[str, str, str] | None:
    """(name, canonical slug, main worktree) for the repo holding DIRECTORY, or None to skip it.

    A repo counts when its owner is the configured user, its path is in the roster, or its
    GitHub name is a roster repo's (SLUGS, lowercase), whichever name the clone's remote has.
    """
    try:
        common = git(directory, "rev-parse", "--git-common-dir").strip()
        common = os.path.realpath(os.path.join(directory, common))
        if os.path.basename(common) != ".git":
            return None
        main = os.path.dirname(common)
        remote = git(main, "remote", "get-url", "origin").strip()
    except (RuntimeError, OSError):
        return None
    found = github_slug(remote)
    if not found:
        return None
    slug = canonical_slug("/".join(found))
    owner, repo = slug.split("/", 1)
    if owner.lower() != me.lower() and main not in roster and slug.lower() not in slugs:
        return None
    return repo, slug, main


def auto_targets(
    paths: list[str], names: list[str], sweep: bool
) -> tuple[list[tuple[str, str, str]], str]:
    """The roster (when SWEEP) plus the repo of each path. The hook's own repo always counts."""
    roster_targets, me = load_sisters(names)
    roster = {os.path.realpath(p): n for n, _, p in roster_targets}
    slugs = (
        frozenset(canonical_slug(s).lower() for _, s, _ in roster_targets) if paths else frozenset()
    )
    targets = [(n, canonical_slug(s), p) for n, s, p in roster_targets] if sweep else []
    seen = {os.path.realpath(p) for _, _, p in targets}
    for directory in paths:
        found = repo_for_path(directory, me, roster, slugs)
        if found and found[2] not in seen:
            seen.add(found[2])
            targets.append(found)
    return targets, me


def held_lines(repo: Repo) -> dict[str, list[str]]:
    """Lines for the report's two lists: left behind by a merge, and closed unmerged."""
    out: dict[str, list[str]] = {"held": [], "closed": []}
    for i in repo.items:
        if i.group != "review":
            continue
        line = f"- {repo.name}: {i.kind} `{i.name}`: {i.reason}"
        if i.kind in ("issue", "pr"):
            out["held"].append(line)
        elif i.left in out:
            out[i.left].append(line)
    return out


def auto_report(removed: list[str], held: list[str], closed: list[str]) -> str:
    sections = []
    for title, lines in (
        ("Removed", removed),
        ("Held after merge", held),
        ("Closed without merging", closed),
    ):
        if lines:
            sections.append(f"{title} ({len(lines)}):\n" + "\n".join(lines))
    return "\n\n".join(sections)


def log_removal(log: Path, repo: Repo, item: Item) -> None:
    """Appended before the removal, so a crash mid-way still leaves what was about to go."""
    stamp = datetime.now().astimezone().isoformat(timespec="seconds")
    with log.open("a") as f:
        f.write(f"{stamp}\t{repo.name}\t{item.kind}\t{item.name}\t{item.sha}\n")


def run_auto(paths: list[str], names: list[str], min_interval: int) -> str:
    """Clean what a merged PR finished and return the report; "" when there is nothing to say.

    The interval gates the roster sweep only; the repos of PATHS (the session's own) are always
    processed. Holding the lock is what keeps two runs apart, and closing the file frees it on
    every exit path.
    """
    global _deadline, _env
    try:
        import fcntl
    except ImportError:  # Windows: no lock, the stamp still limits the rate
        fcntl = None
    if not shutil.which("gh") or not shutil.which("git"):
        return ""
    cache = cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    log = cache / "hygiene-auto.log"
    with open(cache / "hygiene-auto.lock", "w") as lock:
        if fcntl:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return ""  # another run is cleaning
        stamp = cache / "hygiene-auto.stamp"
        sweep = not (stamp.exists() and time.time() - stamp.stat().st_mtime < min_interval)
        if sweep:
            stamp.touch()
        _deadline = time.time() + AUTO_DEADLINE
        _env = {**without_repo_overrides(), "GIT_TERMINAL_PROMPT": "0"}
        try:
            return clean_targets(paths, names, sweep, log)
        finally:
            _deadline, _env = None, None


def clean_targets(paths: list[str], names: list[str], sweep: bool, log: Path) -> str:
    global _env
    targets, me = auto_targets(paths, names, sweep)
    base = _env if _env is not None else without_repo_overrides()
    removed: list[str] = []
    held: list[str] = []
    closed: list[str] = []
    for target in targets:
        if over_deadline():
            break
        try:  # one repo's surprise must not stop the next, or lose the report of earlier removals
            _env = batch_ssh(base, target[2])  # every git call in the repo, lazy fetches included
            (repo,) = survey([target], me)
            if repo.error:
                continue  # offline, logged out or broken: a later run tries again
            for item in repo.items:
                if item.group != "remove" or not item.auto or over_deadline():
                    continue
                try:
                    log_removal(log, repo, item)
                    execute(repo, item)
                except (RuntimeError, OSError, ValueError):
                    continue  # held at the last moment: next run decides
                removed.append(f"- {repo.name}: {item.kind} `{item.name}`: {item.reason}")
            lines = held_lines(repo)
            held += lines["held"]
            closed += lines["closed"]
        except Exception:
            continue
    text = auto_report(removed, held, closed)
    return f"{text}\n\nRemovals are logged in {log}." if removed else text


HOOK_NOTE = (
    "Investigate each held item before touching it: what it holds that the default branch "
    "lacks (commits by patch-id, uncommitted changes, ignored files that are not build output). "
    "Report what you find to the user. Remove an item only when that check shows nothing would "
    "be lost, or when the user says to."
)


def hook_output(report_text: str) -> str:
    if not report_text:
        return ""
    holds = "Held after merge" in report_text or "Closed without merging" in report_text
    context = f"{report_text}\n\n{HOOK_NOTE}" if holds else report_text
    return json.dumps(
        {
            "systemMessage": report_text,
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": context,
            },
        }
    )


def hook_cwd() -> list[str]:
    if sys.stdin.isatty():
        return []
    try:
        cwd = json.load(sys.stdin).get("cwd")
    except (ValueError, OSError, AttributeError):
        return []
    return [cwd] if isinstance(cwd, str) and cwd else []


def auto_main(args: argparse.Namespace) -> int:
    """--auto and --hook never fail and never print an error: a hook that does is noise."""
    try:
        paths = list(args.path) + (hook_cwd() if args.hook else [])
        text = run_auto(paths, args.repo, args.min_interval)
    except (Exception, SystemExit):  # a bad config exits; a hook stays quiet either way
        return 0
    out = hook_output(text) if args.hook else text
    if out:
        print(out)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", action="append", default=[], help="sister name; repeatable")
    parser.add_argument("--json", action="store_true", help="print the full survey as JSON")
    parser.add_argument("--plan-out", type=Path, help="write the safe-to-remove items here")
    parser.add_argument("--env", action="store_true", help="print the audit's shell variables")
    parser.add_argument("--apply", type=Path, metavar="PLAN", help="remove what PLAN approved")
    parser.add_argument(
        "--auto", action="store_true", help="remove what is finished, report the rest"
    )
    parser.add_argument(
        "--path", action="append", default=[], help="also clean the repo holding DIR"
    )
    parser.add_argument(
        "--min-interval", type=int, default=AUTO_INTERVAL, help="seconds between --auto runs"
    )
    parser.add_argument("--hook", action="store_true", help="--auto as a SessionStart hook")
    args = parser.parse_args()
    if args.auto or args.hook:
        return auto_main(args)
    if args.env:
        print_env()
        return 0
    if args.apply:
        return apply(args.apply)
    targets, me = load_sisters(args.repo)
    repos = survey(targets, me)
    if args.json:
        print(json.dumps([asdict(r) for r in repos], indent=2))
    else:
        print(report(repos))
    if args.plan_out:
        remove = [
            asdict(i) | {"repo": r.name} for r in repos for i in r.items if i.group == "remove"
        ]
        args.plan_out.write_text(json.dumps({"remove": remove}, indent=2))
    return 1 if any(r.error for r in repos) else 0


if __name__ == "__main__":
    sys.exit(main())
