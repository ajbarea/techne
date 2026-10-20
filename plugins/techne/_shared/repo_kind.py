"""Whether a repo is solo (the user's own: a skill acts) or team (others work in it: a skill asks).

Decided from facts, the most specific first:
1. the repo's committed `.claude/skill-context.md`: an `- owner: solo` or `- owner: team`
   line under `## repo`, which travels with the repo to every machine and collaborator;
2. its `[[sisters]]` entry in ~/.claude/techne.toml: `kind = "team"`, or solo when listed
   without it;
3. GitHub: a repo owned by the signed-in gh user (not an organization) whose only collaborator
   with push access is that user.
Anything left unsettled reads as team, so a skill asks rather than acts on someone else's repo.

Usage: python3 repo_kind.py [path]   ->  prints `solo: <why>` or `team: <why>`, exits 0.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

TECHNE_TOML = Path.home() / ".claude" / "techne.toml"
TIMEOUT = 15
OWNER_LINE = re.compile(r"^\s*-\s*owner:\s*(solo|team)\b", re.IGNORECASE | re.MULTILINE)
SLUG = re.compile(r"github\.com[:/]([^/\s]+)/([^/\s]+?)(?:\.git)?/?$")


def sh(*args: str, cwd: str | None = None) -> str | None:
    """stdout of a command, or None when it fails, times out or is missing."""
    try:
        done = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def repo_section(text: str) -> str:
    """The body of the `## repo` section of a skill-context file, or ''."""
    match = re.search(r"^## repo[ \t]*\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    return match.group(1) if match else ""


def from_skill_context(top: Path) -> str | None:
    try:
        text = (top / ".claude" / "skill-context.md").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    match = OWNER_LINE.search(repo_section(text))
    return match.group(1).lower() if match else None


def from_techne_toml(names: set[str], path: Path = TECHNE_TOML) -> str | None:
    try:
        with path.open("rb") as f:
            sisters = tomllib.load(f).get("sisters", [])
    except (OSError, tomllib.TOMLDecodeError):
        return None
    if not isinstance(sisters, list):
        return None
    for sister in sisters:
        if isinstance(sister, dict) and sister.get("name") in names:
            return "team" if sister.get("kind") == "team" else "solo"
    return None


def from_github(owner: str, name: str) -> tuple[str, str]:
    me = sh("gh", "api", "user", "--jq", ".login")
    if not me:
        return "team", "could not read the signed-in GitHub user"
    jq = "{login: .owner.login, type: .owner.type}"
    raw = sh("gh", "api", f"repos/{owner}/{name}", "--jq", jq)
    try:
        info = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        info = None
    if not isinstance(info, dict):
        return "team", f"could not read {owner}/{name} on GitHub"
    if info.get("type") != "User" or info.get("login") != me:
        return "team", f"{owner}/{name} is owned by {info.get('login')}, not {me}"
    pushers = sh(
        "gh",
        "api",
        "--paginate",
        f"repos/{owner}/{name}/collaborators",
        "--jq",
        ".[] | select(.permissions.push) | .login",
    )
    if pushers is None:
        return "team", f"could not list the collaborators of {owner}/{name}"
    others = sorted({p for p in pushers.split() if p != me})
    if others:
        return "team", f"{', '.join(others)} can push to {owner}/{name}"
    return "solo", f"{me} owns {owner}/{name} and is its only collaborator with push access"


def classify(path: str = ".", toml: Path = TECHNE_TOML) -> tuple[str, str]:
    top_out = sh("git", "-C", path, "rev-parse", "--show-toplevel")
    if not top_out:
        return "team", f"{path} is not in a git repository"
    top = Path(top_out)
    kind = from_skill_context(top)
    if kind:
        return kind, "owner line in .claude/skill-context.md"
    names = set()
    common = sh("git", "-C", path, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if common:
        names.add(Path(common).parent.name)  # the main checkout's folder, also from a worktree
    url = sh("git", "-C", path, "remote", "get-url", "origin") or ""
    slug = SLUG.search(url)
    if slug:
        names.add(slug.group(2))
    kind = from_techne_toml(names, toml)
    if kind:
        return kind, f"[[sisters]] entry in {toml}"
    if not slug:
        return "team", "no GitHub origin to check ownership against"
    return from_github(slug.group(1), slug.group(2))


def main(argv: list[str]) -> int:
    kind, why = classify(argv[1] if len(argv) > 1 else ".")
    print(f"{kind}: {why}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
