"""Append-only log of drafts and sends: metadata only, never message bodies."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

KEYS = ("account", "id", "to", "cc", "subject", "attachments")


def _clean(value: object) -> object:
    if isinstance(value, str):
        return value.replace("\r", " ").replace("\n", " ")
    if isinstance(value, list | tuple):
        return [_clean(v) for v in value]
    return value


def record(base: Path, event: str, **fields: object) -> None:
    """Append one entry; a log failure never fails the caller's operation."""
    entry = {"time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "event": _clean(event)}
    entry.update({k: _clean(fields[k]) for k in KEYS if k in fields})
    try:
        base.mkdir(parents=True, exist_ok=True)
        path = base / "audit.jsonl"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a") as fh:
            fh.write(json.dumps(entry) + "\n")
        path.chmod(0o600)
    except OSError:
        return
