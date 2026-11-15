"""graphe:vids `check_script.py`: the Vids script lint, one rule per test."""

# ruff: noqa: RUF001  # segment spans use an en dash, as the lint expects
from __future__ import annotations

import importlib.util
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "vids_check_script",
    ROOT / "plugins" / "graphe" / "skills" / "vids" / "scripts" / "check_script.py",
)
assert _spec and _spec.loader
cs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cs)


def segment(n: int, span: str, spoken: str = "Short line.", extra: str = "") -> str:
    return (
        f"### Segment {n} ({span}): Title\n"
        "- **Environment & Lighting:** a desert ramp at sunset, close-up.\n"
        "- **Avatar (Wardrobe & Physicality):** orange jersey, black shorts, helmet.\n"
        "- **Visual Overlay:** None.\n"
        f'- **Spoken Script:** "{spoken}"\n'
        f"- **Vocal Direction:** flat and dry.{extra}\n"
    )


def messages(text: str) -> list[str]:
    return [m for _, m in cs.check(text)]


def test_a_clean_two_segment_script_passes():
    assert cs.check(segment(1, "0:00 – 0:12") + segment(2, "0:12 – 0:24")) == []


def test_a_script_with_no_segments_is_refused():
    assert messages("# Title\nno segments here\n")


def test_a_heading_without_a_span_is_flagged():
    assert any("span" in m for m in messages(segment(1, "soon")))


def test_a_clip_longer_than_the_cap_is_flagged():
    assert any("a clip is 1 to" in m for m in messages(segment(1, "0:00 – 0:20")))


def test_a_backwards_span_is_flagged_once_and_not_timed():
    out = messages(segment(1, "0:20 – 0:10"))
    assert any("runs backwards" in m for m in out)
    assert not any("-" in m.split(";")[0] for m in out if "segment runs" in m)
    assert not any("spoken line needs" in m for m in out)


def test_a_spoken_line_too_long_for_its_clip_is_flagged():
    long_line = " ".join(["word"] * 60)
    assert any("spoken line needs" in m for m in messages(segment(1, "0:00 – 0:15", long_line)))


def test_a_gap_between_segments_is_flagged():
    out = messages(segment(1, "0:00 – 0:10") + segment(2, "0:12 – 0:20"))
    assert any("but the one before ends" in m for m in out)


def test_a_direction_inside_the_quotes_is_flagged():
    assert any(
        "[direction]" in m for m in messages(segment(1, "0:00 – 0:10", "Hi [smiles] there."))
    )


def test_a_second_quoted_span_in_the_spoken_line_is_flagged():
    text = segment(1, "0:00 – 0:10").replace('"Short line."', '"Short line." and "again."')
    assert any("exactly one double-quoted span" in m for m in messages(text))


def test_double_quotes_in_another_field_are_flagged():
    out = messages(segment(1, "0:00 – 0:10", extra=' Then say "again".'))
    assert any("double quotes in Vocal Direction" in m for m in out)


def test_double_quotes_on_a_loose_line_are_flagged():
    text = segment(1, "0:00 – 0:10").replace(
        "): Title\n", '): Title\nA stray note with "quotes".\n'
    )
    assert any("outside the spoken line" in m for m in messages(text))


def test_double_quotes_in_the_heading_are_flagged():
    text = segment(1, "0:00 – 0:10").replace("Title", '"Title"')
    assert any("in the heading" in m for m in messages(text))


def test_a_pointer_to_another_segment_is_flagged():
    text = segment(1, "0:00 – 0:10").replace("a desert ramp at sunset", "same as Segment 2")
    assert any("points elsewhere" in m for m in messages(text))


def test_a_gesture_time_outside_its_segment_is_flagged():
    text = segment(1, "0:00 – 0:10").replace("helmet.", "helmet. At 0:14, waves.")
    assert any("falls outside this segment" in m for m in messages(text))


def test_a_gesture_time_inside_its_segment_passes():
    text = segment(1, "0:00 – 0:10").replace("helmet.", "helmet. At 0:04, waves.")
    assert cs.check(text) == []


def test_a_lookalike_heading_is_flagged():
    text = segment(1, "0:00 – 0:10") + "## Clip 2 (0:10 – 0:20): Next\n"
    assert any("looks like a segment heading" in m for m in messages(text))


def test_the_timing_is_150_words_a_minute_with_a_second_to_spare():
    fits = " ".join(["word"] * 35)  # 14.0 s at 150 wpm, inside 15 - 1
    over = " ".join(["word"] * 36)  # 14.4 s
    assert not any("spoken line needs" in m for m in messages(segment(1, "0:00 – 0:15", fits)))
    assert any("spoken line needs" in m for m in messages(segment(1, "0:00 – 0:15", over)))


@pytest.mark.parametrize(
    "field",
    [
        "Environment & Lighting",
        "Avatar (Wardrobe & Physicality)",
        "Visual Overlay",
        "Spoken Script",
        "Vocal Direction",
    ],
)
def test_a_missing_field_is_flagged(field):
    lines = [
        ln
        for ln in segment(1, "0:00 – 0:10").splitlines(keepends=True)
        if f"**{field}:**" not in ln
    ]
    assert any(f"missing {field}" in m for m in messages("".join(lines)))


def test_segment_one_may_restart_the_clock_for_a_second_cut():
    long_cut = segment(1, "0:00 – 0:10") + segment(2, "0:10 – 0:20")
    short_cut = segment(1, "0:00 – 0:12").replace("Segment 1", "Segment S1")
    assert cs.check(long_cut + short_cut) == []


def test_main_needs_a_path(capsys):
    assert cs.main([]) == 2
    assert "usage" in capsys.readouterr().err


def test_main_reports_a_missing_file(tmp_path):
    assert cs.main([str(tmp_path / "nope.md")]) == 1


@pytest.mark.parametrize("data", [b"\xff\xfe\x00bad", b"caf\xe9"])
def test_main_reports_non_utf8_without_a_traceback(tmp_path, capsys, data):
    p = tmp_path / "bad.md"
    p.write_bytes(data)
    assert cs.main([str(p)]) == 1
    assert "not UTF-8" in capsys.readouterr().err


def test_main_passes_a_clean_file(tmp_path, capsys):
    p = tmp_path / "ok.md"
    p.write_text(segment(1, "0:00 – 0:12"), encoding="utf-8")
    assert cs.main([str(p)]) == 0
    assert "ok" in capsys.readouterr().out


def test_a_number_is_timed_one_slot_per_two_digits():
    assert cs.spoken_seconds("2025") == cs.spoken_seconds("twenty twenty-five")
