"""Whether a repo is solo (the user's own: a skill acts) or team (others work in it: a skill asks).

Only GitHub facts about the signed-in user can make a repo solo: not in an organization, the
user administers it, nobody else can push, and it is not a fork of a live upstream (unless its
`[[sisters]]` entry says `kind = "solo"`, an explicit claim that the fork is the user's own line
of work). Other signals can only make it team, and are checked first:
1. a line holding the words `owner` and `team` anywhere in the repo's
   `.claude/skill-context.md`, in the working tree, the current commit or the default branch;
2. its `[[sisters]]` entry in ~/.claude/techne.toml with `kind = "team"`, matched by path
   (`workspace_root/<name>`) or, for another clone, by `<github_user>/<name>` as the origin.
Anything unsettled (no repo, no GitHub origin, gh failing, techne.toml present but unreadable)
reads as team, so a skill asks rather than acts on someone else's repo. An `owner: solo` line
is only true for its author, so it is not trusted on its own.

Usage: python3 repo_kind.py [path]   ->  prints `solo: <why>` or `team: <why>`, exits 0, and
reads any unexpected error as team too.
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
# An owner line, erring toward team: any line outside an HTML comment that holds the whole
# word `owner` (or `owners`) and the whole word `team`, in either order. No distance or form to
# count, so every Markdown, table, alignment or HTML spelling counts. Closed <!-- comments -->,
# including multi-line ones, are removed first, which is how the setup template ships the line
# disabled.
_OWNER = re.compile(r"(?<![A-Za-z0-9])owners?(?![A-Za-z0-9])", re.IGNORECASE)
_TEAM = re.compile(r"(?<![A-Za-z0-9])team(?![A-Za-z0-9])", re.IGNORECASE)
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def says_team(text: str) -> bool:
    """Whether any line of a skill-context file pairs `owner` with `team`. It can only make a repo
    team, so it counts anywhere in the file. NUL characters are dropped first, so UTF-16 text
    read as UTF-8 (git show of a PowerShell 5 file) still matches."""
    text = _COMMENT.sub(" ", text.replace("\x00", ""))
    return any(_OWNER.search(line) and _TEAM.search(line) for line in text.splitlines())


def decode(raw: bytes) -> str:
    """A skill-context file as text: UTF-16 when it starts with a UTF-16 byte-order mark (as
    PowerShell 5 writes), otherwise UTF-8 with bad bytes replaced, never an exception."""
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", "replace")
    return raw.decode("utf-8", "replace")


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


def marked_team_in_repo(where: str, top: Path) -> bool:
    """An owner: team line in the working tree or the current commit. The default branch is
    read from GitHub in from_github, since a local origin/<branch> ref may be stale."""
    try:
        if says_team(decode((top / SKILL_CONTEXT).read_bytes())):
            return True
    except OSError:
        pass
    return says_team(sh("git", "-C", where, "show", f"HEAD:{SKILL_CONTEXT}") or "")


def kind_of(sister: dict) -> str:
    """A [[sisters]] entry's kind, lowercased: "team", "solo" or ""."""
    return str(sister.get("kind", "")).strip().lower()


def is_team(sister: dict) -> bool:
    return kind_of(sister) == "team"


def same_remote(root: object, name: str, slug: tuple[str, str] | None) -> bool:
    """Whether the roster checkout workspace_root/<name> has this origin, so another clone of a
    team sister whose folder and GitHub names differ still matches it. Run for team entries only,
    since only a team match changes the answer."""
    if not slug or not isinstance(root, str):
        return False
    checkout = Path(root).expanduser() / name
    if not checkout.is_dir():
        return False
    theirs = github_slug(sh("git", "-C", str(checkout), "remote", "get-url", "origin") or "")
    return bool(theirs) and tuple(p.lower() for p in theirs) == tuple(p.lower() for p in slug)


def sister_entry(checkouts: set[Path], slug: tuple[str, str] | None, path: Path) -> dict | None:
    """The [[sisters]] table for this repo, or None: matched by workspace_root/<name> against
    the checkout paths, or by name when the origin is <github_user>/<name> (another clone)."""
    if not path.exists() and not path.is_symlink():  # a broken link is present but unreadable
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
    matches = []
    for sister in sisters:
        if not isinstance(sister, dict) or not isinstance(sister.get("name"), str):
            continue
        by_path = (
            isinstance(root, str) and (Path(root).expanduser() / sister["name"]).resolve() in here
        )
        by_slug = mine and slug is not None and sister["name"].lower() == slug[1].lower()
        if by_path or by_slug or (is_team(sister) and same_remote(root, sister["name"], slug)):
            matches.append(sister)
    # A team entry wins over any other entry the same repo matches.
    teams = [m for m in matches if is_team(m)]
    return (teams or matches or [None])[0]


