"""Agent frontmatter pins model, tools and turns; the skill names every agent it dispatches."""

from __future__ import annotations

import argparse
import re

import yaml
from conftest import ROOT
from heuresis import cli

PLUGIN = ROOT / "plugins" / "heuresis"
SCOUTS = ("scout-papers", "scout-patents", "scout-products", "scout-context")


def front(path):
    text = path.read_text()
    return yaml.safe_load(text.split("---", 2)[1]), text


def test_scouts_pin_sonnet_and_judge_pins_opus_without_web():
    for name in SCOUTS:
        meta, _ = front(PLUGIN / "agents" / f"{name}.md")
        assert meta["model"] == "sonnet" and isinstance(meta["maxTurns"], int)
    meta, _ = front(PLUGIN / "agents" / "judge.md")
    assert meta["model"] == "opus"
    tools = {t.strip() for t in meta["tools"].split(",")}
    assert not tools & {"WebSearch", "WebFetch", "Bash"}


def test_skill_dispatches_every_agent_and_uses_the_plugin_venv():
    _, text = front(PLUGIN / "skills" / "idea" / "SKILL.md")
    for name in (*SCOUTS, "judge"):
        assert f"heuresis:{name}" in text
    assert "UV_PROJECT_ENVIRONMENT=${CLAUDE_PLUGIN_DATA}/venv" in text
    assert "${user_config.ideas_repo}" in text


def test_every_agent_says_its_folders_are_absolute_paths():
    # A relative --ideas once wrote scout records into the plugin cache.
    for path in PLUGIN.glob("agents/*.md"):
        _, text = front(path)
        assert "`IDEAS` is an absolute path" in text or "`IDEAS` and `REPOS` are absolute" in text
        if "REPOS" in text:
            assert "`IDEAS` and `REPOS` are absolute paths" in text, path.name


def test_no_agent_or_skill_text_uses_em_dashes():
    for path in [*PLUGIN.glob("agents/*.md"), *PLUGIN.glob("skills/*/SKILL.md")]:
        assert "—" not in path.read_text(), path


def _commands() -> dict[str, set[str]]:
    parser = cli.build_parser()
    (sub,) = (a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    return {
        name: {o for a in p._actions for o in a.option_strings if o.startswith("--")}
        for name, p in sub.choices.items()
    }


def _cli_calls(text: str, known: set[str]):
    for line in text.splitlines():
        for m in re.finditer(r"(python -m )?heuresis ([a-z][a-z-]*)\b([^`]*)", line):
            if m.group(1) or m.group(2) in known:
                yield m.group(2), set(re.findall(r"--[a-z][a-z-]*", m.group(3)))


def test_every_cli_call_in_agents_and_skill_exists_in_the_parser():
    commands = _commands()
    seen = 0
    for path in [*PLUGIN.glob("agents/*.md"), *PLUGIN.glob("skills/*/SKILL.md")]:
        for command, flags in _cli_calls(path.read_text(), set(commands)):
            assert command in commands, (path.name, command)
            assert flags <= commands[command], (path.name, command, flags - commands[command])
            seen += 1
    assert seen >= 10


def test_idea_skill_documents_folder_overrides():
    meta, text = front(PLUGIN / "skills" / "idea" / "SKILL.md")
    assert "--ideas" in meta["argument-hint"] and "--repos" in meta["argument-hint"]
    assert "take precedence" in text
    assert "Remove `--ideas" in text
    docs = (ROOT / "docs" / "skills" / "idea.md").read_text()
    assert "--ideas" in docs and "--repos" in docs


def test_idea_skill_reads_folder_flags_only_as_leading_arguments():
    _, text = front(PLUGIN / "skills" / "idea" / "SKILL.md")
    assert "before the mode or the idea text" in text
    assert "a later `--ideas` or `--repos` is part of the idea text" in text
    assert "everything after the leading flags" in text
    assert "Put them first" in (ROOT / "docs" / "skills" / "idea.md").read_text()


def test_idea_skill_declines_only_when_triaging_with_a_distinct_example():
    _, text = front(PLUGIN / "skills" / "idea" / "SKILL.md")
    section = text.split("## Ideas you must not research")[1].split("## Triage")[0]
    assert "only when you are triaging" in section
    assert "Capture-only" in section and "`--override`" in section
    assert "track my ex's location from her phone number" in section.lower()
    for gold_wording in ("WhatsApp", "iMessage", "conversation"):
        assert gold_wording.lower() not in section.lower()
