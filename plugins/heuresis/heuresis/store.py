"""Read, write and validate idea files: YAML front matter plus fixed Markdown sections.

The Idea text is stored with surrounding blank lines trimmed and line endings normalized to LF.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Iterable
from pathlib import Path

import yaml

from heuresis.model import (
    CAPTURED_VIA,
    NOTES,
    PATENT_SOURCES,
    SECTIONS,
    STATES,
    TYPES,
    Idea,
    Verdict,
)

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
NEW_ATTEMPTS = 100
# The shape new_id produces; anything built into a path from outside input must match it.
IDEA_ID = re.compile(r"\d{4}-\d{2}-\d{2}-[a-z0-9-]+")
# The idea text is cut out before this split, so a "## " line inside it stays idea text.
_HEADING = re.compile(r"^## (.+?)[ \t]*$", re.MULTILINE)
VERDICT_HEADING = re.compile(r"^### (\d{4}-\d{2}-\d{2}) · (triage|override) · (\w+)$", re.MULTILINE)
_CLOSING_FENCE = re.compile(r"\n---[ \t]*\n")
NEEDS_TYPE = ("do", "building", "shipped")
# The idea text is the user's, verbatim, so it may hold any heading; markers fence it off from the
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
    idea_body = idea.sections.get("Idea", "")
    if IDEA_START in idea_body or IDEA_END in idea_body:
        raise StoreError("idea text contains a heuresis marker line; remove it")
    front = {key: getattr(idea, key) for key in FRONT_KEYS}
    head = yaml.safe_dump(front, sort_keys=False, allow_unicode=True, width=1000)
    parts = [f"---\n{head}---\n\n# {idea.title}\n"]
    for name in SECTIONS:
        body = idea.sections.get(name, "").replace("\r\n", "\n").strip("\n")
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
    text = text.removeprefix("\ufeff").replace("\r\n", "\n")
    if not text.startswith("---\n"):
        raise StoreError("no front matter")
    fence = _CLOSING_FENCE.search(text, 3)
    if fence is None:
        raise StoreError("front matter is not closed")
    end = fence.start()
    try:
        front = yaml.safe_load(text[4:end]) or {}
    except yaml.YAMLError as exc:
        raise StoreError(f"front matter is not valid YAML: {exc}") from exc
    if not isinstance(front, dict):
        raise StoreError("front matter is not a mapping")
    missing = [key for key in REQUIRED if not front.get(key)]
    if missing:
        raise StoreError("front matter lacks " + ", ".join(missing))
    body = text[fence.end() :]
    for key in ("revisit_on", "related"):
        if front.get(key) is not None and not isinstance(front[key], list):
            raise StoreError(f"{key} must be a list")
    sections = _sections(body, str(front["title"]))
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


def _sections(body: str, title: str) -> dict[str, str]:
    """Known sections by name; every other non-blank piece of text goes to Notes, in order."""
    sections: dict[str, str] = {}
    notes: list[str] = []
    start, stop = body.find(IDEA_START), body.find(IDEA_END)
    marked = 0 <= start < stop
    if marked:
        sections["Idea"] = body[start + len(IDEA_START) : stop].strip("\n")
        body = body[:start] + body[stop + len(IDEA_END) :]
    matches = list(_HEADING.finditer(body))
    preamble = body[: matches[0].start() if matches else len(body)].split("\n")
    first = next((i for i, line in enumerate(preamble) if line.strip()), None)
    if first is not None and preamble[first].rstrip() == f"# {title}":
        del preamble[first]  # render writes the title heading from the front matter
    notes.append("\n".join(preamble))
    in_notes = False
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        name, text = match.group(1), body[match.end() : end].strip("\n")
        if in_notes:
            # Notes renders last, so a heading below it is the user's, even one named like a section
            # heuresis rewrites or deletes.
            notes.append(body[match.start() : end])
        elif name == NOTES or (name == "Idea" and marked):
            in_notes = in_notes or name == NOTES
            notes.append(text)  # the heading is rendered; the text under it is the user's
        elif name in SECTIONS and name not in sections:
            sections[name] = text
        else:
            notes.append(body[match.start() : end])
    kept = [n.strip("\n") for n in notes if n.strip()]
    if kept:
        sections[NOTES] = "\n\n".join(kept)
    return sections


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
    try:
        return parse(path.read_text(encoding="utf-8-sig"))
    except UnicodeDecodeError as exc:
        raise StoreError(f"file is not valid UTF-8: {exc}") from exc


def save(root: Path, idea: Idea, *, new: bool = False) -> Path:
    text = render(idea)
    path = idea_path(root, idea.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not new:
        path.write_text(text, encoding="utf-8")
        return path
    for _ in range(NEW_ATTEMPTS):
        try:
            with path.open("x", encoding="utf-8") as handle:
                handle.write(text)
        except FileExistsError:
            taken = [p.stem for p in path.parent.glob("*.md")]
            try:
                day = dt.date.fromisoformat(idea.id[:10])
            except ValueError:
                day = dt.date.today()
            idea.id = new_id(day, idea.title, taken)
            path = idea_path(root, idea.id)
            text = render(idea)
        else:
            return path
    raise StoreError("could not find a free idea id")


def load_all(root: Path) -> list[tuple[Path, Idea | None, str]]:
    rows = []
    for path in sorted((root / "ideas").glob("*.md")):
        try:
            rows.append((path, load(path), ""))
        except StoreError as exc:
            rows.append((path, None, str(exc)))
    return rows


def inert(text: str) -> str:
    """Escape every line that starts with #, so text from a model can never open a heading.

    parse splits sections on headings, so a "## Verdict log" line in a judge's fit would
    otherwise replace the real verdict log on the next read.
    """
    lines = text.replace("\r\n", "\n").split("\n")
    out = []
    for line in lines:
        body = line.lstrip(" \t")
        out.append(line[: len(line) - len(body)] + "\\" + body if body.startswith("#") else line)
    return "\n".join(out)


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
    patents = [c for c in v.coverage if c.source in PATENT_SOURCES]
    if any(c.status != "skipped" for c in patents):
        lines.append("- **Patents:** partial; only what EPO indexes was searched.")
    elif patents:
        lines.append("- **Patents:** not searched (no EPO key).")
    if v.dropped:
        lines.append("- **Dropped:** " + "; ".join(v.dropped))
    return "\n".join([lines[0], inert("\n".join(lines[1:]))])


def add_verdict(idea: Idea, v: Verdict) -> None:
    previous = idea.sections.get("Verdict log", "").strip("\n")
    entry = render_verdict(v)
    idea.sections["Verdict log"] = f"{entry}\n\n{previous}" if previous else entry
    idea.state = v.state
    if v.origin == "triage":  # a triage judges the idea afresh, so what it leaves out is cleared
        idea.type, idea.project = v.type, v.project
    else:  # an override changes only what the user passed
        idea.type = v.type or idea.type
        idea.project = v.project or idea.project
    idea.duplicate_of = v.duplicate_of
    idea.revisit = v.revisit if v.state == "later" else None
