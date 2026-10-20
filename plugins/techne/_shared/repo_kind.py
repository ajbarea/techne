"""Whether a repo is solo (the user's own: a skill acts) or team (others work in it: a skill asks).

Only GitHub facts about the signed-in user can make a repo solo: not in an organization, the
user administers it, nobody else can push, and it is not a fork of a live upstream (unless the
user lists it as a sister, which says the fork is their own line of work). Other signals can
only make it team, and are checked first because they need no network:
1. an `- owner: team` line under `## repo` in the repo's committed `.claude/skill-context.md`;
2. its `[[sisters]]` entry, matched by path (`workspace_root/<name>`), in ~/.claude/techne.toml
   with `kind = "team"`.
Anything unsettled (no repo, no GitHub origin, gh failing) reads as team, so a skill asks rather
than acts on someone else's repo. An `owner: solo` line is only true for its author, so it is
not trusted on its own.

Usage: python3 repo_kind.py [path]   ->  prints `solo: <why>` or `team: <why>`, exits 0.
A path may be a file or a directory, as docsync passes the doc it audits.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

TECHNE_TOML = Path.home() / ".claude" / "techne.toml"
TIMEOUT = 10
OWNER_TEAM = re.compile(r"^\s*-\s*owner:\s*team\b", re.IGNORECASE | re.MULTILINE)
GITHUB_REMOTE = re.compile(r"github\.com[:/]([^/\s]+)/([^/\s]+?)(?:\.git)?/?$")


def sh(*args: str) -> str | None:
    """stdout of a command, or None when it fails, times out or is missing."""
    # A git hook exports GIT_DIR and GIT_WORK_TREE, which would override `git -C`.
    env = {k: v for k, v in os.environ.items() if k not in ("GIT_DIR", "GIT_WORK_TREE")}
    try:
        done = subprocess.run(args, capture_output=True, text=True, timeout=TIMEOUT, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def as_directory(path: str) -> Path:
    """The nearest existing directory at or above path, so a file target works too."""
    target = Path(path).absolute()
    while not target.exists() and target != target.parent:
        target = target.parent
    return target if target.is_dir() else target.parent


def repo_section(text: str) -> str:
    """The body of the `## repo` section of a skill-context file, or ''."""
    match = re.search(r"^## repo[ \t]*\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    return match.group(1) if match else ""


def marked_team_in_repo(top: Path) -> bool:
    try:
        text = (top / ".claude" / "skill-context.md").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return bool(OWNER_TEAM.search(repo_section(text)))


def sister_entry(main_checkout: Path, path: Path = TECHNE_TOML) -> dict | None:
    """The [[sisters]] table whose workspace_root/<name> is this checkout, or None."""
    import tomllib  # 3.11+; imported here so hygiene.py can load this module on 3.9 and explain

    try:
        with path.open("rb") as f:
            cfg = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return None
    root, sisters = cfg.get("workspace_root"), cfg.get("sisters")
    if not isinstance(root, str) or not isinstance(sisters, list):
        return None
    for sister in sisters:
        if isinstance(sister, dict) and isinstance(sister.get("name"), str):
            if Path(root).expanduser() / sister["name"] == main_checkout:
                return sister
    return None


def from_github(owner: str, name: str, listed: bool = False) -> tuple[str, str]:
    slug = f"{owner}/{name}"
    raw = sh("gh", "repo", "view", slug, "--json", "parent,isInOrganization,viewerPermission")
    try:
        info = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        info = None
    if not isinstance(info, dict):
        return "team", f"could not read {slug} on GitHub"
    parent = info.get("parent")
    if isinstance(parent, dict) and parent and not listed:  # a fork of a live upstream
        up = f"{(parent.get('owner') or {}).get('login')}/{parent.get('name')}"
        return "team", f"{slug} is a fork of {up}, so its changes may land there"
    if info.get("isInOrganization"):
        return "team", f"{slug} belongs to an organization"
    if info.get("viewerPermission") != "ADMIN":
        return "team", f"{slug} is not yours: your permission is {info.get('viewerPermission')}"
    pushers = sh(
        "gh", "api", "--paginate", f"repos/{slug}/collaborators",
        "--jq", ".[] | select(.permissions.push) | .login",
    )  # fmt: skip
    if pushers is None:
        return "team", f"could not list the collaborators of {slug}"
    logins = sorted(set(pushers.split()))
    if len(logins) != 1:
        return "team", f"{', '.join(logins) or 'nobody listed'} can push to {slug}"
    return "solo", f"{logins[0]} owns {slug} and is its only collaborator with push access"


def classify(path: str = ".", toml: Path = TECHNE_TOML) -> tuple[str, str]:
    where = str(as_directory(path))
    top_out = sh("git", "-C", where, "rev-parse", "--show-toplevel")
    if not top_out:
        return "team", f"{path} is not in a git repository"
    if marked_team_in_repo(Path(top_out)):
        return "team", "owner: team in .claude/skill-context.md"
    common = sh("git", "-C", where, "rev-parse", "--path-format=absolute", "--git-common-dir")
    sister = sister_entry(Path(common).parent, toml) if common else None
    if sister and sister.get("kind") == "team":
        return "team", f'kind = "team" in {toml}'
    slug = GITHUB_REMOTE.search(sh("git", "-C", where, "remote", "get-url", "origin") or "")
    if not slug:
        return "team", "no GitHub origin to check ownership against"
    return from_github(slug.group(1), slug.group(2), listed=sister is not None)


def main(argv: list[str]) -> int:
    kind, why = classify(argv[1] if len(argv) > 1 else ".")
    print(f"{kind}: {why}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
