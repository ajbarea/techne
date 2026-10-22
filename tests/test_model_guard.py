"""Tests for model_guard.py, the opt-in guard that refuses a subagent call naming no model."""

from __future__ import annotations

import json
import os
import pathlib
import subprocess

import pytest
from conftest import HOOK_PYTHON

ROOT = pathlib.Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "plugins" / "phylax"
GUARD = PLUGIN / "hooks" / "model_guard.py"
HOOKS_JSON = PLUGIN / "hooks" / "hooks.json"
MANIFEST = PLUGIN / ".claude-plugin" / "plugin.json"
OPTION = "require_subagent_model"


def _env(on: str | None) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_PLUGIN_OPTION_")}
    if on is not None:
        env[f"CLAUDE_PLUGIN_OPTION_{OPTION.upper()}"] = on
    return env


def payload(tool="Agent", **tool_input) -> str:
    tool_input.setdefault("prompt", "p")
    tool_input.setdefault("description", "d")
    tool_input.setdefault("subagent_type", "general-purpose")
    return json.dumps({"tool_name": tool, "tool_input": tool_input})


DEFAULT_ENV = ("CLAUDE_CODE_SUBAGENT_MODEL", "CLAUDE_CODE_SUBAGENT_MODEL_FORCE")


def run_guard(stdin: str, **env_extra: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in DEFAULT_ENV}
    return subprocess.run(
        [HOOK_PYTHON, str(GUARD)],
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
        env={**env, **env_extra},
    )


def decision(proc: subprocess.CompletedProcess) -> str | None:
    assert proc.returncode == 0, proc.stderr
    if not proc.stdout.strip():
        return None
    out = json.loads(proc.stdout)["hookSpecificOutput"]
    assert out["hookEventName"] == "PreToolUse"
    assert out["permissionDecision"] == "deny"
    return out["permissionDecisionReason"]


def _handler() -> dict:
    groups = json.loads(HOOKS_JSON.read_text())["hooks"]["PreToolUse"]
    (group,) = [g for g in groups if g["matcher"] == "Agent|Task"]
    (handler,) = group["hooks"]
    return handler


def run_handler(stdin: str, on: str | None = "true") -> subprocess.CompletedProcess:
    shell = _handler()["command"].replace("${CLAUDE_PLUGIN_ROOT}", str(PLUGIN))
    return subprocess.run(
        ["sh", "-c", shell], input=stdin, capture_output=True, text=True, env=_env(on), check=False
    )


MISSING = object()


@pytest.mark.parametrize("model", [MISSING, None, "", "  ", 5])
@pytest.mark.parametrize("tool", ["Agent", "Task"])
def test_unnamed_model_is_refused(tool, model):
    fields = {} if model is MISSING else {"model": model}
    reason = decision(run_guard(payload(tool, **fields)))
    assert reason and "model" in reason


@pytest.mark.parametrize(
    "model", ["opus", "sonnet", "haiku", "fable", "claude-opus-5-5", "inherit"]
)
def test_named_model_is_silent(model):
    assert decision(run_guard(payload(model=model))) is None


# Claude Code's order: the call's model, the definition's, CLAUDE_CODE_SUBAGENT_MODEL (which
# Explore and Plan ignore unless forced), the session's. _FORCE=1 puts the variable first.
# Each row: agent type, env, whether a call with no model is refused.
RESOLUTION = [
    ("general-purpose", {}, True),
    ("general-purpose", {"CLAUDE_CODE_SUBAGENT_MODEL": "haiku"}, False),
    ("general-purpose", {"CLAUDE_CODE_SUBAGENT_MODEL": "inherit"}, True),
    ("general-purpose", {"CLAUDE_CODE_SUBAGENT_MODEL": ""}, True),
    ("general-purpose", {"CLAUDE_CODE_SUBAGENT_MODEL_FORCE": "1"}, True),
    ("claude", {"CLAUDE_CODE_SUBAGENT_MODEL": "sonnet"}, False),
    ("Explore", {"CLAUDE_CODE_SUBAGENT_MODEL": "haiku"}, True),
    ("Plan", {"CLAUDE_CODE_SUBAGENT_MODEL": "haiku"}, True),
    ("Explore", {"CLAUDE_CODE_SUBAGENT_MODEL": "haiku", "CLAUDE_CODE_SUBAGENT_MODEL_FORCE": "1"}, False),
    ("Plan", {"CLAUDE_CODE_SUBAGENT_MODEL": "haiku", "CLAUDE_CODE_SUBAGENT_MODEL_FORCE": "0"}, True),
    ("Plan", {"CLAUDE_CODE_SUBAGENT_MODEL": "inherit", "CLAUDE_CODE_SUBAGENT_MODEL_FORCE": "1"}, True),
]


