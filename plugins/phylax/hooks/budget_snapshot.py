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
login) leaves the file as it was. Nothing here may break the status line, so every error
is dropped. Runs on the system python3, so it stays compatible with 3.9 (macOS's).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time

STATE_NAME = "phylax-budget.json"


def default_path() -> str:
    config = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    return os.path.join(config, STATE_NAME)


def save(raw: bytes, path: str) -> None:
    data = json.loads(raw)
    limits = data.get("rate_limits") if isinstance(data, dict) else None
    if not isinstance(limits, dict) or not limits:
        return
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".phylax-budget-", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"rate_limits": limits, "written_at": time.time()}, f)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


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
