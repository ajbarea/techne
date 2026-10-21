"""~/.claude/techne.toml: the one reader and roster rules every techne script shares.

load() returns the parsed table, or None when there is no file, and raises a ConfigError when a
file is there but cannot be used. Each caller decides what that means: the sisters audit exits
with the message, the board hook does nothing, repo_kind reads the repo as team. Imports on
python3 3.9; parsing needs tomllib (3.11), and below it load() raises NeedsTomllib.
"""

from __future__ import annotations

import sys
from pathlib import Path


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


def load(path: Path | None = None) -> dict | None:
    """The parsed techne.toml, or None when there is no file. A broken link is unreadable, not
    absent: the roster it points at may hold a team entry."""
    path = path or techne_toml()
    try:
        path.stat()
    except (FileNotFoundError, NotADirectoryError):
        if path.is_symlink():
            raise ConfigUnreadable(f"cannot read {path}: a link to a missing file") from None
        return None
    except OSError as exc:
        raise ConfigUnreadable(f"cannot read {path}: {exc.strerror or exc}") from exc
    try:
        import tomllib
    except ImportError as exc:  # python3 below 3.11, as on stock macOS
        raise NeedsTomllib(f"python3 {sys.version.split()[0]} cannot read {path}") from exc
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except OSError as exc:
        raise ConfigUnreadable(f"cannot read {path}: {exc.strerror or exc}") from exc
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
        if not isinstance(sister.get("name"), str) or not sister["name"]:
            raise ConfigInvalid(f"[[sisters]] entry {number} in {where} has no name")
    return roster


def kind_of(sister: dict) -> str:
    """A [[sisters]] entry's kind, lowercased: "team", "solo" or ""."""
    return str(sister.get("kind", "")).strip().lower()


def is_team(sister: dict) -> bool:
    return kind_of(sister) == "team"


def is_active(sister: dict) -> bool:
    return sister.get("status", "active") == "active"


def workspace_root(cfg: dict) -> Path | None:
    """workspace_root with `~` expanded, or None when it is absent or not a string."""
    root = cfg.get("workspace_root")
    return Path(root).expanduser() if isinstance(root, str) and root else None


def github_user(cfg: dict) -> str | None:
    user = cfg.get("github_user")
    return user if isinstance(user, str) and user else None


def checkout(cfg: dict, sister: dict) -> Path | None:
    """Where the roster says this sister's checkout is: workspace_root/<name>."""
    root = workspace_root(cfg)
    return root / sister["name"] if root else None


def matches(cfg: dict, sister: dict, checkouts: set[Path], slug: tuple[str, str] | None) -> bool:
    """Whether a repo is this sister: one of its CHECKOUTS (resolved) is workspace_root/<name>,
    or its GitHub SLUG is <github_user>/<name> (another clone), case-insensitive."""
    path = checkout(cfg, sister)
    if path is not None and path.resolve() in {p.resolve() for p in checkouts}:
        return True
    me = github_user(cfg)
    return bool(
        slug and me and slug[0].lower() == me.lower() and slug[1].lower() == sister["name"].lower()
    )
