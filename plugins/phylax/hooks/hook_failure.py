"""The refusal a guard prints when it crashes, so a session is never stuck behind a broken one.

hooks.json sets onFailure "block" on every refusing PreToolUse hook, so a crash refuses the
call. Claude Code's own text for that names no guard and no way out; the message here names
the guard, the error and the phylax option that switches it off.

Runs on the system python3, so it stays compatible with 3.9 (macOS's).
"""

from __future__ import annotations

import sys
from collections.abc import Callable


def message(guard: str, options: str, error: BaseException) -> str:
    return (
        f"phylax {guard} failed ({type(error).__name__}: {error}); the call was not run. "
        f"To switch it off, turn off the phylax option {options} in /config, "
        "or run /phylax:setup."
    )


def run(main: Callable[[], int], guard: str, options: str) -> None:
    """Exit with MAIN's code; an exception it raises prints `message` and exits 2."""
    try:
        code = main()
    except Exception as exc:
        print(message(guard, options, exc), file=sys.stderr)
        code = 2
    sys.exit(code)
