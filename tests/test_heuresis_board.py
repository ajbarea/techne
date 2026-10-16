"""BOARD.md orders by what needs a decision; LOG.md lists every verdict, newest first."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from heuresis import board, store
from heuresis.model import Idea, Verdict

TODAY = dt.date(2026, 10, 15)


def make(root: Path, idea_id: str, **kw) -> Idea:
    i = Idea(
        id=idea_id,
        title=kw.pop("title", idea_id),
        captured="2026-10-01T00:00:00",
        captured_via="terminal",
        **kw,
    )
    i.sections["Idea"] = "text"
    store.save(root, i)
    return i


def test_board_sections_in_decision_order(tmp_path: Path):
    make(tmp_path, "a-inbox")
    make(tmp_path, "b-due", state="later", revisit="2026-10-01")
    make(tmp_path, "c-later", state="later", revisit="2027-01-01")
    make(tmp_path, "d-do", state="do", type="tool", project="techne")
    make(tmp_path, "e-trash", state="trash")
    make(tmp_path, "f-merged", state="merged", duplicate_of="d-do")
    (tmp_path / "ideas" / "g-broken.md").write_text("junk")
    text = board.render_board(store.load_all(tmp_path), TODAY)
    order = ["## Needs triage", "## Due for revisit", "## Do", "## Later", "## Closed"]
    assert [text.index(h) for h in order] == sorted(text.index(h) for h in order)
    needs = text[text.index("## Needs triage") : text.index("## Due for revisit")]
    assert "a-inbox" in needs and "g-broken.md" in needs
    assert "b-due" in text[text.index("## Due for revisit") : text.index("## Do")]
    assert "### techne" in text and "d-do" in text
    assert "c-later" in text[text.index("## Later") : text.index("## Closed")]
    assert "Trash: 1" in text and "Merged: 1" in text


def test_board_flags_invalid_ideas_under_needs_triage(tmp_path: Path):
    make(tmp_path, "h-bad", state="do")  # do without a type
    text = board.render_board(store.load_all(tmp_path), TODAY)
    needs = text[text.index("## Needs triage") : text.index("## Due for revisit")]
    assert "h-bad" in needs and "needs a type" in needs


def test_log_lists_verdicts_newest_first(tmp_path: Path):
    a = make(tmp_path, "a")
    store.add_verdict(
        a, Verdict(date="2026-10-02", origin="triage", state="trash", reason="exists")
    )
    store.save(tmp_path, a)
    b = make(tmp_path, "b")
    store.add_verdict(
        b, Verdict(date="2026-10-05", origin="override", state="do", reason="mine", type="tool")
    )
    store.save(tmp_path, b)
    text = board.render_log(store.load_all(tmp_path))
    assert text.index("2026-10-05") < text.index("2026-10-02")
    assert "[b](ideas/b.md) · override · do" in text


def test_write_creates_both_files(tmp_path: Path):
    make(tmp_path, "a")
    paths = board.write(tmp_path, TODAY)
    assert [p.name for p in paths] == list(board.GENERATED)
    assert all(p.is_file() for p in paths)
