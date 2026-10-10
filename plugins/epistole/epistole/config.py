"""Where epistole keeps its files, and the accounts.toml that names each account."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import NamedTuple

RESERVED = {"all"}


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
    bad = RESERVED & raw.keys()
    if bad:
        raise ConfigError(f"alias {sorted(bad)[0]!r} is reserved; pick another name.")
    accounts = {alias: Account(alias, str(addr).lower()) for alias, addr in raw.items()}
    attach = tuple(_path(p) for p in data.get("attach_dirs", ["~/Downloads"]))
    download = _path(data.get("download_dir", "~/Downloads/epistole"))
    return Config(accounts, attach, download)
