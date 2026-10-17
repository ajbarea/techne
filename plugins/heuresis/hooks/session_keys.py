#!/usr/bin/env python3
"""SessionStart and SessionEnd hook: hand the saved search keys to Bash commands.

Usage: session_keys.py start | end

Claude Code gives a hook every plugin option as CLAUDE_PLUGIN_OPTION_<NAME>, but Bash-tool
commands never see them. CLAUDE_ENV_FILE reaches every Bash command in the session, subagents
included, but Claude Code leaves those files on disk at mode 0644 and never deletes them, so no
value goes in one. `start` writes the values to a private (0600) file in the plugin's data folder
and appends only a line that sources it to CLAUDE_ENV_FILE; `end` deletes that file. A variable
already set in the Bash environment wins. Prints nothing and always exits 0; a value is never
echoed.

The file is `<session_id>.<owner_pid>.sh`, where the owner is the hook's parent: hooks.json runs
the script with `exec`, so that parent is the Claude Code process that ran the hook command. One
conversation can be open in two processes, so a session id alone is not a safe name. `end`
deletes only its own process's file. `start` prunes files whose owner process is gone; a session
that idles for days keeps its file. Standard library only, Python 3.9 or newer.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shlex
import stat
import sys
import time
from collections.abc import Mapping

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from search_keys import KEYS  # noqa: E402

SUBDIR = "session-keys"
# Windows cannot probe a pid without os.kill, which there terminates the process, so a file whose
# owner cannot be probed (Windows, or a name that does not parse) is pruned by age instead. A
# session that idles longer than this and is still open loses its keys until its next start.
MAX_AGE_SECONDS = 30 * 24 * 60 * 60
SAFE_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
FILE_NAME = re.compile(r"(?P<sid>[A-Za-z0-9_-]{1,128})\.(?P<pid>[0-9]{1,10})\.sh")


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


def pid_alive(pid: int) -> bool:
    """Whether a process with this pid exists. POSIX only: on Windows os.kill terminates it."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, OverflowError):
        return False
    except OSError:  # PermissionError: it exists but belongs to another user
        return True
    return True


def stale(name: str, path: str, now: float) -> bool:
    match = FILE_NAME.fullmatch(name)
    if match and os.name != "nt":
        return not pid_alive(int(match.group("pid")))
    return now - os.lstat(path).st_mtime > MAX_AGE_SECONDS


def prune(directory: str, now: float) -> None:
    for name in os.listdir(directory):
        path = os.path.join(directory, name)
        try:
            if not stat.S_ISDIR(os.lstat(path).st_mode) and stale(name, path, now):
                os.remove(path)
        except OSError:
            pass


def remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def write_private(path: str, text: str) -> None:
    """Create the file at mode 0600 under a fresh temp name, then move it into place.

    The temp name is created exclusively and never through a symlink; if it exists the write
    fails, and the hook exits 0 without a file.
    """
    temp = f"{path}.{secrets.token_hex(8)}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(temp, flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(text)
        os.replace(temp, path)
    except BaseException:
        remove(temp)
        raise


def has_line(target: str, line: str) -> bool:
    try:
        with open(target, encoding="utf-8", errors="replace") as src:
            return line in src.read().splitlines()
    except FileNotFoundError:
        return False


def file_name(sid: str) -> str:
    return f"{sid}.{os.getppid()}.sh"


def start(sid: str, directory: str, environ: Mapping[str, str]) -> None:
    prune(directory, time.time())
    path = os.path.join(directory, file_name(sid))
    lines = export_lines(environ)
    target = environ.get("CLAUDE_ENV_FILE")
    if not lines or not target:
        remove(path)
        return
    write_private(path, "".join(lines))
    quoted = shlex.quote(path)
    source = f"if [ -f {quoted} ]; then . {quoted}; fi"
    if not has_line(target, source):
        with open(target, "a", encoding="utf-8") as out:
            out.write(source + "\n")


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
            remove(os.path.join(directory, file_name(sid)))
    except (OSError, ValueError):
        pass  # a hook never blocks a session
    return 0


if __name__ == "__main__":
    try:
        text = sys.stdin.read()
    except (OSError, ValueError):
        text = ""
    sys.exit(main(sys.argv, text, os.environ))
