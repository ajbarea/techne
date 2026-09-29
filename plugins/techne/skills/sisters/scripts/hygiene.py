#!/usr/bin/env python3
"""Branch, worktree and stash hygiene across the sister repos, with a guarded clean mode.

Usage:
    hygiene.py [--repo NAME ...] [--json] [--plan-out FILE]
    hygiene.py --apply FILE

Report mode (the default) reads every active sister in ~/.claude/techne.toml, or
the --repo names, and sorts what it finds into three groups per repo:

  remove   provably finished: a PR merged into the default branch whose head is
           the branch tip (or contains it), or a local branch with no PR already
           inside the default branch; a worktree on such a branch that is clean,
           idle and unused; a prunable worktree
  review   anything a person should decide: unmerged commits, commits added after
           the PR merged, a PR merged elsewhere or closed unmerged, a dirty,
           locked, busy, recently active or ignored-work-holding worktree, a
           remote branch with no PR or someone else's
  info     branches of open PRs, stashes, uncommitted changes in the main checkout

Squash merges leave a branch's own commits outside main forever, so "ahead of
main" says nothing about whether it shipped. The PR's state does: a branch is
finished when its PR merged and the tip is the head that merged.

--plan-out writes the remove group as JSON. --apply takes that file, collects
every repo in it afresh, and runs only the actions that are still in the remove
group with the same tip. Every deletion is compare-and-delete on that tip, so a
branch that moved after the plan was shown is left alone.

Writes the report to stdout; diagnostics to stderr. Needs git and an
authenticated gh.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path

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
REGENERABLE_SUFFIXES = (
    ".egg-info", ".pyc", ".aux", ".bbl", ".blg", ".log", ".out", ".toc", ".fls",
    ".fdb_latexmk", ".synctex.gz", ".bcf", ".run.xml",
)  # fmt: skip


def regenerable(ignored: str) -> bool:
    parts = ignored.rstrip("/").split("/")
    return bool(
        REGENERABLE & set(parts)
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


@dataclass
class Repo:
    name: str
    slug: str
    path: str
    items: list[Item] = field(default_factory=list)
    error: str = ""


def run(cmd: list[str], cwd: str | None = None, check: bool = True) -> str:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)}: {proc.stderr.strip() or proc.returncode}")
    return proc.stdout


def git(path: str, *args: str, check: bool = True) -> str:
    # --no-optional-locks: `status` must not refresh the index, or reading a
    # worktree would reset the idle clock this script relies on.
    return run(["git", "--no-optional-locks", "-C", path, *args], check=check)


def is_ancestor(path: str, a: str, b: str) -> bool:
    return (
        subprocess.run(
            ["git", "-C", path, "merge-base", "--is-ancestor", a, b], capture_output=True
        ).returncode
        == 0
    )


def has_object(path: str, sha: str) -> bool:
    return (
        subprocess.run(
            ["git", "-C", path, "cat-file", "-e", f"{sha}^{{commit}}"], capture_output=True
        ).returncode
        == 0
    )


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


def busy_paths() -> list[str] | None:
    """Working directories of live processes; None when the platform will not say."""
    cwds: list[str] = []
    proc = Path("/proc")
    if not proc.is_dir():
        try:  # macOS and the BSDs
            out = subprocess.run(["lsof", "-d", "cwd", "-Fn"], capture_output=True, text=True)
        except OSError:
            return None
        if out.returncode not in (0, 1):
            return None
        return [line[1:] for line in out.stdout.splitlines() if line.startswith("n")]
    for entry in proc.iterdir():
        if entry.name.isdigit():
            try:
                cwds.append(os.readlink(entry / "cwd"))
            except OSError:
                continue
    return cwds


def last_activity(wt: str) -> float:
    gitdir = git(wt, "rev-parse", "--absolute-git-dir").strip()
    stamps = [
        Path(gitdir, f).stat().st_mtime for f in ("HEAD", "index") if Path(gitdir, f).exists()
    ]
    return max(stamps, default=0.0)


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
            if not regenerable(ln[3:].strip()):
                kept.append(ln[3:].strip())
    nested = [o for o in others if o.startswith(wpath + os.sep)]
    idle = time.time() - last_activity(wpath)
    blockers = [
        f"{len(changes)} uncommitted change(s)" if changes else "",
        f"ignored files that are not build output: {', '.join(kept[:3])}" if kept else "",
        f"{len(nested)} worktree(s) inside it" if nested else "",
        "cannot tell whether a process is using it" if busy is None else "",
        "a live process is using it"
        if busy and any(c == wpath or c.startswith(wpath + os.sep) for c in busy)
        else "",
        f"active {int(idle // 60)} min ago" if idle < IDLE_SECONDS else "",
    ]
    return [b for b in blockers if b]


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
            items.append(Item("prune", label, "remove", "directory is gone", path=wpath))
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
        if blockers:
            group, reason = "review", reason + "; " + ", ".join(blockers)
        items.append(Item("worktree", label, group, reason, sha=head, path=wpath, branch=branch))
        if branch:
            judged.pop(branch, None)  # removed with its worktree, or held with it

    for branch, (group, reason) in judged.items():
        if branch in checked_out and checked_out[branch] == main_tree:
            group, reason = "review", reason + "; checked out in the main checkout"
        items.append(Item("local-branch", branch, group, reason, sha=locals_[branch]))

    for line in git(
        path, "for-each-ref", "--format=%(refname:lstrip=3) %(objectname)", "refs/remotes/origin/"
    ).splitlines():
        branch, sha = line.split()
        if branch in ("HEAD", default):
            continue
        group, reason = judge_branch(path, sha, default, prs.get(branch), me, remote=True)
        items.append(Item("remote-branch", branch, group, reason, sha=sha))

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
    return items


def load_sisters(names: list[str]) -> tuple[list[tuple[str, str, str]], str]:
    with TECHNE_TOML.open("rb") as f:
        cfg = tomllib.load(f)
    ws, me = cfg["workspace_root"], cfg["github_user"]
    active = [s["name"] for s in cfg["sisters"] if s.get("status", "active") == "active"]
    chosen = names or active
    return [(n, f"{me}/{n}", str(Path(ws) / n)) for n in chosen], me


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
        git(repo.path, "update-ref", "-d", f"refs/heads/{item.name}", item.sha)
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", action="append", default=[], help="sister name; repeatable")
    parser.add_argument("--json", action="store_true", help="print the full survey as JSON")
    parser.add_argument("--plan-out", type=Path, help="write the safe-to-remove items here")
    parser.add_argument("--apply", type=Path, metavar="PLAN", help="remove what PLAN approved")
    args = parser.parse_args()
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
