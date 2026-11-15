"""Every skill, agent and command frontmatter parses as strict YAML.

Claude Code reads an unquoted `description:` that itself contains ": " leniently, but strict
loaders (Copilot CLI's and agy's skill loaders) reject it, so those engines silently skip
the skill.
"""

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
FILES = sorted(
    [
        *ROOT.glob("plugins/*/skills/*/SKILL.md"),
        *ROOT.glob("plugins/*/agents/*.md"),
        *ROOT.glob("plugins/*/commands/*.md"),
    ]
)
FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.S)


def frontmatter(path: Path) -> str | None:
    m = FRONTMATTER.match(path.read_text(encoding="utf-8"))
    return m.group(1) if m else None


def test_the_glob_finds_the_skills() -> None:
    assert len([f for f in FILES if f.name == "SKILL.md"]) >= 20


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(ROOT)))
def test_frontmatter_is_strict_yaml_with_a_string_description(path: Path) -> None:
    text = frontmatter(path)
    if text is None:
        pytest.skip("no frontmatter")
    data = yaml.safe_load(text)
    assert isinstance(data, dict), "frontmatter is not a mapping"
    if path.name == "SKILL.md":
        assert isinstance(data.get("name"), str) and data["name"]
        assert isinstance(data.get("description"), str) and data["description"]


def test_an_unquoted_colon_in_a_description_is_rejected() -> None:
    with pytest.raises(yaml.YAMLError):
        yaml.safe_load("name: x\ndescription: Run a session: Claude drives it\n")
