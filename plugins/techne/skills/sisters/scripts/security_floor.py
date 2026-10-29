#!/usr/bin/env python3
"""Check each sister against the security floor (check 17).

Usage:
    security_floor.py WORKSPACE REPO [REPO ...]

Per repo, from GitHub (through `gh`) and from its workflow files:
  - secret scanning and push protection on (free on public repos; a private
    repo needs GitHub Secret Protection, a paid add-on, so it is reported
    as the user's decision, not a gap)
  - Dependabot alerts on
  - zizmor run by a workflow (the workflow linter)
  - every action pinned to a full commit SHA, or the workflow dependency
    lockfile (.github/workflows/actions.lock), which GitHub calls the stronger
    form; a reusable workflow call needs a SHA either way
  - least-privilege `permissions:` in every workflow: set at the top or on
    every job, and never write-all

Prints one line per repo: `<repo>: security floor ✓`, or the gaps. A repo whose
GitHub settings cannot be read (no gh, no network, no admin access) says so on
that line and still gets its workflow checks. Always exits 0.
"""

# research(2026-10): docs.github.com/en/actions/reference/security/secure-use (pin to a
# full-length SHA; least-privilege GITHUB_TOKEN; Scorecards' token-permission and pinned-action
# checks), .../concepts/security/workflow-dependency-lockfiles (actions.lock supersedes SHA
# pins; reusable calls still need a SHA), the repos API's security_and_analysis field and the
# vulnerability-alerts endpoint (204 on, 404 off).

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

GH = os.environ.get("TECHNE_GH", "gh")
SHA = re.compile(r"@[0-9a-f]{40}$")
USES = re.compile(r"^\s*(?:-\s+)?uses:\s*['\"]?([^'\"\s#]+)")
TOP_KEY = re.compile(r"^([A-Za-z_][\w-]*):")


