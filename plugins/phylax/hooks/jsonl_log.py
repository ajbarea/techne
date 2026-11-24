"""Append one JSON line to a local log under a size cap, shared by the phylax hooks' logs.

Runs on the system python3, so it stays compatible with 3.9 (macOS's).
"""

from __future__ import annotations

import json
import os
import time

LOG_MAX = 256 * 1024


def append(path: str, row: dict, max_bytes: int = LOG_MAX) -> None:
    """Append ROW with a `ts` field to PATH (mode 0600). A file past MAX_BYTES first moves
    to PATH with `.1` before its suffix. A log that cannot be written is skipped silently."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            if os.stat(path).st_size > max_bytes:
                os.replace(path, os.path.splitext(path)[0] + ".jsonl.1")
        except FileNotFoundError:
            pass  # no log yet, or another agent rotated it first
        line = json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **row})
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, (line + "\n").encode())  # one write: concurrent appends never interleave
        finally:
            os.close(fd)
    except OSError:
        pass
