"""Every `## <section>` a SKILL.md tells the model to read is documented and templated."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "plugins/techne/skills/setup/skill-context.template.md"
CONVENTIONS = ROOT / "docs/conventions.md"
SECTION = re.compile(r"`## ([a-z][a-z_-]*)`")


def sections_read_by_skills() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for skill in sorted((ROOT / "plugins").glob("*/skills/*/SKILL.md")):
        for name in set(SECTION.findall(skill.read_text())):
            found.setdefault(name, []).append(skill.parent.name)
    return found


def test_skills_name_sections() -> None:
    assert "research_grounded" in sections_read_by_skills()


def test_every_section_is_in_the_conventions_table() -> None:
    table = {
        name
        for line in CONVENTIONS.read_text().splitlines()
        if line.startswith("| `## ")
        for name in SECTION.findall(line.split("|")[1])
    }
    missing = {n: s for n, s in sections_read_by_skills().items() if n not in table}
    assert missing == {}, f"sections read by skills but absent from docs/conventions.md: {missing}"


def test_every_section_is_in_the_template() -> None:
    headings = set(re.findall(r"^## ([a-z][a-z_-]*)\s*$", TEMPLATE.read_text(), re.M))
    missing = {n: s for n, s in sections_read_by_skills().items() if n not in headings}
    assert missing == {}, f"sections read by skills but absent from the template: {missing}"
