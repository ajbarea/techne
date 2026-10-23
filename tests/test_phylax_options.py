"""One rule for a phylax option being on, kept by every reader: the value is exactly `true`.

Claude Code hands an option to a hook as CLAUDE_PLUGIN_OPTION_<KEY> and to the doctor as
KEY=VALUE; a hand-edited settings.json can store any text there. Each hooks.json handler,
git_guards.py and the doctor must agree on which values switch an option on. The mod needs
no case here: Claude Code refuses to load a hooks module whose options do not fit their
userConfig types, so register.ts only ever sees booleans.
"""

from __future__ import annotations

import json
import pathlib
import re
import subprocess

import pytest
from conftest import HOOK_PYTHON, ROOT, _load, hook_env, hook_handlers, hook_shell

PLUGIN = ROOT / "plugins" / "phylax"
GUARDS = PLUGIN / "hooks" / "git_guards.py"
DOCTOR = PLUGIN / "skills" / "setup" / "scripts" / "doctor.py"
MANIFEST = PLUGIN / ".claude-plugin" / "plugin.json"
OPTIONS = tuple(json.loads(MANIFEST.read_text())["userConfig"])
VALUES = ["true", "True", "TRUE", " true", "true ", "1", "yes", "on", "false", "False", ""]
OPTION_VAR = re.compile(r"\$CLAUDE_PLUGIN_OPTION_([A-Z_]+)")


def handlers() -> list[tuple[str, dict]]:
    config = json.loads((PLUGIN / "hooks" / "hooks.json").read_text())
    return [(event, h) for event in config["hooks"] for h in hook_handlers("phylax", event)]


def handler_options() -> list[tuple[str, int, str]]:
    """(event, index, option) for each option each handler's command reads."""
    cases = []
    for i, (event, handler) in enumerate(handlers()):
        names = OPTION_VAR.findall(handler["command"])
        assert names, f"{event} handler reads no option"
        cases += [(event, i, name.lower()) for name in names]
    return cases


def test_every_option_has_a_hooks_json_handler():
    assert set(OPTIONS) == {option for _, _, option in handler_options()}


@pytest.mark.parametrize("value", VALUES)
@pytest.mark.parametrize(("event", "index", "option"), handler_options())
def test_a_handler_starts_python_only_for_exactly_true(tmp_path, event, index, option, value):
    _, handler = handlers()[index]
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "python3").write_text("#!/bin/sh\necho started\n")
    (fake / "python3").chmod(0o755)
    env = {"PATH": str(fake), f"CLAUDE_PLUGIN_OPTION_{option.upper()}": value}
    proc = subprocess.run(
        ["/bin/sh", "-c", hook_shell("phylax", handler, python=None)],
        input="{}",
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    assert (proc.stdout.strip() == "started") == (value == "true"), (event, option, value)


@pytest.fixture
def repo(tmp_path: pathlib.Path) -> pathlib.Path:
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    (r / "COMMITS.md").write_text("plan\n")
    return r


@pytest.mark.parametrize("value", VALUES)
def test_git_guards_act_only_for_exactly_true(repo, value):
    payload = json.dumps({"cwd": str(repo), "tool_input": {"command": "git add COMMITS.md"}})
    proc = subprocess.run(
        [HOOK_PYTHON, str(GUARDS)],
        input=payload,
        capture_output=True,
        text=True,
        env=hook_env({"block_commits_md": value}),
        check=False,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert bool(proc.stdout.strip()) == (value == "true"), value


@pytest.mark.parametrize("value", VALUES)
def test_the_doctor_reports_on_only_for_exactly_true(value):
    doctor = _load("phylax_doctor_options", DOCTOR)
    for option in OPTIONS:
        parsed = doctor.parse_options([f"{option}={value}"])
        line = doctor.option_line(option, parsed[option])
        assert (line.detail == "on") == (value == "true"), (option, value)


@pytest.mark.parametrize("value", ["True", "TRUE", " true", "1", "yes"])
def test_the_doctor_names_a_value_the_hooks_do_not_read_as_true(value):
    doctor = _load("phylax_doctor_options", DOCTOR)
    parsed = doctor.parse_options([f"block_commits_md={value}"])
    detail = doctor.option_line("block_commits_md", parsed["block_commits_md"]).detail
    assert repr(value) in detail and "off" in detail
