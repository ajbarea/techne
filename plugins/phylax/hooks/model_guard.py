#!/usr/bin/env python3
"""Guard on the Agent tool: refuse a call that leaves its model to the session's default.

The hooks.json PreToolUse hook (matcher Agent|Task) runs this when the
require_subagent_model option is on, passing the PreToolUse JSON on stdin. Claude Code
picks a subagent's model in this order: the call's `model`, the agent definition's,
CLAUDE_CODE_SUBAGENT_MODEL (which Explore and Plan ignore unless
CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1, which also puts it first), then the session's. The
built-in types in INHERITING have no model of their own, so a call to one is refused
when nothing before the session's model would decide it. Every other type is left to
its definition: a call's `model` would override one the definition pins. A `fork`
always runs on the parent's model and ignores `model`. The tool was named Task before
Claude Code 2.1.63.
A payload or tool input that cannot be read is reported on stderr and allowed: the
guard sets a default rather than protecting data, so a change in payload shape must
not block every dispatch.
Runs on the system python3, so it stays compatible with 3.9 (macOS's).
"""

from __future__ import annotations

import json
import os
import sys

TOOLS = ("Agent", "Task")
# Built-in agent types with no model of their own; an omitted type is general-purpose.
INHERITING = ("general-purpose", "claude", "Explore", "Plan")
# The built-ins that CLAUDE_CODE_SUBAGENT_MODEL alone does not reach.
UNLESS_FORCED = ("Explore", "Plan")
REASON = (
    "phylax: this subagent call names no model, so it would fall back to a default "
    "rather than a model chosen for the task. "
    "Pass model: with the model this task needs and retry. "
    "Switch require_subagent_model off in /config to allow it."
)


def agent_type(tool_input: dict) -> str:
    kind = tool_input.get("subagent_type")
    return kind if isinstance(kind, str) and kind else "general-purpose"


def env_default() -> str | None:
    """CLAUDE_CODE_SUBAGENT_MODEL when it names a model; `inherit` or empty is the session's."""
    model = os.environ.get("CLAUDE_CODE_SUBAGENT_MODEL", "")
    return model if model and model != "inherit" else None


def default_decides(kind: str) -> bool:
    """Whether something other than the session's model decides an unnamed call to kind."""
    if kind not in INHERITING:
        return True  # the agent's own definition decides
    if env_default() is None:
        return False
    return kind not in UNLESS_FORCED or os.environ.get("CLAUDE_CODE_SUBAGENT_MODEL_FORCE") == "1"


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
    if names_model(tool_input) or default_decides(agent_type(tool_input)):
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
