# tests/test_heuresis_store.py
"""Idea files: ids, round-trips, validation, verdict log."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import pytest
from heuresis import store
from heuresis.model import Coverage, Idea, Verdict

DAY = dt.date(2026, 10, 15)


def idea(**kw: Any) -> Idea:
    base: dict[str, Any] = dict(
        id="2026-10-15-idea-triage-tool",
        title="Idea triage tool",
        captured="2026-10-15T14:02:00-04:00",
        captured_via="terminal",
        sections={"Idea": "An idea triage tool."},
    )
    base.update(kw)
    return Idea(**base)


def test_slugify_keeps_six_words_and_ascii():
    assert (
        store.slugify("A tool: that triages ideas, fast & well!")
        == "a-tool-that-triages-ideas-fast"
    )
    assert store.slugify("¿?") == "idea"


def test_new_id_appends_a_counter_on_collision():
    taken = {"2026-10-15-idea-triage-tool", "2026-10-15-idea-triage-tool-2"}
    assert store.new_id(DAY, "Idea triage tool", taken) == "2026-10-15-idea-triage-tool-3"


def test_title_from_takes_first_line_and_caps_length():
    assert store.title_from("  First line here\nsecond") == "First line here"
    assert len(store.title_from("x" * 200)) == 80


HOSTILE = '---\nkey: "value"\n## Restated\n- emoji 🚀 and 漢字\n```\ncode\n```'


def test_round_trip_preserves_hostile_idea_text_and_title():
    original = idea(title='Title: with "quotes" #1', sections={"Idea": HOSTILE})
    back = store.parse(store.render(original))
    assert back.title == original.title
    assert back.sections["Idea"] == HOSTILE
    assert "Restated" not in back.sections


def test_parse_coerces_unquoted_yaml_dates_to_strings():
    text = store.render(idea(state="later", revisit="2027-01-15"))
    text = text.replace("'2027-01-15'", "2027-01-15").replace(
        "'2026-10-15T14:02:00-04:00'", "2026-10-15T14:02:00-04:00"
    )
    back = store.parse(text)
    assert back.revisit == "2027-01-15"
    assert back.captured.startswith("2026-10-15T14:02:00")


def test_parse_rejects_missing_front_matter():
    with pytest.raises(store.StoreError):
        store.parse("# no front matter\n")


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"state": "maybe"}, "state"),
        ({"captured_via": "fax"}, "captured_via"),
        ({"state": "do"}, "type"),
        ({"state": "merged"}, "duplicate_of"),
        ({"state": "later"}, "revisit"),
        ({"state": "later", "revisit": "soon"}, "revisit"),
        ({"type": "gadget"}, "type"),
    ],
)
def test_validate_reports_each_rule(changes, message):
    errors = store.validate(idea(**changes))
    assert any(message in e for e in errors), errors


def test_validate_checks_id_matches_filename():
    assert store.validate(idea(), stem="other") == [
        "id 2026-10-15-idea-triage-tool does not match file name other"
    ]


def test_save_and_load_all_skip_nothing_and_report_bad_files(tmp_path: Path):
    store.save(tmp_path, idea())
    ideas = tmp_path / "ideas"
    (ideas / "broken.md").write_text("not an idea")
    good_text = store.render(idea(id="x"))
    (ideas / "listy.md").write_text(good_text.replace("revisit_on: []", "revisit_on: 5"))
    (ideas / "dated.md").write_text(good_text.replace("related: []", "related: 2027-01-01"))
    (ideas / "binary.md").write_bytes(b"\xff\xfe not utf-8 \x80")
    rows = {p.name: (i, msg) for p, i, msg in store.load_all(tmp_path)}
    assert rows["2026-10-15-idea-triage-tool.md"][0] is not None
    for name in ("broken.md", "listy.md", "dated.md", "binary.md"):
        assert rows[name][0] is None and rows[name][1], name


@pytest.mark.parametrize("marker", [store.IDEA_START, store.IDEA_END])
def test_render_and_save_refuse_marker_lines(tmp_path: Path, marker: str):
    bad = idea(sections={"Idea": f"before\n{marker}\nafter"})
    with pytest.raises(store.StoreError, match="marker"):
        store.render(bad)
    with pytest.raises(store.StoreError):
        store.save(tmp_path, bad)
    assert not (tmp_path / "ideas").exists()


def test_save_new_never_overwrites(tmp_path: Path):
    a = idea(sections={"Idea": "first"})
    b = idea(sections={"Idea": "second"})
    pa = store.save(tmp_path, a, new=True)
    pb = store.save(tmp_path, b, new=True)
    assert pa != pb
    assert b.id == "2026-10-15-idea-triage-tool-2"
    assert store.load(pa).sections["Idea"] == "first"
    assert store.load(pb).sections["Idea"] == "second"


def test_load_strips_bom_and_parse_accepts_padded_closing_fence(tmp_path: Path):
    text = store.render(idea())
    path = tmp_path / "bom.md"
    path.write_bytes(b"\xef\xbb\xbf" + text.encode())
    assert store.load(path).id == "2026-10-15-idea-triage-tool"
    padded = text.replace("\n---\n", "\n---  \t\n", 1)
    assert padded != text
    assert store.parse(padded).sections["Idea"] == "An idea triage tool."


def test_add_verdict_prepends_newest_first_and_sets_fields():
    target = idea()
    first = Verdict(
        date="2026-10-15", origin="triage", state="later", reason="r1", revisit="2027-01-15"
    )
    second = Verdict(
        date="2026-10-20",
        origin="override",
        state="do",
        reason="r2",
        type="tool",
        project="techne",
        coverage=[Coverage("openalex", "ok", 3, 8), Coverage("epo", "skipped", note="no EPO key")],
        dropped=["https://x.example (quote not found)"],
    )
    store.add_verdict(target, first)
    store.add_verdict(target, second)
    log = target.sections["Verdict log"]
    assert log.index("2026-10-20 · override · do") < log.index("2026-10-15 · triage · later")
    assert "openalex: ok, 3 queries, 8 hits" in log
    assert "quote not found" in log
    assert "**Patents:** not searched (no EPO key)" in log
    assert (target.state, target.type, target.project) == ("do", "tool", "techne")
    assert [m.group(3) for m in store.VERDICT_HEADING.finditer(log)] == ["do", "later"]


HAND_EDITED = """---
id: 2026-10-15-idea-triage-tool
title: Idea triage tool
captured: '2026-10-15T14:02:00-04:00'
captured_via: terminal
---

