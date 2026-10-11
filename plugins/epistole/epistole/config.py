"""Where epistole keeps its files, and the accounts.toml that names each account."""

from __future__ import annotations

import json
import os
import re
import tempfile
import tomllib
from pathlib import Path
from typing import NamedTuple

RESERVED = {"all"}
ALIAS_RE = re.compile(r"^[A-Za-z0-9_-]+$")
DEFAULT_ATTACH = ["~/Downloads"]
DEFAULT_DOWNLOAD = "~/Downloads/epistole"


class ConfigError(Exception):
    pass


class Account(NamedTuple):
    alias: str
    address: str


class Config(NamedTuple):
    accounts: dict[str, Account]
    attach_dirs: tuple[Path, ...]
    download_dir: Path


def home() -> Path:
    env = os.environ.get("EPISTOLE_HOME")
    return Path(env) if env else Path.home() / ".config" / "epistole"


def write_private(path: Path, data: str) -> None:
    """Write data atomically at 0600 into a 0700 directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        os.chmod(tmp, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def check_alias(alias: str) -> None:
    if alias in RESERVED:
        raise ConfigError(f"alias {alias!r} is reserved; pick another name.")
    if not ALIAS_RE.fullmatch(alias):
        raise ConfigError(f"alias {alias!r} is invalid; use only letters, digits, '_' and '-'.")


def _path(value: str) -> Path:
    return Path(value).expanduser().resolve()


def load(base: Path | None = None) -> Config:
    base = base or home()
    file = base / "accounts.toml"
    if not file.is_file():
        raise ConfigError(
            f"{file} not found. Create it with an [accounts] table mapping an alias to an "
            'address, e.g. personal = "user@example.com"; see the plugin README.'
        )
    data = tomllib.loads(file.read_text())
    raw = data.get("accounts") or {}
    if not raw:
        raise ConfigError(f"{file} has no [accounts] entries.")
    for alias in sorted(raw, key=lambda a: a not in RESERVED):
        check_alias(alias)
    accounts = {alias: Account(alias, str(addr).lower()) for alias, addr in raw.items()}
    attach = tuple(_path(p) for p in data.get("attach_dirs", DEFAULT_ATTACH))
    download = _path(data.get("download_dir", DEFAULT_DOWNLOAD))
    return Config(accounts, attach, download)


def _q(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def add_account(base: Path, alias: str, address: str) -> None:
    """Record alias = address in accounts.toml, keeping every existing account and path.

    The file has a fixed shape, so it is regenerated whole. Paths keep the spelling the user
    wrote (a leading ~ stays), read from the raw file after load() has validated it.
    """
    check_alias(alias)
    file = base / "accounts.toml"
    data: dict = {}
    if file.is_file():
        load(base)
        data = tomllib.loads(file.read_text())
    accounts = {k: str(v) for k, v in (data.get("accounts") or {}).items()}
    if alias in accounts:
        raise ConfigError(f"alias {alias!r} is already in accounts.toml.")
    accounts[alias] = address.lower()
    attach = [str(p) for p in data.get("attach_dirs", DEFAULT_ATTACH)]
    lines = [
        f"attach_dirs = [{', '.join(_q(p) for p in attach)}]",
        f"download_dir = {_q(str(data.get('download_dir', DEFAULT_DOWNLOAD)))}",
        "",
        "[accounts]",
        *(f"{a} = {_q(addr)}" for a, addr in accounts.items()),
    ]
    write_private(file, "\n".join(lines) + "\n")
