"""~/.claude/techne.toml: the one reader and roster rules every techne script shares.

load() returns the parsed table, or None when there is no file, and raises a ConfigError when a
file is there but cannot be used. Each caller decides what that means: the sisters audit exits
with the message, the board hook does nothing, repo_kind reads the repo as team. Imports on
python3 3.9; parsing needs tomllib (3.11), and below it load() raises NeedsTomllib.
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

MAX_BYTES = 1 << 20  # a config or skill-context file is a few KB; past this it is not one


def techne_toml() -> Path:
    return Path.home() / ".claude" / "techne.toml"


class ConfigError(Exception):
    """techne.toml is there but cannot be used; the message says why, in one line."""


class NeedsTomllib(ConfigError):
    """python3 below 3.11 has no TOML parser."""


class ConfigUnreadable(ConfigError):
    """The file cannot be opened or read: permissions, a broken link, a folder."""


class ConfigInvalid(ConfigError):
    """The file is read but is not valid TOML, or its roster is malformed."""


class Unusable(Exception):
    """A file that is there but not one to read: the message completes "<path> ..."."""


def read_regular(path: Path, limit: int = MAX_BYTES) -> bytes | None:
    """The bytes of PATH, or None when there is no file. Only a regular file under LIMIT bytes is
    read, so a link to /dev/zero or a FIFO can neither hang nor fill memory: the file is opened
    without blocking and checked through that open descriptor, so it cannot be swapped between
    the check and the read. Raises Unusable for a broken link, anything not a regular file, or a
    file over LIMIT; OSError when unreadable."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
    except (FileNotFoundError, NotADirectoryError):
        if path.is_symlink():
            raise Unusable("is a link to a missing file") from None
        return None
    try:
        regular = stat.S_ISREG(os.fstat(fd).st_mode)
    except OSError:
        os.close(fd)
        raise
    if not regular:  # a device, FIFO or folder
        os.close(fd)
        raise Unusable("is not a regular file")
    with os.fdopen(fd, "rb") as f:
        raw = f.read(limit + 1)
    if len(raw) > limit:
        raise Unusable(f"is over {limit} bytes")
    return raw


def load(path: Path | None = None) -> dict | None:
    """The parsed techne.toml, or None when there is no file. A broken link is unreadable, not
    absent: the roster it points at may hold a team entry."""
    path = path or techne_toml()
    try:
        raw = read_regular(path, MAX_BYTES)
    except Unusable as exc:
        raise ConfigUnreadable(f"cannot read {path}: it {exc}") from None
    except OSError as exc:
        raise ConfigUnreadable(f"cannot read {path}: {exc.strerror or exc}") from exc
    if raw is None:
        return None
    try:
        import tomllib
    except ImportError as exc:  # python3 below 3.11, as on stock macOS
        raise NeedsTomllib(f"python3 {sys.version.split()[0]} cannot read {path}") from exc
    try:
        return tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ConfigInvalid(f"{path} is not valid TOML ({exc})") from exc


def sisters(cfg: dict, path: Path | None = None) -> list[dict]:
    """The [[sisters]] tables, [] when there are none. A roster that is there but malformed
    raises ConfigInvalid rather than dropping entries, since a dropped entry may be a team one."""
    where = path or techne_toml()
    roster = cfg.get("sisters", [])
    if not isinstance(roster, list) or not all(isinstance(s, dict) for s in roster):
        raise ConfigInvalid(f"sisters in {where} must be a list of tables")
    for number, sister in enumerate(roster, 1):
        name = sister.get("name")
        if not isinstance(name, str) or not name:
            raise ConfigInvalid(f"[[sisters]] entry {number} in {where} has no name")
        if name in (".", "..") or "/" in name or "\\" in name:  # checkout() joins it to the root
            raise ConfigInvalid(
                f"[[sisters]] entry {number} in {where}: name {name!r} must be one folder name"
            )
    return roster


def required(cfg: dict, path: Path | None = None) -> tuple[Path, str, list[dict]]:
    """(workspace_root, github_user, [[sisters]]) for a script that needs all three. Raises
    ConfigInvalid naming the first that is missing or of the wrong type."""
    where = path or techne_toml()
    for key in ("workspace_root", "github_user", "sisters"):
        if key not in cfg:
            raise ConfigInvalid(f"{where} has no {key}")
    roster = sisters(cfg, where)
    ws, me = workspace_root(cfg), github_user(cfg)
    if ws is None:
        raise ConfigInvalid(f"workspace_root in {where} must be a path")
    if me is None:
        raise ConfigInvalid(f"github_user in {where} must be a login")
    return ws, me, roster


def kind_of(sister: dict) -> str:
    """A [[sisters]] entry's kind, lowercased: "team", "solo" or ""."""
    return str(sister.get("kind", "")).strip().lower()


def is_team(sister: dict) -> bool:
    return kind_of(sister) == "team"


def is_active(sister: dict) -> bool:
    """Whether the sister is in the active roster; status is read in any case, as kind is."""
    return str(sister.get("status", "active")).strip().lower() == "active"


def workspace_root(cfg: dict) -> Path | None:
    """workspace_root with `~` expanded, or None when it is absent or not a string. Raises
    ConfigInvalid for a `~user` that names nobody on this machine, or a relative path, which
    would resolve against whatever folder a script runs in."""
    root = cfg.get("workspace_root")
    if not isinstance(root, str) or not root:
        return None
    try:
        path = Path(root).expanduser()
    except RuntimeError as exc:  # Path.expanduser on an unknown ~user
        raise ConfigInvalid(f"workspace_root {root!r} names no home folder here") from exc
    if not path.is_absolute():
        raise ConfigInvalid(f"workspace_root {root!r} must be absolute or start with ~")
    return path


def github_user(cfg: dict) -> str | None:
    user = cfg.get("github_user")
    return user if isinstance(user, str) and user else None


def checkout(cfg: dict, sister: dict) -> Path | None:
    """Where the roster says this sister's checkout is: workspace_root/<name>."""
    root = workspace_root(cfg)
    return root / sister["name"] if root else None


def matches(cfg: dict, sister: dict, checkouts: set[Path], slug: tuple[str, str] | None) -> bool:
    """Whether a repo is this sister: one of its CHECKOUTS (resolved here) is workspace_root/<name>,
    or its GitHub SLUG is <github_user>/<name> (another clone), case-insensitive."""
    path = checkout(cfg, sister)
    if path is not None and path.resolve() in {p.resolve() for p in checkouts}:
        return True
    me = github_user(cfg)
    return bool(
        slug and me and slug[0].lower() == me.lower() and slug[1].lower() == sister["name"].lower()
    )
