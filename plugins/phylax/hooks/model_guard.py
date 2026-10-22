#!/usr/bin/env python3
"""Guard on the Agent tool: refuse a call to a built-in agent type that names no model.

The hooks.json PreToolUse hook (matcher Agent|Task) runs this when the
require_subagent_model option is on, passing the PreToolUse JSON on stdin. The
built-in types in INHERITING run on the session's model unless the call names one,
so such a call is denied with a reason that says how to name one. Every other type
is left to its definition: a call's `model` outranks the definition's, so requiring
one there would override a model the definition pins. A `fork` always runs on the
parent's model and ignores `model`. The tool was named Task before Claude Code 2.1.63.
A payload or tool input that cannot be read is reported on stderr and allowed: the
guard sets a default rather than protecting data, so a change in payload shape must
not block every dispatch.
Runs on the system python3, so it stays compatible with 3.9 (macOS's).
"""

from __future__ import annotations

import json
import sys

TOOLS = ("Agent", "Task")
# Built-in agent types with no model of their own; an omitted type is general-purpose.
INHERITING = ("general-purpose", "claude", "Explore", "Plan")
REASON = (
    "phylax: this subagent call names no model, so it would run on this session's model. "
    "Pass model: with the model this task needs and retry. "
    "Switch require_subagent_model off in /config to allow it."
)


def agent_type(tool_input: dict) -> str:
    kind = tool_input.get("subagent_type")
    return kind if isinstance(kind, str) and kind else "general-purpose"


def names_model(tool_input: dict) -> bool:
    model = tool_input.get("model")
    return isinstance(model, str) and bool(model.strip())


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except ValueError as err:
        print(f"phylax model_guard: stdin is not JSON ({err}); allowing the call", file=sys.stderr)
        return 0
    if not isinstance(data, dict):
        print("phylax model_guard: payload is not an object; allowing the call", file=sys.stderr)
        return 0
    if data.get("tool_name") not in TOOLS:
        return 0
    tool_input = data.get("tool_input")
    if not isinstance(tool_input, dict):
        print("phylax model_guard: tool_input is not an object; allowing the call", file=sys.stderr)
        return 0
    if agent_type(tool_input) not in INHERITING or names_model(tool_input):
        return 0
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": REASON,
                }
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