@pytest.mark.parametrize(("agent", "env", "refused"), RESOLUTION)
def test_refusal_follows_claude_codes_model_order(agent, env, refused):
    assert bool(decision(run_guard(payload(subagent_type=agent), **env))) is refused
    # A model named in the call always settles it.
    assert decision(run_guard(payload(subagent_type=agent, model="opus"), **env)) is None


def test_fork_is_exempt_without_a_model():
    assert decision(run_guard(payload(subagent_type="fork"))) is None


@pytest.mark.parametrize("agent", ["general-purpose", "claude", "Explore", "Plan"])
def test_built_in_types_that_inherit_are_checked(agent):
    assert decision(run_guard(payload(subagent_type=agent)))


@pytest.mark.parametrize(
    "agent",
    [
        "heuresis:scout-papers",  # a plugin agent whose definition may pin a model
        "my-reviewer",  # a user or project agent
        "statusline-setup",  # built-in, runs on its own model
        "claude-code-guide",
        "explore",  # names are exact: not the built-in Explore
    ],
)
def test_types_whose_definition_decides_are_silent(agent):
    assert decision(run_guard(payload(subagent_type=agent))) is None


def test_other_tools_are_silent():
    stdin = json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}})
    assert decision(run_guard(stdin)) is None


def test_missing_subagent_type_is_checked_as_general_purpose():
    stdin = json.dumps({"tool_name": "Agent", "tool_input": {"prompt": "p"}})
    assert decision(run_guard(stdin))


@pytest.mark.parametrize("stdin", ["not json", "[1, 2]", ""])
def test_unreadable_payload_does_not_block(stdin):
    proc = run_guard(stdin)
    assert (proc.returncode, proc.stdout) == (0, "")
    assert len(proc.stderr.strip().splitlines()) == 1


@pytest.mark.parametrize("agent", [None, "", 5])
def test_unnamed_or_odd_subagent_type_is_checked_as_general_purpose(agent):
    assert decision(run_guard(payload(subagent_type=agent)))


@pytest.mark.parametrize("tool_input", ["x", None, [1], 5])
def test_unreadable_tool_input_does_not_block(tool_input):
    stdin = json.dumps({"tool_name": "Agent", "tool_input": tool_input})
    proc = run_guard(stdin)
    assert (proc.returncode, proc.stdout) == (0, "")
    assert len(proc.stderr.strip().splitlines()) == 1


def test_missing_tool_input_does_not_block():
    proc = run_guard(json.dumps({"tool_name": "Agent"}))
    assert (proc.returncode, proc.stdout) == (0, "")
    assert len(proc.stderr.strip().splitlines()) == 1


def test_a_subagent_dispatching_a_subagent_is_checked():
    stdin = json.loads(payload())
    stdin.update(agent_id="a1", agent_type="general-purpose")
    assert decision(run_guard(json.dumps(stdin)))


def test_reason_says_how_to_fix_and_how_to_switch_off():
    reason = decision(run_guard(payload()))
    assert reason and "model:" in reason and OPTION in reason


def test_handler_runs_the_guard_when_on():
    assert decision(run_handler(payload()))
    assert decision(run_handler(payload(model="opus"))) is None


@pytest.mark.parametrize("on", [None, "false", ""])
def test_handler_is_silent_when_off(on):
    proc = run_handler(payload(), on=on)  # a payload that would trip
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, "", "")


def test_handler_does_not_start_python_when_off(tmp_path):
    shell = _handler()["command"].replace("${CLAUDE_PLUGIN_ROOT}", str(PLUGIN))
    empty = tmp_path / "bin"
    empty.mkdir()
    env = {"PATH": str(empty), "CLAUDE_PLUGIN_OPTION_REQUIRE_SUBAGENT_MODEL": "false"}
    proc = subprocess.run(
        ["/bin/sh", "-c", shell], input=payload(), capture_output=True, text=True, env=env
    )
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, "", "")


def test_hooks_json_has_one_agent_group_naming_option_and_script():
    groups = json.loads(HOOKS_JSON.read_text())["hooks"]["PreToolUse"]
    assert [g["matcher"] for g in groups].count("Agent|Task") == 1
    command = _handler()["command"]
    assert "$CLAUDE_PLUGIN_OPTION_REQUIRE_SUBAGENT_MODEL" in command
    assert "model_guard.py" in command


def test_manifest_option_is_a_boolean_default_off():
    option = json.loads(MANIFEST.read_text())["userConfig"][OPTION]
    assert option["type"] == "boolean" and option["default"] is False
    assert option["title"] and option["description"]