_REPO_QUERY = (
    "query($o:String!,$n:String!){repository(owner:$o,name:$n){"
    "owner{login} parent{name owner{login}} isInOrganization viewerPermission "
    f'object(expression:"HEAD:{SKILL_CONTEXT}"){{... on Blob{{text isBinary isTruncated}}}}}}}}'
)


def from_github(owner: str, name: str, fork_ok: bool = False) -> tuple[str, str]:
    """The GitHub facts, read in one round trip: one GraphQL query (ownership, fork, the
    default branch's skill-context.md) with the collaborator and invitation lists alongside."""
    slug = f"{owner}/{name}"
    api = ("gh", "api", "--hostname", "github.com")
    with ThreadPoolExecutor(max_workers=3) as pool:
        querying = pool.submit(
            sh, *api, "graphql", "-f", f"query={_REPO_QUERY}",
            "-f", f"o={owner}", "-f", f"n={name}", "--jq", ".data.repository",
        )  # fmt: skip
        pushing = pool.submit(
            sh, *api, "--paginate", f"repos/{slug}/collaborators",
            "--jq", ".[] | select(.permissions.push) | .login",
        )  # fmt: skip
        inviting = pool.submit(
            sh,
            *api,
            "--paginate",
            f"repos/{slug}/invitations",
            "--jq",
            '.[] | (.invitee.login // "an-email-invitee")',
        )
        raw, pushers, invited = querying.result(), pushing.result(), inviting.result()
    try:
        info = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        info = None
    if not isinstance(info, dict):
        return "team", f"could not read {slug} on GitHub"
    parent = info.get("parent")
    if isinstance(parent, dict) and parent and not fork_ok:  # a fork of a live upstream
        up = f"{(parent.get('owner') or {}).get('login')}/{parent.get('name')}"
        return (
            "team",
            f'{slug} is a fork of {up} (kind = "solo" on its sister entry says otherwise)',
        )
    if info.get("isInOrganization"):
        return "team", f"{slug} belongs to an organization"
    if info.get("viewerPermission") != "ADMIN":
        return "team", f"{slug} is not yours: your permission is {info.get('viewerPermission')}"
    blob = info.get("object")
    if isinstance(blob, dict) and (blob.get("isBinary") or blob.get("isTruncated")):
        return "team", f"{SKILL_CONTEXT} on {slug}'s default branch is not whole text, so unread"
    if isinstance(blob, dict) and says_team(str(blob.get("text") or "")):
        return "team", f"owner: team in {SKILL_CONTEXT} on {slug}'s default branch"
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


# A remote through an ssh host alias, scp form (git@github-work:o/r) or URL form
# (ssh://git@github-work/o/r): host, owner, name.
_ALIAS_REMOTE = re.compile(
    r"^(?:ssh://)?(?:[^@/\s]+@)?([^:/\s]+)(?:(?<=[^/]):(?!\d+/)|(?::\d+)?/)"
    r"([^/\s]+)/([^/\s]+?)(?:\.git)?/?$"
)


def github_slug(url: str) -> tuple[str, str] | None:
    """owner/name of a GitHub remote, including one through an ssh host alias (git@github-work:o/r
    or ssh://git@github-work/o/r, as several-account setups use) that `ssh -G` resolves to
    github.com."""
    found = GITHUB_REMOTE.search(url)
    if found:
        return found.group(1), found.group(2)
    scp = _ALIAS_REMOTE.match(url)
    if not scp:
        return None
    if scp.group(1).startswith("-"):  # never hand ssh an option from a remote URL
        return None
    settings = sh("ssh", "-G", "--", scp.group(1)) or ""
    host = next((ln.split()[1] for ln in settings.splitlines() if ln.startswith("hostname ")), "")
    if host.lower() in ("github.com", "ssh.github.com"):
        return scp.group(2), scp.group(3)
    return None


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
    slug = github_slug(sh("git", "-C", where, "remote", "get-url", "origin") or "")
    try:
        sister = sister_entry(checkouts, slug, toml)
    except TomlUnreadable as exc:
        return "team", str(exc)
    if sister and is_team(sister):
        return "team", f'kind = "team" in {toml}'
    if not slug:
        return "team", "no GitHub origin to check ownership against"
    fork_ok = bool(sister) and kind_of(sister) == "solo"
    return from_github(*slug, fork_ok=fork_ok)


def main(argv: list[str]) -> int:
    try:
        kind, why = classify(argv[1] if len(argv) > 1 else ".")
    except Exception as exc:  # any surprise (no HOME, an unreadable folder) reads as team
        kind, why = "team", f"could not classify: {type(exc).__name__}: {exc}"
    print(f"{kind}: {why}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
