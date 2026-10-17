"""Every skill has a docs page, and llms.txt describes each page with the page's own text."""

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
# docs/skills/docs-site.md is edited in a separate change; it joins these checks once that lands.
SEPARATE_CHANGE = {"skills/docs-site.md"}
SKILL_URL = "https://github.com/ajbarea/techne/blob/main/plugins/{plugin}/skills/{skill}/SKILL.md"


def description(page: Path) -> str | None:
    head = re.match(r"---\n(.*?)\n---\n", page.read_text(), re.S)
    if head is None:
        return None
    line = re.search(r"^description: (.*)$", head.group(1), re.M)
    if line is None:
        return None
    value = line.group(1).strip()
    if value.startswith('"'):
        return tomllib.loads(f"d = {value}")["d"]
    return value


def test_every_skill_has_a_docs_page() -> None:
    pages = {p: p.read_text() for p in (DOCS / "skills").glob("*.md")}
    missing = []
    for skill_md in sorted(ROOT.glob("plugins/*/skills/*/SKILL.md")):
        skill = skill_md.parent.name
        if f"skills/{skill}.md" in SEPARATE_CHANGE:
            continue
        plugin = skill_md.parents[2].name
        url = SKILL_URL.format(plugin=plugin, skill=skill)
        if not any(url in text for text in pages.values()):
            missing.append(f"{plugin}:{skill}")
    assert missing == [], f"no docs/skills page links the SKILL.md of: {missing}"


def test_every_page_has_a_description() -> None:
    bare = [p.relative_to(DOCS).as_posix() for p in DOCS.rglob("*.md") if not description(p)]
    bare = [p for p in bare if p not in SEPARATE_CHANGE]
    assert bare == [], f"no description: front matter: {bare}"


def test_llms_sections_repeat_page_descriptions() -> None:
    config = tomllib.loads((ROOT / "zensical.toml").read_text())
    sections = config["project"]["plugins"]["llmstxt"]["sections"]
    entries = {
        path: text for items in sections.values() for item in items for path, text in item.items()
    }
    pages = {p.relative_to(DOCS).as_posix() for p in DOCS.rglob("*.md")}
    assert set(entries) == pages, "every page is an llms.txt entry, and every entry is a page"
    stale = [
        p
        for p, text in entries.items()
        if p not in SEPARATE_CHANGE and text != description(DOCS / p)
    ]
    assert stale == [], f"llms.txt text differs from the page's description: {stale}"
