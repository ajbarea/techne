"""The catch-me-up window: when the last sweep read the inboxes, kept in the epistole home."""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from epistole import config

FILE = "catch-me-up.json"
FUTURE_SLACK = 300  # seconds of clock skew allowed in a recorded time
OVERLAP = 600  # seconds re-read before the last run, for mail Gmail indexed late
MAX_AGE = 366 * 86400  # a --set older than this is refused as a typo


def _system_zone() -> tzinfo:
    """The machine's IANA zone (TZ, /etc/timezone, /etc/localtime), else its fixed offset."""
    names = [os.environ.get("TZ", "").lstrip(":")]
    try:
        names.append(Path("/etc/timezone").read_text().strip())
    except OSError:
        pass
    try:
        target = str(Path("/etc/localtime").resolve())
        if "/zoneinfo/" in target:
            names.append(target.split("/zoneinfo/", 1)[1])
    except (OSError, RuntimeError):
        pass
    for name in names:
        if name and not name.startswith("/") and ".." not in name:
            try:
                return ZoneInfo(name)
            except (ZoneInfoNotFoundError, ValueError):
                continue
    local = datetime.now().astimezone().tzinfo
    assert local is not None
    return local


def zone(base: Path) -> tzinfo:
    """The timezone in accounts.toml, else the machine's zone."""
    try:
        name = config.load(base, allow_empty=True).timezone
    except (config.ConfigError, ValueError, OSError):
        name = None
    return ZoneInfo(name) if name else _system_zone()


def read(base: Path, now: float | None = None) -> int | None:
    """The recorded last run as epoch seconds; None when missing, unreadable or implausible."""
    now = time.time() if now is None else now
    try:
        value = json.loads((base / FILE).read_text())["last_run"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        return None
    return value if 0 < value <= now + FUTURE_SLACK else None


def write(base: Path, epoch: int, now: float | None = None) -> None:
    now = time.time() if now is None else now
    if epoch > now + FUTURE_SLACK:
        raise ValueError("refusing a last-run time in the future.")
    if epoch < now - MAX_AGE:
        raise ValueError("refusing a last-run time more than a year ago; pass the now epoch.")
    base.mkdir(parents=True, exist_ok=True)
    config.write_private(base / FILE, json.dumps({"last_run": epoch}) + "\n")


def default_start(now: datetime) -> datetime:
    """With no record: since the start of yesterday, or since Friday on a Monday."""
    days = 3 if now.weekday() == 0 else 1
    return (now - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)


def fmt(moment: datetime) -> str:
    return moment.strftime("%a %b %d %Y %H:%M %Z")


def window(base: Path, now: float | None = None) -> str:
    now = time.time() if now is None else now
    tz = zone(base)
    current = datetime.fromtimestamp(now, tz)
    last = read(base, now)
    if last is None:
        start, source = default_start(current), "no record; default window"
        query = int(start.timestamp())
    else:
        start, source = datetime.fromtimestamp(last, tz), "last run"
        query = last - OVERLAP
    return (
        f"window start: {fmt(start)} ({source})\n"
        f"now: {fmt(current)} (epoch {int(now)})\n"
        f"gmail query: after:{query}\n"
    )


USAGE = (
    "usage: epistole-since              print the catch-me-up window\n"
    "       epistole-since --set EPOCH  record when this sweep read the inboxes\n"
)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    try:
        base = config.home()
        if not args:
            sys.stdout.write(window(base))
            return 0
        if len(args) == 2 and args[0] == "--set" and args[1].isascii() and args[1].isdigit():
            epoch = int(args[1])
            write(base, epoch)
            moment = datetime.fromtimestamp(epoch, zone(base))
            sys.stdout.write(f"recorded last run: {fmt(moment)}\n")
            return 0
    except (config.ConfigError, ValueError, OSError) as exc:
        sys.stderr.write(f"epistole-since: {exc}\n")
        return 1
    sys.stderr.write(USAGE)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
