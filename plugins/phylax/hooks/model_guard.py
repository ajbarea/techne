#!/usr/bin/env python3
"""Guard on the Agent tool: refuse a subagent call that names no model.

The hooks.json PreToolUse hook (matcher Agent|Task) runs this when the
require_subagent_model option is on, passing the PreToolUse JSON on stdin. A call
with no model would run on the session's model, so it is denied with a reason that
says how to name one. A `fork` subagent always runs on the parent's model and
ignores `model`, so it is exempt. The tool was named Task before Claude Code 2.1.63.
A payload that cannot be read is reported on stderr and allowed, so a change in
payload shape does not block every dispatch.
Runs on the system python3, so it stays compatible with 3.9 (macOS's).
"""

from __future__ import annotations

import json
import sys

TOOLS = ("Agent", "Task")
REASON = (
    "phylax: this subagent call names no model, so it would run on this session's model. "
    "Pass model: opus to plan or review, sonnet to implement or run a research sweep, "
    "haiku only for mechanical edits; for an agent type whose definition sets a model, "
    "pass that model. Switch require_subagent_model off in /config to allow it."
)


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
        tool_input = {}
    if tool_input.get("subagent_type") == "fork" or names_model(tool_input):
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
