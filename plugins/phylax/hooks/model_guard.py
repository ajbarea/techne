#!/usr/bin/env python3
"""Guard on the Agent tool: refuse a call that leaves its model to the session's.

The hooks.json PreToolUse hook (matcher Agent|Task) runs this when the
require_subagent_model option is on, passing the PreToolUse JSON on stdin. Claude Code
picks a subagent's model from the call's `model`, then the agent definition's, then
CLAUDE_CODE_SUBAGENT_MODEL, then the session's. The built-in types in INHERITING run on
the session's model when the call names none: general-purpose and claude have no model
of their own, unless CLAUDE_CODE_SUBAGENT_MODEL names one; Explore and Plan pin
`inherit`, which wins over that variable. Such a call is refused. A managed, project or
user definition with one of those names replaces the built-in, so its `model` decides
instead: a model it names allows the call, `inherit` refuses it, and none falls through
to CLAUDE_CODE_SUBAGENT_MODEL. Definitions from `--agents` or an `--add-dir` folder are
not visible to a hook and are not read. Every other type is
left to its definition: a call's `model` would override one the definition pins. While
a setting in OVERRIDES is present Claude Code drops or withholds the call's `model`, so
the guard stands down, whatever the value, rather than re-implement how it reads them.
A `fork` always runs on the parent's model. The tool was named Task before Claude Code
2.1.63. A payload or tool input that cannot be read is reported on stderr and allowed:
the guard sets a default rather than protecting data, so a change in payload shape
must not block every dispatch.
Runs on the system python3, so it stays compatible with 3.9 (macOS's).
"""

from __future__ import annotations

import json
import os
import re
import sys

TOOLS = ("Agent", "Task")
# Built-in agent types that run on the session's model; an omitted type is general-purpose.
INHERITING = ("general-purpose", "claude", "Explore", "Plan")
# The ones with no model of their own, which CLAUDE_CODE_SUBAGENT_MODEL reaches.
NO_OWN_MODEL = ("general-purpose", "claude")
# Settings under which Claude Code drops or withholds the call's model.
OVERRIDES = (
    "CLAUDE_CODE_SUBAGENT_MODEL_FORCE",
    "CLAUDE_CODE_COORDINATOR_FORCE_WORKER_INHERIT_MODEL",
)
# The folder holding managed settings, whose .claude/agents outranks every other definition.
MANAGED = {
    "darwin": "/Library/Application Support/ClaudeCode",
    "win32": "C:\\Program Files\\ClaudeCode",
}.get(sys.platform, "/etc/claude-code")
# Bytes read from each definition file; frontmatter sits at its top.
HEAD = 65536
# Definition files read per call at most, so a huge or looping folder cannot stall a dispatch.
MAX_FILES = 2000
KEY = re.compile(r"([A-Za-z_][A-Za-z0-9_-]*)[ \t]*:(?:[ \t]+(.*))?$")
# A frontmatter value this reader does not parse (block or flow), so it counts as unknown.
UNKNOWN = object()
REASON = (
    "phylax: this subagent call names no model, so it would fall back to a default "
    "rather than a model chosen for the task. "
    "Pass model: with the model this task needs and retry. "
    "Switch require_subagent_model off in /config to allow it."
)


def agent_type(tool_input: dict) -> str:
    kind = tool_input.get("subagent_type")
    return kind if isinstance(kind, str) and kind else "general-purpose"


def scalar(raw: str) -> object:
    """A frontmatter value as YAML reads a plain or quoted scalar: None for empty or null,
    UNKNOWN for a block, flow or malformed value."""
    raw = raw.strip()
    if raw[:1] == '"':
        end = re.match(r'"((?:[^"\\]|\\.)*)"[ \t]*(?:#.*)?$', raw)
        if not end:
            return UNKNOWN
        try:
            return json.loads('"' + end.group(1) + '"')
        except ValueError:
            return UNKNOWN
    if raw[:1] == "'":
        end = re.match(r"'((?:[^']|'')*)'[ \t]*(?:#.*)?$", raw)
        return end.group(1).replace("''", "'") if end else UNKNOWN
    raw = re.sub(r"(^|[ \t])#.*$", "", raw).strip()
    if raw in ("", "~", "null", "Null", "NULL"):
        return None
    if raw[0] in "|>[{&*!%@`" or raw.startswith(("- ", "? ")) or raw == "-":
        return UNKNOWN
    if re.search(r":([ \t]|$)", raw):
        return UNKNOWN
    return raw


