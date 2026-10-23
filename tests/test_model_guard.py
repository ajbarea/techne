"""Tests for model_guard.py, the opt-in guard that refuses a subagent call naming no model."""

from __future__ import annotations

import json
import pathlib
import subprocess

import pytest
from conftest import HOOK_PYTHON, hook_env, hook_handlers, hook_shell, run_hook_handler

ROOT = pathlib.Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "plugins" / "phylax"
GUARD = PLUGIN / "hooks" / "model_guard.py"
HOOKS_JSON = PLUGIN / "hooks" / "hooks.json"
MANIFEST = PLUGIN / ".claude-plugin" / "plugin.json"
OPTION = "require_subagent_model"


def payload(tool="Agent", **tool_input) -> str:
    tool_input.setdefault("prompt", "p")
    tool_input.setdefault("description", "d")
    tool_input.setdefault("subagent_type", "general-purpose")
    return json.dumps({"tool_name": tool, "tool_input": tool_input})


# The settings that choose subagent models: _FORCE and coordinator mode stand the guard down for
# every type, CLAUDE_CODE_SUBAGENT_MODEL only for the types with no model of their own.
DEFAULT_ENV = (
    "CLAUDE_CODE_SUBAGENT_MODEL",
    "CLAUDE_CODE_SUBAGENT_MODEL_FORCE",
    "CLAUDE_CODE_COORDINATOR_FORCE_WORKER_INHERIT_MODEL",
)


def run_guard(stdin: str, **env_extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [HOOK_PYTHON, str(GUARD)],
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
        env=hook_env(drop=DEFAULT_ENV, **env_extra),
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
    (handler,) = hook_handlers("phylax", "PreToolUse", "Agent|Task")
    return handler


def run_handler(stdin: str, on: str | None = "true") -> subprocess.CompletedProcess:
    env = hook_env({} if on is None else {OPTION: on})
    return run_hook_handler("phylax", _handler(), stdin, env)


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


VAR, FORCE, COORDINATOR = DEFAULT_ENV
# Under _FORCE or coordinator mode Claude Code drops or withholds the call's model, so any
# value in any spelling stands the guard down; the guard does not parse them.
SPELLINGS = ["1", "true", "TRUE", "yes", "on", " 1", "0", "false", "haiku", "inherit", "  "]
INHERITING_TYPES = ["general-purpose", "claude", "Explore", "Plan"]


@pytest.mark.parametrize("var", [FORCE, COORDINATOR])
@pytest.mark.parametrize("value", SPELLINGS)
@pytest.mark.parametrize("agent", INHERITING_TYPES)
def test_a_setting_that_overrides_the_call_stands_the_guard_down(var, value, agent):
    assert decision(run_guard(payload(subagent_type=agent), **{var: value})) is None


# CLAUDE_CODE_SUBAGENT_MODEL alone reaches only the types with no model of their own;
# Explore and Plan pin `inherit`, which Claude Code resolves before reading it.
@pytest.mark.parametrize(
    ("agent", "value", "refused"),
    [
        ("general-purpose", "haiku", False),
        ("claude", "sonnet", False),
        ("general-purpose", "inherit", True),
        ("general-purpose", "inherit ", True),  # Claude Code trims the value
        ("general-purpose", "  ", True),
        ("general-purpose", " haiku ", False),
        ("claude", "inherit", True),
        ("Explore", "haiku", True),
        ("Plan", "haiku", True),
    ],
)
def test_the_subagent_model_default_reaches_only_types_without_a_model(agent, value, refused):
    assert bool(decision(run_guard(payload(subagent_type=agent), **{VAR: value}))) is refused


@pytest.mark.parametrize("var", DEFAULT_ENV)
def test_an_empty_setting_counts_as_unset(var):
    assert decision(run_guard(payload(), **{var: ""}))


@pytest.mark.parametrize("agent", INHERITING_TYPES)
def test_with_no_setting_a_named_model_settles_it(agent):
    assert decision(run_guard(payload(subagent_type=agent)))
    assert decision(run_guard(payload(subagent_type=agent, model="opus"))) is None


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
    shell = hook_shell("phylax", _handler(), python=None)
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
