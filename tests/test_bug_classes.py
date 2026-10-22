"""The elenchus bug-class catalog parses, and the skill sends authors and reviewers to it.

Each class is a `### slug: Name` heading followed by exactly the four field bullets, in order.
The core rubric is the numbered classes 1 to 9; every other class was learned from an incident,
so it cites a dated one.
"""

from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKILL_DIR = ROOT / "plugins" / "techne" / "skills" / "elenchus"
CATALOG = SKILL_DIR / "references" / "bug-classes.md"
SKILL = SKILL_DIR / "SKILL.md"
DOCS_PAGE = ROOT / "docs" / "skills" / "elenchus.md"

HEADING_RE = re.compile(r"^### (?:(\d+)\. )?([a-z0-9]+(?:-[a-z0-9]+)*): (\S.*)$")
FIELD_RE = re.compile(r"^- \*\*(\w+):\*\* (\S.*)$")
FIELDS = ("Symptom", "Question", "Guard", "Incidents")
DATE_RE = re.compile(r"\b20\d\d-\d\d(?:-\d\d)?\b")
# How SKILL.md and the docs page name a class: class `slug`.
CLASS_REF_RE = re.compile(r"\bclass `([a-z0-9-]+)`")


def parse(text: str) -> list[dict]:
    """One dict per class: number (or None), slug, name, section, and the field lines in order."""
    classes: list[dict] = []
    section = ""
    current: dict | None = None
    for line in text.splitlines():
        if line.startswith("## "):
            section, current = line[3:].strip(), None
            continue
        if line.startswith("### "):
            match = HEADING_RE.match(line)
            assert match, f"malformed class heading: {line!r}"
            number, slug, name = match.groups()
            current = {
                "number": int(number) if number else None,
                "slug": slug,
                "name": name,
                "section": section,
                "fields": [],
            }
            classes.append(current)
            continue
        if current is not None and line.startswith("- "):
            field = FIELD_RE.match(line)
            assert field, f"{current['slug']}: malformed field line {line!r}"
            current["fields"].append(field.groups())
    return classes


@pytest.fixture(scope="module")
def classes() -> list[dict]:
    return parse(CATALOG.read_text(encoding="utf-8"))


def test_catalog_has_classes(classes):
    assert len(classes) > 9


def test_every_class_has_every_field_in_order(classes):
    for entry in classes:
        assert tuple(name for name, _ in entry["fields"]) == FIELDS, entry["slug"]


def test_slugs_are_unique(classes):
    slugs = [entry["slug"] for entry in classes]
    assert len(slugs) == len(set(slugs))


def test_core_rubric_is_cells_one_to_nine_in_order(classes):
    core = [entry for entry in classes if entry["number"] is not None]
    assert [entry["number"] for entry in core] == list(range(1, 10))
    assert {entry["section"] for entry in core} == {"Core rubric"}
    assert all(entry["number"] is None for entry in classes if entry["section"] != "Core rubric")


def test_learned_classes_cite_a_dated_incident(classes):
    for entry in classes:
        incidents = dict(entry["fields"])["Incidents"]
        if entry["number"] is None:
            assert DATE_RE.search(incidents), entry["slug"]
        else:
            assert DATE_RE.search(incidents) or incidents == "none recorded.", entry["slug"]


def test_parse_rejects_a_missing_field():
    text = (
        "## Learned\n\n### a-b: A\n\n"
        "- **Symptom:** s\n- **Guard:** g\n- **Incidents:** x (2026-10)\n"
    )
    (entry,) = parse(text)
    assert tuple(name for name, _ in entry["fields"]) != FIELDS


def test_parse_rejects_a_malformed_heading():
    with pytest.raises(AssertionError, match="malformed class heading"):
        parse("### Not A Slug\n")


def test_skill_sends_authors_and_reviewers_to_the_catalog():
    skill = SKILL.read_text(encoding="utf-8")
    assert "(references/bug-classes.md)" in skill
    # The reader tags findings with a class; the author walks the catalog before review.
    assert "**Class**" in skill
    assert "## Before you ask for review" in skill


@pytest.mark.parametrize("doc", [SKILL, DOCS_PAGE], ids=lambda p: p.name)
def test_every_class_named_in_prose_exists(classes, doc):
    slugs = {entry["slug"] for entry in classes}
    named = set(CLASS_REF_RE.findall(doc.read_text(encoding="utf-8")))
    assert named, f"{doc.name} names no class"
    assert named <= slugs, sorted(named - slugs)
