#!/usr/bin/env python3
"""SessionStart hook: export the search keys saved with /plugin configure to Bash commands.

Claude Code gives a hook every plugin option as CLAUDE_PLUGIN_OPTION_<NAME>, but Bash-tool
commands never see them. A line appended to CLAUDE_ENV_FILE reaches every later Bash command
in the session, subagents included. A key already set in the environment is left alone, so one
exported in the shell profile wins. Prints nothing and always exits 0; a value is never echoed.
"""

from __future__ import annotations

import os
import shlex
import sys
from collections.abc import Mapping

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from search_keys import KEYS  # noqa: E402


def export_lines(environ: Mapping[str, str]) -> list[str]:
    lines = []
    for key in KEYS:
        value = environ.get(f"CLAUDE_PLUGIN_OPTION_{key.option.upper()}", "")
        if not value or environ.get(key.env) or "\n" in value or "\r" in value or "\0" in value:
            continue
        lines.append(f"export {key.env}={shlex.quote(value)}\n")
    return lines


def main() -> int:
    target = os.environ.get("CLAUDE_ENV_FILE")
    lines = export_lines(os.environ) if target else []
    if target and lines:
        try:
            with open(target, "a", encoding="utf-8") as out:
                out.writelines(lines)
        except OSError:
            pass  # a hook never blocks a session
    return 0


if __name__ == "__main__":
    sys.exit(main())
