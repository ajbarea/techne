#!/usr/bin/env python3
"""Save the statusLine's rate_limits for phylax budget mode, passing stdin through unchanged.

Claude Code hands `rate_limits` (the 5-hour and 7-day windows' used_percentage and
resets_at) only to the statusLine command, never to hooks. Chain this in front of the
status line so budget.py can read them:

    "statusLine": {"type": "command",
                   "command": "python3 <copy>/budget_snapshot.py | <your status line command>"}

The budget_mode SessionStart hook keeps <copy> current at ${CLAUDE_PLUGIN_DATA}, a path that
survives plugin updates; /phylax:setup prints the exact line. The file written is the
optional path argument, else ${CLAUDE_CONFIG_DIR:-~/.claude}/phylax-budget.json, one per
account. A payload without rate_limits (before the session's first response, or an API-key
login) leaves the file as it was. Every session's status line writes the one file, and an
idle session re-renders with the usage of its last response, so each window keeps the newest
reading: the later resets_at, and for the same resets_at the higher used_percentage. Nothing
here may break the status line, so every error is dropped. Runs on the system python3, so it
stays compatible with 3.9 (macOS's).
"""

from __future__ import annotations

import json
import math
import os
import stat
import sys
import tempfile
import time

STATE_NAME = "phylax-budget.json"
# Seconds an unchanged reading stays on disk unrewritten.
REWRITE_AFTER = 300


def default_path(environ=os.environ) -> str:
    """The snapshot file of the account whose Claude config folder this environment names."""
    home = os.path.expanduser("~")
    config = environ.get("CLAUDE_CONFIG_DIR") or os.path.join(home, ".claude")
    return os.path.join(config, STATE_NAME)


def write_atomic(path: str, data: bytes) -> None:
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".phylax-", dir=folder)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


def previous(path: str) -> tuple:
    """(rate_limits, mtime) of the file as it stands; ({}, 0.0) for a missing, unreadable or
    non-regular one (a FIFO would block the status line)."""
    try:
        info = os.stat(path)
        if not stat.S_ISREG(info.st_mode):
            return {}, 0.0
        with open(path, "rb") as f:
            limits = json.loads(f.read(65536)).get("rate_limits")
    except (OSError, ValueError, AttributeError, RecursionError):
        return {}, 0.0
    return (limits, info.st_mtime) if isinstance(limits, dict) else ({}, 0.0)


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return float(value) if math.isfinite(value) else None
    except OverflowError:
        return None


def newer(old, new) -> bool:
    """Whether window reading NEW replaces OLD: a later reset, or the same one used more."""
    if not isinstance(old, dict):
        return True
    if not isinstance(new, dict):
        return False
    old_reset, new_reset = number(old.get("resets_at")), number(new.get("resets_at"))
    if old_reset is None or new_reset is None or old_reset != new_reset:
        return new_reset is not None and (old_reset is None or new_reset > old_reset)
    old_used, new_used = number(old.get("used_percentage")), number(new.get("used_percentage"))
    return old_used is None or (new_used is not None and new_used >= old_used)


def save(raw: bytes, path: str) -> None:
    data = json.loads(raw)
    limits = data.get("rate_limits") if isinstance(data, dict) else None
    if not isinstance(limits, dict) or not limits:
        return
    now = time.time()
    old, written = previous(path)
    merged = dict(old)
    merged.update((name, win) for name, win in limits.items() if newer(old.get(name), win))
    # A re-render repeats the last response: an unchanged reading this recent is left alone.
    if merged == old and now - written < REWRITE_AFTER:
        return
    write_atomic(path, json.dumps({"rate_limits": merged, "written_at": now}).encode())


def main(argv: list) -> int:
    raw = sys.stdin.buffer.read()
    try:
        sys.stdout.buffer.write(raw)
        sys.stdout.flush()
    except OSError:
        pass
    try:
        save(raw, os.path.expanduser(argv[0]) if argv else default_path())
    except Exception:  # the status line must render whatever happens here
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
