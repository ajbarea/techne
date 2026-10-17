#!/usr/bin/env python3
"""SessionStart and SessionEnd hook: hand the saved search keys to Bash commands.

Usage: session_keys.py start | end

Claude Code gives a hook every plugin option as CLAUDE_PLUGIN_OPTION_<NAME>, but Bash-tool
commands never see them. CLAUDE_ENV_FILE reaches every Bash command in the session, subagents
included, but Claude Code leaves those files on disk at mode 0644 and never deletes them, so no
value goes in one. `start` writes the values to a private (0600) file in the plugin's data folder
and appends only a line that sources it to CLAUDE_ENV_FILE; `end` deletes that file. A variable
already set in the Bash environment wins. Prints nothing and always exits 0; a value is never
echoed. Standard library only, Python 3.9 or newer.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
import time
from collections.abc import Mapping

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from search_keys import KEYS  # noqa: E402

SUBDIR = "session-keys"
# A live session rewrites its file on every resume, clear and compact SessionStart, so only the
# files of crashed sessions, which never ran SessionEnd, get this old.
MAX_AGE_SECONDS = 7 * 24 * 60 * 60
SAFE_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")


def session_id(raw: str) -> str | None:
    """The id from the hook's stdin JSON, or None unless it is safe to use in a file name."""
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    sid = data.get("session_id") if isinstance(data, dict) else None
    return sid if isinstance(sid, str) and SAFE_ID.fullmatch(sid) else None


def export_lines(environ: Mapping[str, str]) -> list[str]:
    """One line per saved key. A variable already set in the Bash environment is kept."""
    lines = []
    for key in KEYS:
        value = environ.get(f"CLAUDE_PLUGIN_OPTION_{key.option.upper()}", "")
        if not value or "\n" in value or "\r" in value or "\0" in value:
            continue
        lines.append(f'[ -n "${{{key.env}-}}" ] || export {key.env}={shlex.quote(value)}\n')
    return lines


def private_dir(data_dir: str) -> str:
    path = os.path.join(data_dir, SUBDIR)
    os.makedirs(path, mode=0o700, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def prune(directory: str, now: float) -> None:
    for name in os.listdir(directory):
        path = os.path.join(directory, name)
        try:
            if os.path.isfile(path) and now - os.path.getmtime(path) > MAX_AGE_SECONDS:
                os.remove(path)
        except OSError:
            pass


def remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def write_private(path: str, text: str) -> None:
    """Create the file at mode 0600 under a temp name, then move it into place."""
    temp = f"{path}.{os.getpid()}.tmp"
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(text)
        os.replace(temp, path)
    except BaseException:
        remove(temp)
        raise


def start(sid: str, directory: str, environ: Mapping[str, str]) -> None:
    prune(directory, time.time())
    path = os.path.join(directory, f"{sid}.sh")
    lines = export_lines(environ)
    target = environ.get("CLAUDE_ENV_FILE")
    if not lines or not target:
        remove(path)
        return
    write_private(path, "".join(lines))
    quoted = shlex.quote(path)
    with open(target, "a", encoding="utf-8") as out:
        out.write(f"if [ -f {quoted} ]; then . {quoted}; fi\n")


def main(argv: list[str], stdin_text: str, environ: Mapping[str, str]) -> int:
    mode = argv[1] if len(argv) > 1 else ""
    data_dir = environ.get("CLAUDE_PLUGIN_DATA")
    sid = session_id(stdin_text)
    if mode not in ("start", "end") or not data_dir or sid is None:
        return 0
    try:
        directory = private_dir(data_dir)
        if mode == "start":
            start(sid, directory, environ)
        else:
            remove(os.path.join(directory, f"{sid}.sh"))
    except (OSError, ValueError):
        pass  # a hook never blocks a session
    return 0


if __name__ == "__main__":
    try:
        text = sys.stdin.read()
    except (OSError, ValueError):
        text = ""
    sys.exit(main(sys.argv, text, os.environ))
