"""Whether a repo is solo (the user's own: a skill acts) or team (others work in it: a skill asks).

Only GitHub facts about the signed-in user can make a repo solo: not in an organization, the
user administers it, nobody else can push, and it is not a fork of a live upstream (unless the
user lists it as a sister, which says the fork is their own line of work). Other signals can
only make it team, and are checked first because they need no network:
1. an `- owner: team` line under `## repo` in the repo's `.claude/skill-context.md`, in the
   working tree, the current commit or the default branch;
2. its `[[sisters]]` entry, matched by path (`workspace_root/<name>`), in ~/.claude/techne.toml
   with `kind = "team"`.
Anything unsettled (no repo, no GitHub origin, gh failing, techne.toml present but unreadable)
reads as team, so a skill asks rather than acts on someone else's repo. An `owner: solo` line
is only true for its author, so it is not trusted on its own.

Usage: python3 repo_kind.py [path]   ->  prints `solo: <why>` or `team: <why>`, exits 0.
A path may be a file or a directory, as docsync passes the doc it audits. Runs on python3 3.9;
reading techne.toml needs 3.11, and below that an existing techne.toml reads as team.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import doctor_lib
from git_env import GITHUB_REMOTE, without_repo_overrides
from project_board import techne_toml

TIMEOUT = 10
SKILL_CONTEXT = ".claude/skill-context.md"
# `- owner: team`, `owner: team` or `owner: "team"`, as other skill-context keys are written.
OWNER_TEAM = re.compile(r"""^\s*(?:-\s*)?owner:\s*["']?team\b""", re.IGNORECASE | re.MULTILINE)
REPO_SECTION = re.compile(r"^##[ \t]+repo\b[^\n]*\n(.*?)(?=^##[ \t]|\Z)", re.I | re.M | re.S)


class TomlUnreadable(Exception):
    """techne.toml exists but this python3 cannot parse it, so a team entry may be missed."""


def sh(*args: str) -> str | None:
    """stdout of a command, or None when it fails, times out or is missing."""
    env = without_repo_overrides()
    code, out = doctor_lib.run(args, timeout=TIMEOUT, merge_stderr=False, env=env)
    return out.strip() if code == 0 else None


def as_directory(path: str) -> Path:
    """The nearest existing directory at or above path, so a file target works too."""
    target = Path(path).absolute()
    while not target.exists() and target != target.parent:
        target = target.parent
    return target if target.is_dir() else target.parent


def repo_section(text: str) -> str:
    """The body of the `## repo` section of a skill-context file, or ''."""
    match = REPO_SECTION.search(text)
    return match.group(1) if match else ""


def marked_team_in_repo(where: str, top: Path) -> bool:
    """An owner: team line in the working tree, the current commit or the default branch."""

    def texts():
        try:
            yield (top / SKILL_CONTEXT).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            pass
        for ref in ("HEAD", "origin/HEAD"):
            yield sh("git", "-C", where, "show", f"{ref}:{SKILL_CONTEXT}") or ""

    return any(OWNER_TEAM.search(repo_section(text)) for text in texts())


def sister_entry(checkouts: set[Path], path: Path) -> dict | None:
    """The [[sisters]] table whose workspace_root/<name> is one of these paths, or None."""
    if not path.exists():
        return None
    try:
        import tomllib
    except ImportError as exc:  # python3 below 3.11, as on stock macOS
        raise TomlUnreadable(f"python3 {sys.version.split()[0]} cannot read {path}") from exc
    try:
        with path.open("rb") as f:
            cfg = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise TomlUnreadable(f"cannot read {path}: {exc}") from exc
    root, sisters = cfg.get("workspace_root"), cfg.get("sisters")
    if not isinstance(root, str) or not isinstance(sisters, list):
        return None
    here = {p.resolve() for p in checkouts}
    for sister in sisters:
        if isinstance(sister, dict) and isinstance(sister.get("name"), str):
            if (Path(root).expanduser() / sister["name"]).resolve() in here:
                return sister
    return None


def from_github(owner: str, name: str, listed: bool = False) -> tuple[str, str]:
    slug = f"{owner}/{name}"
    raw = sh(
        "gh",
        "repo",
        "view",
        f"github.com/{slug}",
        "--json",
        "parent,isInOrganization,viewerPermission",
    )
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
        "gh", "api", "--hostname", "github.com", "--paginate", f"repos/{slug}/collaborators",
        "--jq", ".[] | select(.permissions.push) | .login",
    )  # fmt: skip
    if pushers is None:
        return "team", f"could not list the collaborators of {slug}"
    logins = sorted(set(pushers.split()))
    if len(logins) != 1:
        return "team", f"{', '.join(logins) or 'nobody listed'} can push to {slug}"
    invited = sh(
        "gh", "api", "--hostname", "github.com", "--paginate", f"repos/{slug}/invitations",
        "--jq", ".[].invitee.login",
    )  # fmt: skip
    if invited is None:
        return "team", f"could not list the pending invitations to {slug}"
    if invited.split():
        return "team", f"{', '.join(sorted(set(invited.split())))} is invited to {slug}"
    return "solo", f"{logins[0]} owns {slug} and is its only collaborator with push access"


def classify(path: str = ".", toml: Path | None = None) -> tuple[str, str]:
    toml = toml or techne_toml()
    where = str(as_directory(path))
    out = (sh("git", "-C", where, "rev-parse", "--show-toplevel", "--git-common-dir") or "").split(
        "\n"
    )
    if len(out) != 2:
        return "team", f"{path} is not in a git repository"
    top, common = Path(out[0]), (Path(where) / out[1]).resolve()  # common is relative to `where`
    if marked_team_in_repo(where, top):
        return "team", f"owner: team in {SKILL_CONTEXT}"
    # Where a roster may name this repo: its top level (a submodule, a --separate-git-dir repo),
    # the folder holding its common dir (<checkout>/.git, or <checkout>/.bare behind worktrees),
    # or a bare `<name>.git` common dir behind worktrees.
    checkouts = {top, common.parent}
    if common.name.endswith(".git") and common.name != ".git":
        checkouts.add(common.with_name(common.name[: -len(".git")]))
    try:
        sister = sister_entry(checkouts, toml)
    except TomlUnreadable as exc:
        return "team", str(exc)
    if sister and str(sister.get("kind", "")).lower() == "team":
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
