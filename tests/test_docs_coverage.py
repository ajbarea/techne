"""Every skill has a docs page, and llms.txt describes each page with the page's own text."""

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
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


def nav_pages(entries: object) -> set[str]:
    if isinstance(entries, list):
        return {page for entry in entries for page in nav_pages(entry)}
    if isinstance(entries, dict):
        return {page for v in entries.values() for page in nav_pages(v)}
    return {entries} if isinstance(entries, str) and entries.endswith(".md") else set()


def test_every_skill_has_its_own_page_in_the_nav() -> None:
    """A page titled with the skill's name, reachable from the nav, linking its SKILL.md."""
    nav = nav_pages(tomllib.loads((ROOT / "zensical.toml").read_text())["project"]["nav"])
    pages = {p: (DOCS / p).read_text() for p in nav if p.startswith("skills/")}
    missing = []
    for skill_md in sorted(ROOT.glob("plugins/*/skills/*/SKILL.md")):
        skill, plugin = skill_md.parent.name, skill_md.parents[2].name
        title = f"# `{plugin}:{skill}`\n"
        url = SKILL_URL.format(plugin=plugin, skill=skill)
        if not any(title in text and url in text for text in pages.values()):
            missing.append(f"{plugin}:{skill}")
    assert missing == [], f"no page in the nav titled with and linking the SKILL.md of: {missing}"


def test_every_page_has_a_description() -> None:
    bare = [p.relative_to(DOCS).as_posix() for p in DOCS.rglob("*.md") if not description(p)]
    assert bare == [], f"no description: front matter: {bare}"


def test_llms_sections_repeat_page_descriptions() -> None:
    config = tomllib.loads((ROOT / "zensical.toml").read_text())
    sections = config["project"]["plugins"]["llmstxt"]["sections"]
    listed = [
        (path, text) for items in sections.values() for item in items for path, text in item.items()
    ]
    entries = dict(listed)
    assert len(entries) == len(listed), "a page is listed twice in llms.txt"
    pages = {p.relative_to(DOCS).as_posix() for p in DOCS.rglob("*.md")}
    assert set(entries) == pages, "every page is an llms.txt entry, and every entry is a page"
    stale = [p for p, text in entries.items() if text != description(DOCS / p)]
    assert stale == [], f"llms.txt text differs from the page's description: {stale}"
