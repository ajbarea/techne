"""Whether a repo is solo (the user's own: a skill acts) or team (others work in it: a skill asks).

Only GitHub facts about the signed-in user can make a repo solo: not in an organization, the
user administers it, nobody else can push, and it is not a fork of a live upstream (unless the
user lists it as a sister, which says the fork is their own line of work). Other signals can
only make it team, and are checked first because they need no network:
1. an `owner: team` line anywhere in the repo's `.claude/skill-context.md`, in any Markdown
   form, in the working tree, the current commit or the default branch;
2. its `[[sisters]]` entry in ~/.claude/techne.toml with `kind = "team"`, matched by path
   (`workspace_root/<name>`) or, for another clone, by `<github_user>/<name>` as the origin.
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
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.dont_write_bytecode = True  # the plugin cache stays as installed
sys.path.insert(0, str(Path(__file__).resolve().parent))
import doctor_lib  # noqa: E402
from git_env import GITHUB_REMOTE, without_repo_overrides  # noqa: E402
from project_board import techne_toml  # noqa: E402

TIMEOUT = 10
SKILL_CONTEXT = ".claude/skill-context.md"
# Markdown decoration around a key-value line: blockquote marks, list bullets and numbers, table
# pipes, emphasis and quotes. Stripped before matching, so `owner: team` counts in any form.
_DECORATION = re.compile(r"""^\s*(?:>\s*)*(?:(?:[-*+]|\d+[.)])\s+)?|[|*_`"']""")
_OWNER_TEAM = re.compile(r"^\s*owner\s*[:=]?\s*team\b", re.IGNORECASE)


def says_team(text: str) -> bool:
    """Whether any line of a skill-context file is an owner: team line, in any Markdown form.
    It can only make a repo team, so it counts anywhere in the file, not only under ## repo."""
    return any(_OWNER_TEAM.match(_DECORATION.sub(" ", line)) for line in text.splitlines())


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


def marked_team_at(where: str, *refs: str) -> bool:
    """An owner: team line in .claude/skill-context.md at any of these commits."""
    return any(
        says_team(sh("git", "-C", where, "show", f"{ref}:{SKILL_CONTEXT}") or "") for ref in refs
    )


def marked_team_in_repo(where: str, top: Path) -> bool:
    """An owner: team line in the working tree, the current commit or origin/HEAD."""
    try:
        if says_team((top / SKILL_CONTEXT).read_text(encoding="utf-8")):
            return True
    except (OSError, UnicodeDecodeError):
        pass
    return marked_team_at(where, "HEAD", "origin/HEAD")


def sister_entry(checkouts: set[Path], slug: tuple[str, str] | None, path: Path) -> dict | None:
    """The [[sisters]] table for this repo, or None: matched by workspace_root/<name> against
    the checkout paths, or by name when the origin is <github_user>/<name> (another clone)."""
    if not path.exists():
        return None
    try:
        import tomllib
    except ImportError as exc:  # python3 below 3.11, as on stock macOS
        raise TomlUnreadable(f"python3 {sys.version.split()[0]} cannot read {path}") from exc
    try:
        with path.open("rb") as f:
            cfg = tomllib.load(f)
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise TomlUnreadable(f"cannot read {path}: {exc}") from exc
    root, sisters, me = cfg.get("workspace_root"), cfg.get("sisters"), cfg.get("github_user")
    if not isinstance(sisters, list):
        return None
    here = {p.resolve() for p in checkouts}
    mine = bool(slug and isinstance(me, str) and slug[0].lower() == me.lower())
    for sister in sisters:
        if not isinstance(sister, dict) or not isinstance(sister.get("name"), str):
            continue
        if isinstance(root, str) and (Path(root).expanduser() / sister["name"]).resolve() in here:
            return sister
        if mine and slug and sister["name"].lower() == slug[1].lower():
            return sister
    return None


def from_github(owner: str, name: str, where: str, listed: bool = False) -> tuple[str, str]:
    slug = f"{owner}/{name}"
    fields = "owner,parent,isInOrganization,viewerPermission,defaultBranchRef"
    raw = sh("gh", "repo", "view", f"github.com/{slug}", "--json", fields)
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
    default = (info.get("defaultBranchRef") or {}).get("name")
    if isinstance(default, str) and default and marked_team_at(where, f"origin/{default}"):
        return "team", f"owner: team in {SKILL_CONTEXT} on origin/{default}"
    api = ("gh", "api", "--hostname", "github.com", "--paginate")
    with ThreadPoolExecutor(max_workers=2) as pool:  # two lookups, one wait
        pushing = pool.submit(
            sh,
            *api,
            f"repos/{slug}/collaborators",
            "--jq",
            ".[] | select(.permissions.push) | .login",
        )
        inviting = pool.submit(sh, *api, f"repos/{slug}/invitations", "--jq", ".[].invitee.login")
        pushers, invited = pushing.result(), inviting.result()
    if pushers is None:
        return "team", f"could not list the collaborators of {slug}"
    logins = sorted(set(pushers.split()))
    the_owner = (info.get("owner") or {}).get("login")
    if logins != [the_owner]:
        return "team", f"{', '.join(logins) or 'nobody listed'} can push to {slug}"
    if invited is None:
        return "team", f"could not list the pending invitations to {slug}"
    if invited.split():
        return "team", f"{', '.join(sorted(set(invited.split())))} is invited to {slug}"
    return "solo", f"{the_owner} owns {slug} and is its only collaborator with push access"


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
    found = GITHUB_REMOTE.search(sh("git", "-C", where, "remote", "get-url", "origin") or "")
    slug = (found.group(1), found.group(2)) if found else None
    try:
        sister = sister_entry(checkouts, slug, toml)
    except TomlUnreadable as exc:
        return "team", str(exc)
    if sister and str(sister.get("kind", "")).lower() == "team":
        return "team", f'kind = "team" in {toml}'
    if not slug:
        return "team", "no GitHub origin to check ownership against"
    return from_github(*slug, where=where, listed=sister is not None)


def main(argv: list[str]) -> int:
    kind, why = classify(argv[1] if len(argv) > 1 else ".")
    print(f"{kind}: {why}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
