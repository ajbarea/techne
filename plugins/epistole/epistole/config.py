"""Where epistole keeps its files, and the accounts.toml that names each account."""

from __future__ import annotations

import json
import os
import re
import tempfile
import tomllib
from pathlib import Path
from typing import NamedTuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

RESERVED = {"all"}
ALIAS_RE = re.compile(r"^[A-Za-z0-9_-]+$")
DEFAULT_ATTACH: list[str] = []
DEFAULT_DOWNLOAD = "~/Downloads/epistole"
KEYS = {"attach_dirs", "download_dir", "accounts", "timezone"}
MANAGED = (
    "# Managed by epistole-login: it rewrites this file when an account is added, "
    "and comments are not kept."
)


class ConfigError(Exception):
    pass


class Account(NamedTuple):
    alias: str
    address: str


class Config(NamedTuple):
    accounts: dict[str, Account]
    attach_dirs: tuple[Path, ...]
    download_dir: Path
    timezone: str | None = None


def caller_dir() -> Path:
    """The directory the user ran epistole-login from (the wrapper changes its own)."""
    return Path(os.environ.get("EPISTOLE_CWD") or Path.cwd())


def home() -> Path:
    """The epistole home: EPISTOLE_HOME, which must be absolute or start with ~."""
    env = os.environ.get("EPISTOLE_HOME")
    if not env:
        return Path.home() / ".config" / "epistole"
    try:
        path = Path(env).expanduser()
    except RuntimeError:
        raise ConfigError(f"EPISTOLE_HOME has an unknown user in {env!r}.") from None
    if not path.is_absolute():
        raise ConfigError(
            f"EPISTOLE_HOME must be an absolute path or start with ~, not {env!r}; "
            "the server and epistole-login run from different folders."
        )
    return path


def client_secret_path(base: Path) -> Path:
    return base / "client_secret.json"


def next_login_command(base: Path) -> str:
    """The command that moves a user forward: import the client first if there is none."""
    if client_secret_path(base).is_file():
        return "`!epistole-login <alias>`"
    return "`!epistole-login --client <downloaded.json> <alias>`"


def _no_accounts(base: Path) -> str:
    return (
        f"No accounts yet. Run {next_login_command(base)} for the first account, then "
        "`!epistole-login <alias>` for each other one (see /epistole:setup)."
    )


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


def _check_absolute(key: str, value: str) -> None:
    try:
        absolute = Path(value).expanduser().is_absolute()
    except RuntimeError:
        raise ConfigError(f"{key} in accounts.toml has an unknown user in {value!r}.") from None
    if not absolute:
        raise ConfigError(
            f"{key} in accounts.toml must be an absolute path or start with ~, not {value!r}."
        )


def _check_zone(value: object) -> None:
    """timezone must be an IANA name such as America/New_York."""
    if isinstance(value, str) and value and ".." not in value and not value.startswith("/"):
        try:
            ZoneInfo(value)
            return
        except (ZoneInfoNotFoundError, ValueError):
            pass
    raise ConfigError(
        f"timezone in accounts.toml must be an IANA zone name such as "
        f'"America/New_York", not {value!r}.'
    )


def _read(base: Path) -> dict:
    file = base / "accounts.toml"
    try:
        data = tomllib.loads(file.read_text())
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{file} is not valid TOML: {exc}") from None
    unknown = sorted(set(data) - KEYS)
    if unknown:
        raise ConfigError(
            f"accounts.toml has an unknown key {unknown[0]!r}; allowed: {sorted(KEYS)}."
        )
    attach = data.get("attach_dirs", DEFAULT_ATTACH)
    if not isinstance(attach, list) or not all(isinstance(p, str) for p in attach):
        raise ConfigError("attach_dirs in accounts.toml must be a list of folder paths.")
    if not isinstance(data.get("download_dir", DEFAULT_DOWNLOAD), str):
        raise ConfigError("download_dir in accounts.toml must be one folder path.")
    for value in attach:
        _check_absolute("attach_dirs", value)
    _check_absolute("download_dir", data.get("download_dir", DEFAULT_DOWNLOAD))
    if "timezone" in data:
        _check_zone(data["timezone"])
    table = data.get("accounts", {})
    if not isinstance(table, dict) or not all(
        isinstance(v, str) and "@" in v for v in table.values()
    ):
        raise ConfigError(
            f"the [accounts] table in {file} must map each alias to an address, "
            'e.g. school = "user@example.edu".'
        )
    return data


def load(base: Path | None = None, *, allow_empty: bool = False) -> Config:
    base = base or home()
    if not (base / "accounts.toml").is_file():
        raise ConfigError(_no_accounts(base))
    data = _read(base)
    raw = data.get("accounts") or {}
    if not raw and not allow_empty:
        raise ConfigError(_no_accounts(base))
    for alias in sorted(raw, key=lambda a: a not in RESERVED):
        check_alias(alias)
    accounts = {alias: Account(alias, str(addr).lower()) for alias, addr in raw.items()}
    attach = tuple(_path(p) for p in data.get("attach_dirs", DEFAULT_ATTACH))
    download = _path(data.get("download_dir", DEFAULT_DOWNLOAD))
    return Config(accounts, attach, download, data.get("timezone"))


def _q(value: str) -> str:
    """A TOML basic string. JSON escapes every control character TOML forbids except DEL."""
    return json.dumps(value, ensure_ascii=False).replace("\x7f", "\\u007f")


def add_account(base: Path, alias: str, address: str) -> None:
    """Record alias = address in accounts.toml, keeping every existing account and path.

    The file has a fixed shape, so it is regenerated whole. Paths keep the spelling the user
    wrote (a leading ~ stays), read from the raw file after load() has validated it.
    """
    check_alias(alias)
    file = base / "accounts.toml"
    data: dict = {}
    if file.is_file():
        load(base, allow_empty=True)
        data = _read(base)
    accounts = {k: str(v) for k, v in (data.get("accounts") or {}).items()}
    if alias in accounts:
        raise ConfigError(f"alias {alias!r} is already in accounts.toml.")
    accounts[alias] = address.lower()
    attach = [str(p) for p in data.get("attach_dirs", DEFAULT_ATTACH)]
    lines = [
        MANAGED,
        f"attach_dirs = [{', '.join(_q(p) for p in attach)}]",
        f"download_dir = {_q(str(data.get('download_dir', DEFAULT_DOWNLOAD)))}",
        *([f"timezone = {_q(data['timezone'])}"] if "timezone" in data else []),
        "",
        "[accounts]",
        *(f"{a} = {_q(addr)}" for a, addr in accounts.items()),
    ]
    write_private(file, "\n".join(lines) + "\n")