def gh(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([GH, *args], capture_output=True, text=True, timeout=30)


def slug(root: Path) -> str | None:
    """owner/name of the repo's origin on GitHub."""
    try:
        url = subprocess.run(
            ["git", "-C", str(root), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r"(?:^|[@/])github\.com[:/]([^/]+/[^/]+?)(?:\.git)?/?$", url)
    return m.group(1) if m else None


def remote_gaps(name: str) -> tuple[list[str], list[str]]:
    """(gaps, notes) from GitHub's settings for owner/name."""
    gaps: list[str] = []
    notes: list[str] = []
    try:
        repo = gh("api", f"repos/{name}")
        if repo.returncode:
            return [], [f"GitHub settings not read ({(repo.stderr.strip() or 'gh failed')[:80]})"]
        data = json.loads(repo.stdout)
        if not (data.get("permissions") or {}).get("admin"):
            return [], ["GitHub settings not read (needs admin access)"]
        sa = data.get("security_and_analysis") or {}

        def on(key: str) -> bool:
            return (sa.get(key) or {}).get("status") == "enabled"

        off = [
            label
            for key, label in (
                ("secret_scanning", "secret scanning"),
                ("secret_scanning_push_protection", "push protection"),
            )
            if not on(key)
        ]
        if off and data.get("private"):
            paid = "private: needs GitHub Secret Protection, the user's call"
            notes.append(f"{' and '.join(off)} off ({paid})")
        elif off:
            gaps.append(f"{' and '.join(off)} off")
        alerts = gh("api", "-i", f"repos/{name}/vulnerability-alerts")
        status = alerts.stdout.splitlines()[0] if alerts.stdout else ""
        if " 404" in status:
            gaps.append("Dependabot alerts off")
        elif " 204" not in status:
            notes.append("Dependabot alerts not read (needs admin access)")
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        return [], [f"GitHub settings not read ({type(exc).__name__})"]
    return gaps, notes


def workflow_files(root: Path) -> list[Path]:
    folder = root / ".github" / "workflows"
    return sorted(p for p in folder.glob("*.y*ml") if p.is_file()) if folder.is_dir() else []


def composite_actions(root: Path) -> list[Path]:
    """The repo's own composite actions: their `uses:` are pinned like a workflow's."""
    folder = root / ".github" / "actions"
    return (
        sorted(p for p in folder.glob("**/action.y*ml") if p.is_file()) if folder.is_dir() else []
    )


def read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


ZIZMOR = re.compile(r"^\s*(?:-\s+)?(?:run:.*\bzizmor\b|uses:\s*['\"]?zizmorcore/zizmor-action@)")


def perm_value(line: str) -> str:
    """A `permissions:` line's value, its comment dropped."""
    return line.split(":", 1)[1].split("#", 1)[0].strip()


def jobs_without_permissions(text: str) -> list[str]:
    """Jobs with no `permissions:` key of their own, read by indentation."""
    out: list[str] = []
    in_jobs = False
    job: str | None = None
    job_indent = child_indent = 0
    has = False

    def close() -> None:
        if job and not has:
            out.append(job)

    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent == 0:
            close()
            job, in_jobs = None, line.startswith("jobs:")
            continue
        if not in_jobs:
            continue
        if job is None or indent <= job_indent:
            close()
            job, job_indent, child_indent, has = line.strip().rstrip(":"), indent, 0, False
            continue
        child_indent = child_indent or indent
        if indent == child_indent and line.strip().startswith("permissions:"):
            has = True
            if perm_value(line.strip()) == "write-all":
                out.append(f"{job} (write-all)")
    close()
    return out


def workflow_gaps(root: Path) -> list[str]:
    files = workflow_files(root)
    if not files:
        return []
    gaps: list[str] = []
    lock = read(root / ".github" / "workflows" / "actions.lock") or ""
    unpinned: list[str] = []
    no_perms: list[str] = []
    write_all: list[str] = []
    unreadable: list[str] = []
    zizmor = False
    for path in files + composite_actions(root):
        text = read(path)
        if text is None:
            unreadable.append(path.name)
            continue
        workflow = path.parent.name == "workflows"
        # Only a workflow the lockfile names is onboarded (GitHub onboards them one by one).
        locked = workflow and path.name in lock
        for line in text.splitlines():
            zizmor |= workflow and bool(ZIZMOR.match(line))
            m = USES.match(line)
            if not m:
                continue
            ref = m.group(1)
            if ref.startswith(("./", "docker://")):
                continue  # local actions; Docker refs are out of scope
            reusable = "/.github/workflows/" in ref
            if not SHA.search(ref) and (reusable or not locked):
                unpinned.append(f"{path.name}: {ref}")
        if not workflow:
            continue
        top = {m.group(1): line for line in text.splitlines() if (m := TOP_KEY.match(line))}
        missing = jobs_without_permissions(text)
        if "permissions" in top and perm_value(top["permissions"]) == "write-all":
            write_all.append(path.name)
        elif any(j.endswith("(write-all)") for j in missing):
            write_all.append(path.name)
        elif "permissions" not in top and missing:
            no_perms.append(path.name)
    if not zizmor:
        gaps.append("no zizmor in CI")
    if unpinned:
        gaps.append(f"{len(unpinned)} action refs not pinned to a SHA (first: {unpinned[0]})")
    if no_perms:
        gaps.append(f"no permissions: in {', '.join(no_perms)}")
    if write_all:
        gaps.append(f"permissions: write-all in {', '.join(write_all)}")
    if unreadable:
        gaps.append(f"could not read {', '.join(unreadable)}")
    return gaps


def check(root: Path) -> tuple[list[str], list[str]]:
    if not (root / ".git").exists():
        return [f"not a git repository at {root}"], []
    gaps = workflow_gaps(root)
    name = slug(root)
    notes: list[str] = []
    if name:
        remote, notes = remote_gaps(name)
        gaps = remote + gaps
    else:
        notes.append("no GitHub origin, settings not checked")
    return gaps, notes


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__.strip())
        return 0
    workspace = Path(argv[0]).expanduser()
    for name in argv[1:]:
        gaps, notes = check(workspace / name)
        tail = f" ({'; '.join(notes)})" if notes else ""
        if gaps:
            word = "gap" if len(gaps) == 1 else "gaps"
            print(f"{name}: {len(gaps)} security floor {word}: {'; '.join(gaps)}{tail}")
        else:
            print(f"{name}: security floor ✓{tail}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
