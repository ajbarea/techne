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
# One incident: `where (YYYY-MM[-DD]): what happened`.
INCIDENT_RE = re.compile(r"\(20\d\d-\d\d(?:-\d\d)?\):")
MAX_INCIDENTS = 3
BUDGET_RE = re.compile(r"<!-- budget: (\d+) words -->")
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
        if current is not None and line.strip():
            field = FIELD_RE.match(line)
            assert field, f"{current['slug']}: a class holds only field lines, got {line!r}"
            current["fields"].append(field.groups())
    return classes


def problems(entry: dict) -> list[str]:
    """What is wrong with one parsed class; empty when it is well formed."""
    found = []
    names = tuple(name for name, _ in entry["fields"])
    if names != FIELDS:
        found.append(f"fields {names} are not {FIELDS}")
    incidents = dict(entry["fields"]).get("Incidents", "")
    if entry["number"] is None and not DATE_RE.search(incidents):
        found.append("a learned class cites no dated incident")
    if len(INCIDENT_RE.findall(incidents)) > MAX_INCIDENTS:
        found.append(f"more than {MAX_INCIDENTS} incidents")
    return found


@pytest.fixture(scope="module")
def classes() -> list[dict]:
    return parse(CATALOG.read_text(encoding="utf-8"))


def test_catalog_has_classes(classes):
    assert len(classes) > 9


def test_every_class_is_well_formed(classes):
    for entry in classes:
        assert problems(entry) == [], entry["slug"]


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


def _entry(**fields: str) -> dict:
    lines = "".join(f"- **{name}:** {value}\n" for name, value in fields.items())
    (entry,) = parse(f"## Learned\n\n### a-b: A\n\n{lines}")
    return entry


GOOD = {"Symptom": "s", "Question": "q", "Guard": "g", "Incidents": "x (2026-10): y."}


def test_a_well_formed_class_has_no_problems():
    assert problems(_entry(**GOOD)) == []


def test_a_missing_field_is_a_problem():
    fields = {k: v for k, v in GOOD.items() if k != "Question"}
    assert problems(_entry(**fields))


def test_an_undated_learned_class_is_a_problem():
    assert problems(_entry(**{**GOOD, "Incidents": "somewhere: something."}))


def test_a_fourth_incident_is_a_problem():
    four = "; ".join(f"r#{n} (2026-10-0{n}): x" for n in range(1, 5))
    assert problems(_entry(**{**GOOD, "Incidents": four}))


@pytest.mark.parametrize("stray", ["  - r#1 (2026-10): an indented sub-bullet", "wrapped text"])
def test_parse_rejects_a_line_that_is_not_a_field(stray):
    text = "## Learned\n\n### a-b: A\n\n- **Symptom:** s\n" + stray + "\n"
    with pytest.raises(AssertionError, match="only field lines"):
        parse(text)


def test_parse_rejects_a_malformed_heading():
    with pytest.raises(AssertionError, match="malformed class heading"):
        parse("### Not A Slug\n")


def test_skill_sends_authors_and_reviewers_to_the_catalog():
    skill = SKILL.read_text(encoding="utf-8")
    assert "(references/bug-classes.md)" in skill
    # The reader tags findings with a class; the author walks the catalog before review.
    assert "**Class**" in skill
    assert "## Before you ask for review" in skill


def test_catalog_stays_within_its_declared_budget():
    text = CATALOG.read_text(encoding="utf-8")
    budget = BUDGET_RE.search(text)
    assert budget, "the catalog declares no word budget"
    assert len(text.split()) <= int(budget.group(1))


@pytest.mark.parametrize("doc", [SKILL, DOCS_PAGE, CATALOG], ids=lambda p: p.name)
def test_every_class_named_in_prose_exists(classes, doc):
    slugs = {entry["slug"] for entry in classes}
    named = set(CLASS_REF_RE.findall(doc.read_text(encoding="utf-8")))
    assert named, f"{doc.name} names no class"
    assert named <= slugs, sorted(named - slugs)