# Idea triage tool

A stray line AJ typed under the title.

## Idea

Text above the start marker.

<!-- idea:start -->
An idea triage tool.
<!-- idea:end -->

Text below the end marker.

## Restated

Neutral.

## My own thoughts

Ask Dima about $5 pricing.
- a `list` item

## Verdict log

### 2026-10-15 · triage · later

- **Reason:** thin.
"""
STRAYS = (
    "A stray line AJ typed under the title.",
    "Text above the start marker.",
    "Text below the end marker.",
    "## My own thoughts\n\nAsk Dima about $5 pricing.\n- a `list` item",
)


def _chars(text: str) -> list[str]:
    """Non-whitespace characters of the body, below the front matter heuresis rewrites."""
    return sorted(c for c in text[text.find("\n---\n", 3) :] if not c.isspace())


def test_parse_keeps_hand_edited_text_in_notes_through_round_trips(tmp_path: Path):
    parsed = store.parse(HAND_EDITED)
    notes = parsed.sections["Notes"]
    positions = [notes.index(s) for s in STRAYS]
    assert positions == sorted(positions)
    assert parsed.sections["Idea"] == "An idea triage tool."
    assert parsed.sections["Restated"] == "Neutral."
    rendered = store.render(parsed)
    for s in STRAYS:
        assert s in rendered
    # Every non-whitespace character survives; only the Notes heading is added.
    assert _chars(rendered) == sorted(_chars(HAND_EDITED) + list("##Notes"))
    again = store.parse(rendered)
    assert again.sections == parsed.sections
    assert store.render(again) == rendered
    path = tmp_path / "ideas" / f"{parsed.id}.md"
    path.parent.mkdir()
    path.write_text(HAND_EDITED)
    loaded = store.load(path)
    store.add_verdict(
        loaded, Verdict(date="2026-10-16", origin="override", state="trash", reason="x")
    )
    store.save(tmp_path, loaded)
    for s in STRAYS:
        assert s in path.read_text()


@pytest.mark.parametrize(
    ("status", "line"),
    [
        ("skipped", "- **Patents:** not searched (no EPO key)."),
        ("ok", "- **Patents:** partial; only what EPO indexes was searched."),
        ("failed", "- **Patents:** partial; only what EPO indexes was searched."),
    ],
)
def test_patents_line_says_whether_a_patent_source_ran(status, line):
    coverage = [Coverage("epo", status)]
    text = store.render_verdict(
        Verdict(date="2026-10-15", origin="triage", state="later", reason="r", coverage=coverage)
    )
    patents = [x for x in text.splitlines() if x.startswith("- **Patents:**")]
    assert patents == [line]


def test_no_patents_line_without_patent_coverage():
    v = Verdict(
        date="d", origin="triage", state="later", reason="r", coverage=[Coverage("x", "ok")]
    )
    assert "Patents" not in store.render_verdict(v)


def test_headings_after_notes_stay_in_notes():
    notes = "mine\n\n## Product evidence\n\nhand"
    parsed = store.parse(store.render(idea(sections={"Idea": "x", "Notes": notes})))
    assert "Product evidence" not in parsed.sections
    assert parsed.sections["Notes"] == notes


def test_verdict_heading_accepts_each_origin_and_nothing_else():
    entry = "### 2026-10-17 · {} · trash"
    for origin in ("triage", "override", "declined"):
        assert store.VERDICT_HEADING.search(entry.format(origin))
    assert not store.VERDICT_HEADING.search(entry.format("forged"))


def test_a_decline_keeps_the_type_and_project_it_does_not_name():
    i = idea(type="tool", project="techne")
    store.add_verdict(i, Verdict(date="2026-10-17", origin="declined", state="trash", reason="r"))
    assert (i.state, i.type, i.project) == ("trash", "tool", "techne")
