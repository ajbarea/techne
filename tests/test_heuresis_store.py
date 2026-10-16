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
    good = idea()
    store.save(tmp_path, good)
    (tmp_path / "ideas" / "broken.md").write_text("not an idea")
    rows = store.load_all(tmp_path)
    assert [(p.name, i is not None) for p, i, _ in rows] == [
        ("2026-10-15-idea-triage-tool.md", True),
        ("broken.md", False),
    ]


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
        coverage=[Coverage("openalex", "ok", 3, 8), Coverage("lens", "skipped", note="no token")],
        dropped=["https://x.example (quote not found)"],
    )
    store.add_verdict(target, first)
    store.add_verdict(target, second)
    log = target.sections["Verdict log"]
    assert log.index("2026-10-20 · override · do") < log.index("2026-10-15 · triage · later")
    assert "openalex: ok, 3 queries, 8 hits" in log
    assert "quote not found" in log
    assert "**Patents:** partial" in log
    assert (target.state, target.type, target.project) == ("do", "tool", "techne")
    assert [m.group(3) for m in store.VERDICT_HEADING.finditer(log)] == ["do", "later"]
