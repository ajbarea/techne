"""The lessons files parse, each gate a lesson names exists and is tested, and each skill loads
the file for its surface. A lesson that cannot be checked says why, in its Check field.
"""

from __future__ import annotations

import datetime
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
GRAPHE = ROOT / "plugins" / "graphe" / "_shared" / "lessons"
TECHNE = ROOT / "plugins" / "techne" / "_shared" / "lessons"
FILES = [
    GRAPHE / "common.md",
    GRAPHE / "slides.md",
    GRAPHE / "paper.md",
    TECHNE / "common.md",
    TECHNE / "docs-site.md",
    TECHNE / "project.md",
]
SURFACES = [f for f in FILES if f.name != "common.md"]
# Skill -> the surface file it must load at the start of the work.
LOADERS = {
    "plugins/graphe/skills/slides/SKILL.md": ["common.md", "slides.md"],
    "plugins/graphe/skills/paper/SKILL.md": ["common.md", "paper.md"],
    "plugins/graphe/skills/latex/SKILL.md": ["common.md", "paper.md"],
    "plugins/graphe/skills/paper-review/SKILL.md": ["common.md", "paper.md"],
    "plugins/techne/skills/docs-site/SKILL.md": ["common.md", "docs-site.md"],
    "plugins/techne/skills/lessons/SKILL.md": ["common.md", "project.md"],
}
HEADING_RE = re.compile(r"^### ([a-z0-9]+(?:-[a-z0-9]+)*): (\S.*)$")
FIELD_RE = re.compile(r"^- \*\*(\w+):\*\* (\S.*)$")
FIELDS = ("Rule", "Why", "Since", "Check")
GATE_RE = re.compile(r"^gate: (?P<path>\S+?)#(?P<id>[^,]+), test: (?P<test>test_\w+)$")
RETIRED_RE = re.compile(
    r"^- `(?P<old>[a-z0-9-]+)`, retired (?P<date>20\d\d-\d\d-\d\d) by `(?P<new>[a-z0-9-]+)`: \S"
)
BUDGET_RE = re.compile(r"^<!-- budget: (\d+) words -->", re.M)


def parse(path: pathlib.Path) -> tuple[list[dict], list[str]]:
    lessons: list[dict] = []
    retired: list[str] = []
    current: dict | None = None
    section = ""
    for line in path.read_text().splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
            current = None
        elif line.startswith("### "):
            m = HEADING_RE.match(line)
            assert m, f"{path}: malformed heading: {line}"
            current = {"slug": m[1], "name": m[2], "file": path, "fields": {}}
            lessons.append(current)
        elif section == "Retired" and re.match(r"\s*(?:[-*+]|\d+[.)])\s", line):
            retired.append(line)
        elif current is not None and (m := FIELD_RE.match(line)):
            current["fields"][m[1]] = m[2]
    return lessons, retired


ALL = [lesson for f in FILES for lesson in parse(f)[0]]


def ids(lesson: dict) -> str:
    return f"{lesson['file'].parent.parent.parent.name}/{lesson['file'].name}:{lesson['slug']}"


@pytest.mark.parametrize("path", FILES, ids=lambda p: f"{p.parents[2].name}/{p.name}")
def test_each_file_parses_and_stays_in_budget(path):
    lessons, _ = parse(path)
    assert lessons, "no lessons parsed"
    budget = BUDGET_RE.search(path.read_text())
    assert budget, f"{path}: no budget line"
    words = len(path.read_text().split())
    assert words <= int(budget[1]), f"{path}: {words} words over its {budget[1]} budget"


@pytest.mark.parametrize("lesson", ALL, ids=ids)
def test_each_lesson_has_its_fields_in_order(lesson):
    assert tuple(lesson["fields"]) == FIELDS
    since = datetime.date.fromisoformat(lesson["fields"]["Since"])
    assert since <= datetime.date.today(), f"{lesson['slug']}: a date in the future"


@pytest.mark.parametrize("lesson", ALL, ids=ids)
def test_a_guidance_lesson_says_why_it_cannot_be_checked(lesson):
    check = lesson["fields"]["Check"]
    assert check.startswith(("gate: ", "guidance: "))
    if check.startswith("guidance: "):
        assert len(check) > len("guidance: ") + 10


GATES = [lesson for lesson in ALL if lesson["fields"]["Check"].startswith("gate: ")]


@pytest.mark.parametrize("lesson", GATES, ids=ids)
def test_a_gate_exists_and_a_test_names_it(lesson):
    m = GATE_RE.match(lesson["fields"]["Check"].removesuffix("."))
    assert m, lesson["fields"]["Check"]
    target = ROOT / m["path"]
    assert target.is_file(), f"{m['path']} does not exist"
    assert m["id"] in target.read_text(), f"{m['id']} is not in {m['path']}"
    tests = "\n".join(p.read_text() for p in (ROOT / "tests").glob("test_*.py"))
    body = re.search(rf"^def {m['test']}\(.*?(?=^\S)", tests + "\n@", re.S | re.M)
    assert body, f"no test named {m['test']}"
    wanted = m["id"].removeprefix("def ").replace("-", "_")
    # The test's own name does not count: a test named after the gate could do nothing.
    rest = body[0].removeprefix(f"def {m['test']}")
    assert wanted in rest.replace("-", "_"), f"{m['test']} never mentions {m['id']}"


def test_slugs_are_unique_within_a_plugin():
    for files in (FILES[:3], FILES[3:]):
        slugs = [lesson["slug"] for f in files for lesson in parse(f)[0]]
        assert len(slugs) == len(set(slugs)), sorted(s for s in slugs if slugs.count(s) > 1)


def test_every_lessons_file_is_checked():
    on_disk = {*GRAPHE.rglob("*.md"), *TECHNE.rglob("*.md")}
    assert on_disk == set(FILES), sorted(str(p) for p in on_disk ^ set(FILES))


def test_common_is_the_same_in_both_plugins():
    assert (GRAPHE / "common.md").read_bytes() == (TECHNE / "common.md").read_bytes()


@pytest.mark.parametrize("path", FILES, ids=lambda p: f"{p.parents[2].name}/{p.name}")
def test_a_retired_lesson_names_a_live_replacement(path):
    _, retired = parse(path)
    live = {lesson["slug"] for lesson in ALL}
    for line in retired:
        m = RETIRED_RE.match(line)
        assert m, f"malformed: {line}"
        assert m["new"] in live, f"{m['old']} retired by unknown {m['new']}"
        assert m["old"] not in live, f"{m['old']} is both retired and live"


@pytest.mark.parametrize("path", SURFACES, ids=lambda p: p.name)
def test_each_surface_names_a_reference_to_beat(path):
    text = path.read_text()
    section = re.search(r"^## Reference to beat\n(.*?)(?=^#{1,3} |\Z)", text, re.S | re.M)
    assert section, f"{path}: no Reference to beat"
    assert re.search(r"(https?://|talks#|`conventions\.md`)", section[1]), path


@pytest.mark.parametrize("skill, files", LOADERS.items(), ids=list(LOADERS))
def test_each_skill_loads_its_surface(skill, files):
    text = (ROOT / skill).read_text()
    for name in files:
        assert f"_shared/lessons/{name}" in text, f"{skill} never loads {name}"


def test_a_public_lesson_names_no_private_repo():
    # The repository's own guard covers names from `gh`; this covers the shape of a reference.
    for f in FILES:
        for ref in re.findall(r"\b([a-z][a-z0-9-]*)#\d+", f.read_text()):
            assert ref in {"talks", "techne", "keryx", "klepsydra", "kourai"}, f"{f}: {ref}#"
