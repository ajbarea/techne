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
# A class whose guard became a mechanical check also says which check, last.
RETIRED = "Retired"
DATE_RE = re.compile(r"\b20\d\d-\d\d(?:-\d\d)?\b")
# Incidents are `where (YYYY-MM[-DD]): what happened`, joined by "; ".
INCIDENT_RE = re.compile(r"^(?P<where>[^;():]+?) \((?P<date>20\d\d-\d\d(?:-\d\d)?)\): \S")
NONE_RECORDED = "none recorded."
MAX_INCIDENTS = 3
# The catalog ships in a public repo: an incident names one of these public repos, or
# describes a private one ("a private rm-approval hook") without naming it.
PUBLIC_REPOS = {"techne", "pharos", "sphragis", "klepsydra", "kourai"}
# Where an incident happened: a public repo with an optional PR, round and short label
# ("techne#189 r1 to r18", "kourai a2a-sdk 1.0"), "a private ..." or a listed host.
PUBLIC_WHERE_RE = re.compile(r"^(?P<repo>[a-z0-9-]+)(?:#\d+)?(?: r\d+(?: to r\d+)?)?(?: [\w.-]+)*$")
HOSTS = {"a WSL workstation"}
# A `name#N` reference anywhere in a class must name a public repo.
REPO_REF_RE = re.compile(r"\b([a-z][a-z0-9-]*)#\d+")
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


def split_incidents(text: str) -> list[str]:
    """Split on "; " outside backticks, so a command such as `a; b` stays one incident."""
    items, start, ticks = [], 0, 0
    for i, char in enumerate(text):
        ticks += char == "`"
        if text.startswith("; ", i) and ticks % 2 == 0:
            items.append(text[start:i])
            start = i + 2
    return [*items, text[start:]]


def problems(entry: dict) -> list[str]:
    """What is wrong with one parsed class; empty when it is well formed."""
    found = []
    names = tuple(name for name, _ in entry["fields"])
    if names not in (FIELDS, (*FIELDS, RETIRED)):
        found.append(f"fields {names} are not {FIELDS}, optionally then {RETIRED}")
    incidents = dict(entry["fields"]).get("Incidents", "")
    if incidents == NONE_RECORDED:
        if entry["number"] is None:
            found.append("a learned class cites no incident")
        return found
    items = split_incidents(incidents)
    if len(items) > MAX_INCIDENTS:
        found.append(f"more than {MAX_INCIDENTS} incidents")
    for item in items:
        match = INCIDENT_RE.match(item)
        if not match:
            found.append(f"incident is not `where (date): what`: {item[:60]!r}")
            continue
        where = match.group("where")
        public = PUBLIC_WHERE_RE.match(where)
        if not (
            where.startswith("a private ")
            or where in HOSTS
            or (public and public.group("repo") in PUBLIC_REPOS)
        ):
            found.append(f"incident is at {where!r}: not a public repo, `a private ...` or a host")
    for _, value in entry["fields"]:
        for repo in REPO_REF_RE.findall(value):
            if repo not in PUBLIC_REPOS:
                found.append(f"names {repo}#N, not a public repo")
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


def _entry(**fields: str) -> dict:
    lines = "".join(f"- **{name}:** {value}\n" for name, value in fields.items())
    (entry,) = parse(f"## Learned\n\n### a-b: A\n\n{lines}")
    return entry


GOOD = {"Symptom": "s", "Question": "q", "Guard": "g", "Incidents": "techne#1 (2026-10): y."}


def test_split_keeps_a_command_with_a_semicolon_whole():
    text = "techne#1 (2026-10-01): `ln -s ~ hl; rm -rf hl/` passed; pharos (2026-08): y"
    assert split_incidents(text) == [
        "techne#1 (2026-10-01): `ln -s ~ hl; rm -rf hl/` passed",
        "pharos (2026-08): y",
    ]


def test_a_well_formed_class_has_no_problems():
    assert problems(_entry(**GOOD)) == []


def test_a_missing_field_is_a_problem():
    fields = {k: v for k, v in GOOD.items() if k != "Question"}
    assert problems(_entry(**fields))


def test_a_retired_line_is_allowed_last_only():
    assert problems(_entry(**GOOD, Retired="ruff rule X in make lint")) == []
    first = {"Retired": "x", **GOOD}
    assert problems(_entry(**first))


@pytest.mark.parametrize(
    "incidents",
    [
        "techne: something, no date.",
        NONE_RECORDED,  # allowed only on a core class
        "techne#1 (2026-10-01): x; the same day an undated second one",
        "; ".join(f"techne#{n} (2026-10-0{n}): x" for n in range(1, 5)),
        "private-repo#3 (2026-10-01): a private repo named by name",
        "a acme-internal installer (2026-06-30): an article in front of a private name",
        "an acme-tools rm hook r1 (2026-10-21): the same with `an`",
        "techne#1 (2026-10-01): it echoed acme-internal#534 in the text",
    ],
)
def test_a_malformed_or_unpublishable_incident_is_a_problem(incidents):
    assert problems(_entry(**{**GOOD, "Incidents": incidents}))


@pytest.mark.parametrize(
    "incidents",
    [
        "a private rm-approval hook r1 (2026-10-21): x",
        "pharos (2026-08): x; techne#189 r2 (2026-10-21): y",
        "techne#189 r1 to r18 (2026-10-21): x; kourai a2a-sdk 1.0 (2026-04-29): y",
        "a WSL workstation (2026-10-21): x; a private MCP server's CI (2026-07-04): y",
    ],
)
def test_a_public_repo_or_a_described_private_one_is_fine(incidents):
    assert problems(_entry(**{**GOOD, "Incidents": incidents})) == []


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
