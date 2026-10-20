#!/usr/bin/env python3
"""PostToolUse hook (Bash): put each issue or PR a command just opened on the techne board.

When the command ran `gh issue create`, `gh pr create` or a `gh api` POST to .../issues or
.../pulls, it adds every issue or PR URL in the output whose repo the board's owner owns, and
sets its Status to Issue or In PR. Without a [board] table in ~/.claude/techne.toml it does
nothing. Never blocks the tool call: a failure becomes one line of additionalContext, success
prints nothing. Runs on python3 3.9.
"""

from __future__ import annotations

import json
import os
import sys

sys.dont_write_bytecode = True  # the plugin cache stays as installed
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "_shared"))
import project_board as pb  # noqa: E402  # ty: ignore[unresolved-import]

BUDGET_SECONDS = 8.0  # hooks.json gives the hook 15


def tool_output(response: object) -> str:
    if isinstance(response, dict):
        out = response.get("stdout")
        return out if isinstance(out, str) else ""
    return response if isinstance(response, str) else ""


def note(text: str) -> None:
    out = {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": text}}
    print(json.dumps(out))


def run(payload: dict) -> str | None:
    """The line to tell Claude, or None to stay silent."""
    if payload.get("tool_name") != "Bash":
        return None
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str) or not pb.creates_item(command):
        return None
    try:
        board = pb.load_board()
    except pb.BoardError as exc:
        return f"board: not filed ({exc})"
    if board is None:
        return None
    urls = pb.created_urls(tool_output(payload.get("tool_response")), board.owner)
    budget = pb.Budget(BUDGET_SECONDS)
    failed: dict[str, list[str]] = {}
    for url, status in urls:
        try:
            pb.file_item(board, url, status, budget)
        except pb.BoardError as exc:
            failed.setdefault(str(exc), []).append(url)
    if not failed:
        return None
    return "; ".join(
        f"board: could not add {', '.join(group)} ({why})" for why, group in failed.items()
    )


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        line = run(payload) if isinstance(payload, dict) else None
    except Exception as exc:  # a hook never fails the tool call
        line = None if isinstance(exc, ValueError) else f"board: hook error ({exc})"
    if line:
        note(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
