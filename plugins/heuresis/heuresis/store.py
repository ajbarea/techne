"""Read, write and validate idea files: YAML front matter plus fixed Markdown sections."""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Iterable
from pathlib import Path

import yaml

from heuresis.model import CAPTURED_VIA, PATENT_SOURCES, SECTIONS, STATES, TYPES, Idea, Verdict

FRONT_KEYS = (
    "id",
    "title",
    "captured",
    "captured_via",
    "state",
    "type",
    "project",
    "duplicate_of",
    "revisit",
    "revisit_on",
    "related",
)
REQUIRED = ("id", "title", "captured", "captured_via")
TITLE_MAX = 80
# Sections split only on the known headings, so a "## " line inside the idea text stays text.
_SECTION = re.compile(r"^## (" + "|".join(re.escape(s) for s in SECTIONS) + r")$", re.MULTILINE)
VERDICT_HEADING = re.compile(r"^### (\d{4}-\d{2}-\d{2}) · (triage|override) · (\w+)$", re.MULTILINE)
NEEDS_TYPE = ("do", "building", "shipped")
# The idea text is AJ's, verbatim, so it may hold any heading; markers fence it off from the
# section split. GitHub hides HTML comments when rendering.
IDEA_START, IDEA_END = "<!-- idea:start -->", "<!-- idea:end -->"


class StoreError(Exception):
    """An idea file that cannot be read."""


def slugify(text: str) -> str:
    words = re.findall(r"[a-z0-9]+", text.lower())[:6]
    return "-".join(words)[:60].strip("-") or "idea"


def new_id(day: dt.date, title: str, taken: Iterable[str]) -> str:
    base = f"{day.isoformat()}-{slugify(title)}"
    used = set(taken)
    candidate, n = base, 2
    while candidate in used:
        candidate, n = f"{base}-{n}", n + 1
    return candidate


def title_from(text: str) -> str:
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    return first[:TITLE_MAX]


def idea_path(root: Path, idea_id: str) -> Path:
    return root / "ideas" / f"{idea_id}.md"


def render(idea: Idea) -> str:
    front = {key: getattr(idea, key) for key in FRONT_KEYS}
    head = yaml.safe_dump(front, sort_keys=False, allow_unicode=True, width=1000)
    parts = [f"---\n{head}---\n\n# {idea.title}\n"]
    for name in SECTIONS:
        body = idea.sections.get(name, "").strip("\n")
        if name == "Idea":
            parts.append(f"\n## Idea\n\n{IDEA_START}\n{body}\n{IDEA_END}\n")
        elif body:
            parts.append(f"\n## {name}\n\n{body}\n")
    return "".join(parts)


def _text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, dt.datetime | dt.date):
        return value.isoformat()
    return str(value)


def parse(text: str) -> Idea:
    if not text.startswith("---\n"):
        raise StoreError("no front matter")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise StoreError("front matter is not closed")
    try:
        front = yaml.safe_load(text[4:end]) or {}
    except yaml.YAMLError as exc:
        raise StoreError(f"front matter is not valid YAML: {exc}") from exc
    if not isinstance(front, dict):
        raise StoreError("front matter is not a mapping")
    missing = [key for key in REQUIRED if not front.get(key)]
    if missing:
        raise StoreError("front matter lacks " + ", ".join(missing))
    body = text[end + 5 :]
    sections = {}
    start, stop = body.find(IDEA_START), body.find(IDEA_END)
    if 0 <= start < stop:
        sections["Idea"] = body[start + len(IDEA_START) : stop].strip("\n")
        body = body[:start] + body[stop + len(IDEA_END) :]
    matches = list(_SECTION.finditer(body))
    for i, match in enumerate(matches):
        stop = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        if match.group(1) != "Idea" or "Idea" not in sections:
            sections[match.group(1)] = body[match.end() : stop].strip("\n")
    return Idea(
        id=str(front["id"]),
        title=str(front["title"]),
        captured=_text(front["captured"]) or "",
        captured_via=str(front["captured_via"]),
        state=str(front.get("state") or "inbox"),
        type=_text(front.get("type")),
        project=_text(front.get("project")),
        duplicate_of=_text(front.get("duplicate_of")),
        revisit=_text(front.get("revisit")),
        revisit_on=[str(v) for v in front.get("revisit_on") or []],
        related=[str(v) for v in front.get("related") or []],
        sections=sections,
    )


def validate(idea: Idea, stem: str | None = None) -> list[str]:
    errors = []
    if stem is not None and stem != idea.id:
        errors.append(f"id {idea.id} does not match file name {stem}")
    if idea.state not in STATES:
        errors.append(f"state {idea.state!r} is not one of {', '.join(STATES)}")
    if idea.captured_via not in CAPTURED_VIA:
        errors.append(f"captured_via {idea.captured_via!r} is not one of {', '.join(CAPTURED_VIA)}")
    if idea.type is not None and idea.type not in TYPES:
        errors.append(f"type {idea.type!r} is not one of {', '.join(TYPES)}")
    if idea.state in NEEDS_TYPE and idea.type is None:
        errors.append(f"state {idea.state} needs a type")
    if idea.state == "merged" and not idea.duplicate_of:
        errors.append("state merged needs duplicate_of")
    if idea.state == "later" and not idea.revisit:
        errors.append("state later needs a revisit date")
    if idea.revisit:
        try:
            dt.date.fromisoformat(idea.revisit)
        except ValueError:
            errors.append(f"revisit {idea.revisit!r} is not a YYYY-MM-DD date")
    return errors


def load(path: Path) -> Idea:
    return parse(path.read_text(encoding="utf-8"))


def save(root: Path, idea: Idea) -> Path:
    path = idea_path(root, idea.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(idea), encoding="utf-8")
    return path


def load_all(root: Path) -> list[tuple[Path, Idea | None, str]]:
    rows = []
    for path in sorted((root / "ideas").glob("*.md")):
        try:
            rows.append((path, load(path), ""))
        except StoreError as exc:
            rows.append((path, None, str(exc)))
    return rows


def render_verdict(v: Verdict) -> str:
    lines = [f"### {v.date} · {v.origin} · {v.state}", ""]
    if v.type or v.project:
        lines.append(f"- **Type:** {v.type or 'none'}. **Project:** {v.project or 'none'}.")
    lines.append(f"- **Reason:** {v.reason}")
    if v.next_step:
        lines.append(f"- **Next step:** {v.next_step}")
    if v.duplicate_of:
        lines.append(f"- **Duplicate of:** {v.duplicate_of}")
    if v.revisit:
        lines.append(f"- **Revisit:** {v.revisit}")
    if v.coverage:
        lines.append("- **Coverage:** " + "; ".join(c.line() for c in v.coverage))
    if any(c.source in PATENT_SOURCES for c in v.coverage):
        lines.append("- **Patents:** partial; only what Lens and EPO index was searched.")
    if v.dropped:
        lines.append("- **Dropped:** " + "; ".join(v.dropped))
    return "\n".join(lines)


def add_verdict(idea: Idea, v: Verdict) -> None:
    previous = idea.sections.get("Verdict log", "").strip("\n")
    entry = render_verdict(v)
    idea.sections["Verdict log"] = f"{entry}\n\n{previous}" if previous else entry
    idea.state = v.state
    idea.type = v.type or idea.type
    idea.project = v.project or idea.project
    idea.duplicate_of = v.duplicate_of
    idea.revisit = v.revisit if v.state == "later" else None
