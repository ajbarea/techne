"""The PreToolUse verdict JSON in the shape of the runtime that sent the hook input.

Claude Code validates hook output and ignores an object that fails, deny included: its
top-level `decision` takes only "approve" or "block", so a "deny" or "allow" there lets the
call run. The Antigravity CLI requires a top-level `decision` and reads `reason`. Each
runtime therefore gets only its own fields.

Runs on the system python3, so it stays compatible with 3.9 (macOS's).
"""

from __future__ import annotations


def from_agy(data: object) -> bool:
    """Whether DATA is Antigravity hook input: a `toolCall` object and no `tool_name`."""
    return (
        isinstance(data, dict)
        and isinstance(data.get("toolCall"), dict)
        and not data.get("tool_name")
    )


def deny(reason: str, agy: bool) -> dict:
    if agy:
        return {"decision": "deny", "reason": reason}
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def warn(text: str, agy: bool) -> dict:
    if agy:
        return {"decision": "allow", "reason": text}
    return {
        "systemMessage": text,
        "hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": text},
    }
