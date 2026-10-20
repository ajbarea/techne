#!/usr/bin/env python3
"""PostToolUse hook (Bash): put each issue or PR a command just opened on the techne board.

When the command ran `gh issue create`, `gh pr create` (or `new`) or a `gh api` POST to
.../issues or .../pulls, it adds each issue or PR the output reports created in a repo of the
board's owner, with Status Issue or In PR. An item already on the board keeps its Status. Without
a [board] table in ~/.claude/techne.toml, or below python3 3.11 (no tomllib), it does nothing.
Never blocks the tool call: a failure becomes one line of additionalContext under LINE_CAP
characters, success prints nothing.
"""

from __future__ import annotations

import json
import os
import sys

sys.dont_write_bytecode = True  # the plugin cache stays as installed
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "_shared"))
import project_board as pb  # noqa: E402  # ty: ignore[unresolved-import]

BUDGET_SECONDS = 8.0  # hooks.json gives the hook 15
LINE_CAP = 300


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
    except pb.TomlError:
        return None  # unreadable as on a python3 without tomllib; /techne:board names it
    except pb.BoardError as exc:
        return cap(f"board: not filed ({exc})")
    if board is None:
        return None
    urls = pb.created_urls(tool_output(payload.get("tool_response")), board.owner)
    budget = pb.Budget(BUDGET_SECONDS)
    failed: dict[str, list[str]] = {}
    for url, status in urls:
        if pb.SCOPE_FIX in failed:  # every later call fails the same way
            failed[pb.SCOPE_FIX].append(url)
            continue
        try:
            pb.file_new_item(board, url, status, budget)
        except pb.BoardError as exc:
            failed.setdefault(str(exc), []).append(url)
    if not failed:
        return None
    parts = []
    for why, group in failed.items():
        what = group[0] if len(group) == 1 else f"{len(group)} URLs (first: {group[0]})"
        parts.append(f"could not add {what} ({why})")
    return cap("board: " + "; ".join(parts))


def cap(line: str) -> str:
    return line if len(line) < LINE_CAP else line[: LINE_CAP - 4] + "..."


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
