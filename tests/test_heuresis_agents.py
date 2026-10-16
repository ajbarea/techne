"""Agent frontmatter pins model, tools and turns; the skill names every agent it dispatches."""

from __future__ import annotations

import yaml
from conftest import ROOT

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


def test_no_agent_or_skill_text_uses_em_dashes():
    for path in [*PLUGIN.glob("agents/*.md"), *PLUGIN.glob("skills/*/SKILL.md")]:
        assert "—" not in path.read_text(), path
