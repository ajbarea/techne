"""Where schole keeps its files: schole.toml (site, term, timezone) and the browser profile."""

from __future__ import annotations

import os
import tempfile
import tomllib
from datetime import datetime, tzinfo
from pathlib import Path
from typing import NamedTuple
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

KEYS = {"site", "term", "timezone"}


class ConfigError(Exception):
    pass


class Config(NamedTuple):
    site: str
    term: str
    timezone: str | None


def home() -> Path:
    """SCHOLE_HOME (absolute or ~), else ~/.config/schole."""
    env = os.environ.get("SCHOLE_HOME")
    if not env:
        return Path.home() / ".config" / "schole"
    path = Path(env).expanduser()
    if not path.is_absolute():
        raise ConfigError(f"SCHOLE_HOME must be absolute or start with ~, not {env!r}.")
    return path


def profile(base: Path) -> Path:
    """The browser profile holding the site's sign-in. Private: it is the session."""
    path = base / "profile"
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(base, 0o700)
    os.chmod(path, 0o700)
    return path


def check_site(site: str) -> str:
    parts = urlsplit(site.strip())
    if parts.scheme != "https" or not parts.hostname or parts.path not in ("", "/"):
        raise ConfigError(
            f"site must be the course site's https origin, like https://mycourses.example.edu, "
            f"not {site!r}."
        )
    return f"https://{parts.netloc}"


def check_zone(name: object) -> str:
    if isinstance(name, str) and name and ".." not in name and not name.startswith("/"):
        try:
            ZoneInfo(name)
            return name
        except (ZoneInfoNotFoundError, ValueError):
            pass
    raise ConfigError(
        f'timezone must be an IANA zone name such as "America/New_York", not {name!r}.'
    )


def load(base: Path) -> Config:
    file = base / "schole.toml"
    if not file.is_file():
        raise ConfigError(
            f"no {file}. Set the site up first: schole-login --site https://<your course site> "
            "--term <term code>."
        )
    try:
        data = tomllib.loads(file.read_text())
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise ConfigError(f"{file} is not valid TOML: {exc}") from None
    unknown = sorted(set(data) - KEYS)
    if unknown:
        raise ConfigError(
            f"schole.toml has an unknown key {unknown[0]!r}; allowed: {sorted(KEYS)}."
        )
    site = check_site(str(data.get("site") or ""))
    term = data.get("term", "")
    if not isinstance(term, str):
        raise ConfigError('term in schole.toml must be a string, such as "2261".')
    zone = check_zone(data["timezone"]) if "timezone" in data else None
    return Config(site, term, zone)


def _q(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def save(base: Path, cfg: Config) -> None:
    base.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Written by schole-login; edit freely.",
        f"site = {_q(cfg.site)}",
        f"term = {_q(cfg.term)}",
        *([f"timezone = {_q(cfg.timezone)}"] if cfg.timezone else []),
    ]
    write_private(base / "schole.toml", "\n".join(lines) + "\n")


def write_private(path: Path, data: str) -> None:
    """Write data atomically at 0600 (mkstemp's mode), through a symlink to its target; an
    interrupted write leaves no partial file."""
    path = Path(os.path.realpath(path))
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def zone(cfg: Config | None) -> tzinfo:
    if cfg and cfg.timezone:
        return ZoneInfo(cfg.timezone)
    for name in (os.environ.get("TZ", "").lstrip(":"), _etc_zone()):
        if name and not name.startswith("/") and ".." not in name:
            try:
                return ZoneInfo(name)
            except (ZoneInfoNotFoundError, ValueError):
                continue
    local = datetime.now().astimezone().tzinfo
    assert local is not None
    return local


def _etc_zone() -> str:
    try:
        return Path("/etc/timezone").read_text().strip()
    except OSError:
        pass
    try:
        target = str(Path("/etc/localtime").resolve())
    except (OSError, RuntimeError):
        return ""
    return target.split("/zoneinfo/", 1)[1] if "/zoneinfo/" in target else ""