def frontmatter(path: str) -> dict | None:
    """The top-level `key: value` fields of a definition's frontmatter, or None when the file
    does not open with `---` (after an optional byte-order mark) or never closes it within
    HEAD bytes. A field given twice, or holding a block or flow value, is UNKNOWN."""
    try:
        with open(path, "rb") as f:
            first = f.readline(HEAD)
            if first.removeprefix(b"\xef\xbb\xbf").rstrip() != b"---":
                return None
            size = len(first)
            fields: dict = {}
            continued = None
            while size < HEAD:
                raw = f.readline(HEAD - size)
                if not raw:
                    return None
                size += len(raw)
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                if line.rstrip() == "---":
                    return fields
                match = KEY.match(line)
                if match:
                    key = match.group(1)
                    fields[key] = UNKNOWN if key in fields else scalar(match.group(2) or "")
                    continued = key
                elif continued and line.strip() and not line.lstrip().startswith("#"):
                    if line[:1] in " \t-":
                        fields[continued] = UNKNOWN  # a multi-line, list or nested value
    except OSError:
        return None
    return None


def same(a: str, b: str) -> bool:
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def agent_dirs(start: str) -> list:
    """Folders whose definitions replace a built-in, highest priority first: managed, then
    each project folder from start up to its git root (stopping below the home folder), then
    the user's."""
    home = os.path.expanduser("~")
    dirs = [os.path.join(MANAGED, ".claude", "agents")]
    here = os.path.abspath(start)
    while not same(here, home):
        dirs.append(os.path.join(here, ".claude", "agents"))
        parent = os.path.dirname(here)
        if os.path.exists(os.path.join(here, ".git")) or parent == here:
            break
        here = parent
    config = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(home, ".claude")
    dirs.append(os.path.join(config, "agents"))
    return dirs


def definitions(kind: str, start: str) -> list:
    """The `model` of each definition named kind in the highest-priority folder holding one
    (several when that folder holds duplicates); empty when none replaces the built-in, and
    [UNKNOWN] when the file budget runs out first."""
    budget = MAX_FILES
    for folder in agent_dirs(start):
        models = []
        seen = set()
        for root, subdirs, files in os.walk(folder, followlinks=True):
            real = os.path.realpath(root)
            if real in seen:
                subdirs[:] = []
                continue
            seen.add(real)
            for name in sorted(files):
                if not name.endswith(".md"):
                    continue
                budget -= 1
                if budget < 0:
                    return [UNKNOWN]
                fields = frontmatter(os.path.join(root, name))
                if fields and fields.get("name") == kind:
                    models.append(fields.get("model"))
        if models:
            return models
    return []


def default_decides(kind: str, start: str) -> bool:
    """Whether something other than the session's model may decide an unnamed call to kind."""
    if kind not in INHERITING or any(os.environ.get(name) for name in OVERRIDES):
        return True
    default = os.environ.get("CLAUDE_CODE_SUBAGENT_MODEL", "").strip()
    defaults = default not in ("", "inherit")
    models = definitions(kind, start)
    if not models:
        return kind in NO_OWN_MODEL and defaults
    for model in models:
        if model not in (None, "", "inherit"):
            return True  # a model it names, or a value this reader cannot parse
        if model != "inherit" and defaults:
            return True
    return False


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
    # Claude Code reads project definitions from where the session started, not where it
    # has since moved; the payload's cwd stands in when the variable is missing.
    start = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd")
    if not isinstance(start, str) or not start:
        start = os.getcwd()
    if names_model(tool_input) or default_decides(agent_type(tool_input), start):
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
