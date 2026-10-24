"""Tests for model_guard.py, the opt-in guard that refuses a subagent call naming no model."""

from __future__ import annotations

import json
import os
import pathlib
import subprocess

import pytest
from conftest import HOOK_PYTHON, _load, hook_env, hook_handlers, hook_shell, run_hook_handler

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


# Where Claude Code, and so the guard, finds agent definitions; a test sets them itself.
SESSION_ENV = ("CLAUDE_CONFIG_DIR", "CLAUDE_PROJECT_DIR")
# An empty home and a git repo inside it, so a run reads no real agent definition.
PLACES: dict[str, pathlib.Path] = {}


# The managed folder is a fixed system path a test cannot move; a machine with one would
# change every result for the four built-in names.
_MANAGED = pathlib.Path(_load("model_guard_paths", GUARD).MANAGED) / ".claude" / "agents"


@pytest.fixture(autouse=True)
def isolated(tmp_path):
    if _MANAGED.is_dir():
        pytest.skip(f"{_MANAGED} exists on this machine and outranks every test definition")
    PLACES["home"] = tmp_path / "home"
    PLACES["repo"] = PLACES["home"] / "repo"
    (PLACES["repo"] / ".git").mkdir(parents=True)
    yield
    PLACES.clear()


def run_guard(stdin: str, **env_extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [HOOK_PYTHON, str(GUARD)],
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
        cwd=PLACES["repo"],
        env=hook_env(
            drop=(*DEFAULT_ENV, *SESSION_ENV), **{"HOME": str(PLACES["home"]), **env_extra}
        ),
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
    env = hook_env(
        {} if on is None else {OPTION: on},
        drop=(*DEFAULT_ENV, *SESSION_ENV),
        HOME=str(PLACES["home"]),
    )
    return run_hook_handler("phylax", _handler(), stdin, env, cwd=PLACES["repo"])


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


# A managed, project or user definition named like a built-in replaces it, so its model decides.


def define(folder: pathlib.Path, name: str, model: str | None, file: str = "a.md") -> None:
    folder.mkdir(parents=True, exist_ok=True)
    line = "" if model is None else f"model: {model}\n"
    (folder / file).write_text(f"---\nname: {name}\ndescription: d\n{line}---\nbody\n")


def place(where: str) -> pathlib.Path:
    """The agents folder for a definition location, relative to the isolated home and repo."""
    home, repo = PLACES["home"], PLACES["repo"]
    return {
        "user": home / ".claude" / "agents",
        "project": repo / ".claude" / "agents",
        "project-subfolder": repo / ".claude" / "agents" / "review" / ".hidden",
    }[where]


def run_in(cwd: pathlib.Path, **tool_input) -> str | None:
    stdin = json.loads(payload(**tool_input))
    stdin["cwd"] = str(cwd)
    return decision(run_guard(json.dumps(stdin)))


@pytest.mark.parametrize("where", ["user", "project", "project-subfolder"])
@pytest.mark.parametrize("agent", INHERITING_TYPES)
@pytest.mark.parametrize(
    ("model", "refused"),
    [
        ("haiku", False),
        ("claude-opus-5-5", False),
        ("'sonnet'  # quoted, with a comment", False),
        ("inherit", True),
        ('"inherit"', True),
        ("inherit  # the session's", True),
        (None, True),
        ("", True),
        ("~", True),
        ('""', True),
    ],
)
def test_a_definition_named_like_a_built_in_decides(where, agent, model, refused):
    define(place(where), agent, model)
    assert bool(run_in(PLACES["repo"], subagent_type=agent)) is refused


@pytest.mark.parametrize("agent", INHERITING_TYPES)
@pytest.mark.parametrize(("model", "refused"), [(None, False), ("inherit", True)])
def test_the_subagent_model_default_reaches_a_definition_with_no_model(agent, model, refused):
    define(place("user"), agent, model)
    stdin = json.loads(payload(subagent_type=agent))
    stdin["cwd"] = str(PLACES["repo"])
    assert bool(decision(run_guard(json.dumps(stdin), **{VAR: "haiku"}))) is refused


@pytest.mark.parametrize(
    ("first", "second", "refused"),
    [
        # (higher priority, lower priority): the higher one decides.
        (("project", "inherit"), ("user", "haiku"), True),
        (("project", "haiku"), ("user", "inherit"), False),
        (("near", "inherit"), ("project", "haiku"), True),
        (("near", "haiku"), ("project", "inherit"), False),
    ],
)
def test_the_highest_priority_definition_decides(first, second, refused):
    near = PLACES["repo"] / "pkg" / "sub"
    folders = {
        "user": place("user"),
        "project": place("project"),
        "near": near / ".claude" / "agents",
    }
    for where, model in (first, second):
        define(folders[where], "Explore", model)
    near.mkdir(parents=True, exist_ok=True)
    assert bool(run_in(near, subagent_type="Explore")) is refused


def test_the_payload_cwd_is_walked_not_the_hook_process_cwd(tmp_path):
    other = PLACES["home"] / "other"
    (other / ".git").mkdir(parents=True)
    define(other / ".claude" / "agents", "Plan", "haiku")
    assert run_in(other, subagent_type="Plan") is None
    assert run_in(PLACES["repo"], subagent_type="Plan")


def test_the_session_project_dir_outranks_the_payload_cwd(tmp_path):
    other = PLACES["home"] / "other"
    (other / ".git").mkdir(parents=True)
    define(place("project"), "Plan", "haiku")
    stdin = json.loads(payload(subagent_type="Plan"))
    stdin["cwd"] = str(other)  # the session has since moved here
    assert decision(run_guard(json.dumps(stdin), CLAUDE_PROJECT_DIR=str(PLACES["repo"]))) is None
    assert decision(run_guard(json.dumps(stdin)))


def test_a_symlinked_home_still_stops_the_walk(tmp_path):
    real = tmp_path / "real-home"
    (real / "loose" / "dir").mkdir(parents=True)
    link = tmp_path / "link-home"
    link.symlink_to(real, target_is_directory=True)
    define(tmp_path / ".claude" / "agents", "Plan", "haiku")  # above home: never read
    stdin = json.loads(payload(subagent_type="Plan"))
    stdin["cwd"] = str(real / "loose" / "dir")
    assert decision(run_guard(json.dumps(stdin), HOME=str(link)))


def test_a_payload_without_cwd_walks_the_process_cwd():
    define(place("project"), "Plan", "haiku")
    assert decision(run_guard(payload(subagent_type="Plan"))) is None


def test_the_walk_stops_at_the_git_root():
    above = PLACES["home"] / "outer"
    inner = above / "repo"
    (inner / ".git").mkdir(parents=True)
    define(above / ".claude" / "agents", "Plan", "haiku")
    assert run_in(inner, subagent_type="Plan")


def test_the_walk_stops_below_the_home_folder(tmp_path):
    # Above home is never read; home's own .claude/agents is the user folder.
    define(tmp_path / ".claude" / "agents", "Plan", "haiku")
    loose = PLACES["home"] / "loose" / "dir"
    loose.mkdir(parents=True)
    assert run_in(loose, subagent_type="Plan")


def test_without_a_git_root_the_walk_reaches_home(tmp_path):
    loose = PLACES["home"] / "loose" / "dir"
    loose.mkdir(parents=True)
    define(PLACES["home"] / "loose" / ".claude" / "agents", "Plan", "haiku")
    assert run_in(loose, subagent_type="Plan") is None


def test_claude_config_dir_moves_the_user_folder(tmp_path):
    config = tmp_path / "config"
    define(config / "agents", "Explore", "haiku")
    stdin = json.loads(payload(subagent_type="Explore"))
    stdin["cwd"] = str(PLACES["repo"])
    assert decision(run_guard(json.dumps(stdin), CLAUDE_CONFIG_DIR=str(config))) is None
    assert decision(run_guard(json.dumps(stdin)))  # ~/.claude/agents holds nothing


@pytest.mark.parametrize(
    "text",
    [
        "name: Explore\nmodel: haiku\n---\n",  # no opening marker
        "\n---\nname: Explore\nmodel: haiku\n---\n",  # the marker is not the first line
        "---\nname: Explore\nmodel: haiku\n",  # never closed
        "---\nname: explore\nmodel: haiku\n---\n",  # names are exact
        "---\nname: Explore-2\nmodel: haiku\n---\n",
        "---\ndescription: d\nmodel: haiku\n---\n",  # no name
        "---\n  name: Explore\nmodel: haiku\n---\n",  # indented: not a top-level key
        "# Explore\nname: Explore\nmodel: haiku\n---\n",  # a heading before the fields
    ],
)
def test_a_file_that_is_not_a_definition_of_the_type_is_ignored(text):
    folder = place("project")
    folder.mkdir(parents=True)
    (folder / "Explore.md").write_text(text)  # the file name does not name the agent
    assert run_in(PLACES["repo"], subagent_type="Explore")


def test_only_markdown_files_are_read():
    folder = place("project")
    folder.mkdir(parents=True)
    (folder / "Explore.txt").write_text("---\nname: Explore\nmodel: haiku\n---\n")
    assert run_in(PLACES["repo"], subagent_type="Explore")


def test_a_byte_order_mark_before_the_frontmatter_is_read():
    folder = place("project")
    folder.mkdir(parents=True)
    (folder / "e.md").write_bytes(b"\xef\xbb\xbf---\nname: Explore\nmodel: haiku\n---\n")
    assert run_in(PLACES["repo"], subagent_type="Explore") is None


@pytest.mark.parametrize(
    "fields",
    [
        "model:\n- haiku\n",  # a list at column 0
        "model:\n  haiku\n",  # a multi-line value
        "model: haiku\nmodel: inherit\n",  # a key given twice
    ],
)
def test_a_model_value_the_reader_cannot_parse_allows_the_call(fields):
    folder = place("project")
    folder.mkdir(parents=True)
    (folder / "e.md").write_text(f"---\nname: Explore\n{fields}---\n")
    assert run_in(PLACES["repo"], subagent_type="Explore") is None


def test_reading_stops_at_the_closing_marker(mg, tmp_path, monkeypatch):
    path = tmp_path / "d.md"
    path.write_text("---\nname: Explore\nmodel: haiku\n---\n" + "x" * 100_000)
    monkeypatch.setattr(mg, "HEAD", 64)
    assert mg.frontmatter(str(path)) == {"name": "Explore", "model": "haiku"}
    path.write_text("---\nname: Explore\n" + "a: b\n" * 100 + "---\n")
    assert mg.frontmatter(str(path)) is None  # never closed within HEAD bytes


def test_crlf_frontmatter_is_read():
    folder = place("project")
    folder.mkdir(parents=True)
    (folder / "e.md").write_bytes(b"---\r\nname: Explore\r\nmodel: haiku\r\n---\r\nbody\r\n")
    assert run_in(PLACES["repo"], subagent_type="Explore") is None


def test_a_symlinked_folder_is_followed_and_a_loop_ends(tmp_path):
    shared = tmp_path / "shared"
    define(shared, "Explore", "haiku")
    folder = place("project")
    folder.mkdir(parents=True)
    (folder / "shared").symlink_to(shared, target_is_directory=True)
    (shared / "loop").symlink_to(folder, target_is_directory=True)
    assert run_in(PLACES["repo"], subagent_type="Explore") is None


def test_duplicates_in_one_folder_allow_when_any_names_a_model():
    # Claude Code keeps one of them by filesystem read order, which it does not document.
    define(place("project"), "Explore", "inherit", file="a.md")
    define(place("project"), "Explore", "haiku", file="b.md")
    assert run_in(PLACES["repo"], subagent_type="Explore") is None


def test_an_unreadable_definition_is_skipped():
    define(place("project"), "Explore", "haiku")
    target = place("project") / "a.md"
    target.chmod(0)
    try:
        if os.access(target, os.R_OK):
            pytest.skip("running as a user that reads mode-0 files (root)")
        assert run_in(PLACES["repo"], subagent_type="Explore")
    finally:
        target.chmod(0o644)


def test_a_definition_does_not_touch_a_named_call_or_another_type():
    define(place("project"), "Explore", "inherit")
    assert run_in(PLACES["repo"], subagent_type="Explore", model="opus") is None
    assert run_in(PLACES["repo"], subagent_type="my-reviewer") is None


# In-process: the managed folder is a fixed system path, so tests point the module at a temp one.


@pytest.fixture
def mg(tmp_path, monkeypatch):
    module = _load("model_guard_under_test", GUARD)
    monkeypatch.setattr(module, "MANAGED", str(tmp_path / "managed"))
    monkeypatch.setenv("HOME", str(PLACES["home"]))
    for name in SESSION_ENV:
        monkeypatch.delenv(name, raising=False)
    for name in DEFAULT_ENV:
        monkeypatch.delenv(name, raising=False)
    return module


@pytest.mark.parametrize(("managed", "refused"), [("inherit", True), ("haiku", False)])
def test_a_managed_definition_outranks_project_and_user(mg, tmp_path, managed, refused):
    define(tmp_path / "managed" / ".claude" / "agents", "Plan", managed)
    other = "haiku" if managed == "inherit" else "inherit"
    define(place("project"), "Plan", other)
    define(place("user"), "Plan", other)
    assert mg.default_decides("Plan", str(PLACES["repo"])) is not refused


def test_the_file_budget_bounds_a_huge_folder(mg, monkeypatch):
    monkeypatch.setattr(mg, "MAX_FILES", 5)
    folder = place("project")
    for i in range(10):
        define(folder, f"other-{i}", "haiku", file=f"{i:02}.md")
    define(folder, "Plan", "inherit", file="zz.md")  # read after the budget runs out
    # A folder too large to read counts as unknown, and the call goes ahead.
    assert mg.default_decides("Plan", str(PLACES["repo"])) is True
    monkeypatch.setattr(mg, "MAX_FILES", 50)
    assert mg.default_decides("Plan", str(PLACES["repo"])) is False


# The frontmatter reader against a YAML parser, over generated values.
VALUES = [
    "haiku",
    "claude-opus-5-5",
    "inherit",
    "  inherit  ",
    "",
    "~",
    "null",
    "'inherit'",
    '"inherit"',
    "'it''s'",
    '"a \\"quoted\\" word"',
    '"caf\\u00e9"',
    '"tab\\there"',
    "'#not a comment'",
    "a#b",
    "haiku # trailing",
    "haiku #",
    "'haiku' # c",
    '"haiku"   # c',
    "x:y",
    "a: b",
    "[haiku]",
    "{a: b}",
    "|",
    ">-",
    "&anchor haiku",
    "*alias",
    "!tag haiku",
    "- haiku",
    "'unclosed",
    '"unclosed',
    '"bad \\q escape"',
    "two words",
    "@reserved",
]


@pytest.mark.parametrize("value", VALUES)
@pytest.mark.parametrize("after", ["", "  ", " # tail"])
def test_the_frontmatter_reader_agrees_with_yaml(mg, tmp_path, value, after):
    yaml = pytest.importorskip("yaml")
    text = f"---\nname: Explore\nmodel: {value}{after}\n---\nbody\n"
    path = tmp_path / "d.md"
    path.write_text(text)
    ours = mg.frontmatter(str(path))
    assert ours is not None and ours["name"] == "Explore"
    try:
        theirs = yaml.safe_load(text.split("---\n")[1])
    except yaml.YAMLError:
        # Claude Code skips a file it cannot parse; reading UNKNOWN allows the call instead.
        assert ours["model"] is mg.UNKNOWN or isinstance(ours["model"], str)
        return
    expected = theirs.get("model")
    if ours["model"] is mg.UNKNOWN:
        assert not isinstance(expected, str) or value.lstrip()[:1] in "|>[{&*!-'\"x"
        return
    if isinstance(expected, str) or expected is None:
        assert ours["model"] == expected, (value, after)
    else:
        assert isinstance(ours["model"], str)  # YAML 1.1 bools and numbers stay text here


def test_a_multi_line_value_is_unknown(mg, tmp_path):
    path = tmp_path / "d.md"
    path.write_text("---\nname: Explore\nmodel:\n  haiku\n---\n")
    assert mg.frontmatter(str(path))["model"] is mg.UNKNOWN
