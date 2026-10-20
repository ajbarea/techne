"""End-to-end tests for graphe:pdf against a real Typst compile.

These need the typst wheel, and the first compile fetches cmarker from Typst
Universe. CI declines that network dependency and says so with
TECHNE_NO_TYPST=1; without the declaration a machine that cannot compile fails
here rather than reporting a green run that rendered nothing.
"""

from __future__ import annotations

import importlib.util
import os
import shutil

import pytest

OPTED_OUT = os.environ.get("TECHNE_NO_TYPST") == "1"
HAVE_TYPST = importlib.util.find_spec("typst") is not None
HAVE_POPPLER = shutil.which("pdftotext") is not None

needs_typst = pytest.mark.skipif(
    OPTED_OUT or not HAVE_TYPST,
    reason="opted out of typst compiles" if OPTED_OUT else "typst wheel not importable",
)

DOC = """# Quarterly Notes

*How the quarter went*

The headline number is forty-two.

| Metric | Value |
| --- | --- |
| Throughput | 42 |
"""


def test_the_compiler_is_present_or_its_absence_is_declared():
    """Green by absence is the failure this guards."""
    if HAVE_TYPST and not OPTED_OUT:
        return
    assert OPTED_OUT, (
        "the typst wheel is not importable and TECHNE_NO_TYPST is unset: the "
        "end-to-end renders would have skipped silently. Run the suite through "
        "`make test-unit`, or set TECHNE_NO_TYPST=1 to opt out on purpose."
    )


@needs_typst
def test_a_markdown_file_renders_to_a_real_pdf(rn, tmp_path):
    src = tmp_path / "notes.md"
    src.write_text(DOC)
    out = tmp_path / "out"
    out.mkdir()
    dest, fonts = rn.render(src, out)

    assert dest.exists()
    assert dest.read_bytes()[:5] == b"%PDF-"
    assert fonts, "no embedded families were read back"


@needs_typst
@pytest.mark.skipif(not HAVE_POPPLER, reason="pdftotext not installed")
def test_the_words_survive_the_round_trip(rn, tmp_path):
    """The skill's documented verification: diff the text, do not eyeball it."""
    import subprocess

    src = tmp_path / "notes.md"
    src.write_text(DOC)
    out = tmp_path / "out"
    out.mkdir()
    dest, _ = rn.render(src, out)

    text = subprocess.run(
        ["pdftotext", "-layout", str(dest), "-"], capture_output=True, text=True
    ).stdout
    for word in ("Quarterly Notes", "How the quarter went", "forty-two", "Throughput"):
        assert word in text, f"{word!r} did not survive the render"


WRAPPED = " ".join(["wrapword"] * 120)

LISTS = f"""# Lists

Paraone sits alone.

Paratwo sits alone.

- tightone
- tighttwo

Paramid sits alone.

- looseone

- loosetwo

Paramid again.

3. enumthree

4. enumfour

Paramid once more.

- quoteone
  > aside
- quotetwo
- quotethree

{WRAPPED}
"""


def _line_tops(pdf) -> dict[str, list[float]]:
    """yMin of each word's line, by word, from poppler's per-word boxes."""
    import re
    import subprocess

    boxes = subprocess.run(
        ["pdftotext", "-bbox", str(pdf), "-"], capture_output=True, text=True, check=True
    ).stdout
    tops: dict[str, list[float]] = {}
    for y, word in re.findall(r'yMin="([0-9.]+)"[^>]*>([^<]*)</word>', boxes):
        tops.setdefault(word, []).append(float(y))
    return tops


@needs_typst
@pytest.mark.skipif(not HAVE_POPPLER, reason="pdftotext not installed")
def test_tight_lists_sit_on_the_leading_and_loose_ones_take_paragraph_spacing(rn, tmp_path):
    """cmarker marks every list tight; the template has to tell a loose one apart."""
    src = tmp_path / "lists.md"
    src.write_text(LISTS)
    out = tmp_path / "out"
    out.mkdir()
    dest, _ = rn.render(src, out)
    tops = _line_tops(dest)

    wrapped = sorted(set(tops["wrapword"]))
    assert len(wrapped) >= 2, "the long paragraph did not wrap, so there is no line pitch"
    line = wrapped[1] - wrapped[0]
    paragraph = tops["Paratwo"][0] - tops["Paraone"][0]
    assert paragraph > line + 1

    assert tops["tighttwo"][0] - tops["tightone"][0] == pytest.approx(line, abs=0.05)
    assert tops["loosetwo"][0] - tops["looseone"][0] == pytest.approx(paragraph, abs=0.05)
    assert tops["enumfour"][0] - tops["enumthree"][0] == pytest.approx(paragraph, abs=0.05)
    assert "3." in tops and "4." in tops, "re-emitting the loose enum lost its start number"
    # cmarker follows a blockquote with a parbreak even in a tight list.
    assert tops["quotethree"][0] - tops["quotetwo"][0] == pytest.approx(line, abs=0.05)


@needs_typst
def test_a_labeled_loose_list_still_compiles(rn, tmp_path):
    """The re-emit cannot pass `label` back to the constructor."""
    src = tmp_path / "labeled.md"
    src.write_text("# Labeled\n\n<!--raw-typst #list([a\n\n], [b\n\n]) <lab> -->\n")
    out = tmp_path / "out"
    out.mkdir()
    dest, _ = rn.render(src, out)
    assert dest.exists()


@needs_typst
def test_font_drift_is_caught_against_a_real_render(rn, tmp_path):
    """The gate that catches a machine where a requested family is missing."""
    src = tmp_path / "notes.md"
    src.write_text(DOC)
    assert rn.main([str(src), str(tmp_path / "out"), "--check-fonts", "NoSuchFamily"]) == 1


@needs_typst
def test_the_families_a_run_reports_are_the_ones_it_embedded(rn, tmp_path):
    src = tmp_path / "notes.md"
    src.write_text(DOC)
    out = tmp_path / "out"
    out.mkdir()
    _, fonts = rn.render(src, out)
    assert rn.main([str(src), str(out), "--check-fonts", *fonts]) == 0


HEADERS = """# Table

| Case | Mutation | Tests |
| --- | --- | --- |
| one | two | three |
"""


@needs_typst
@pytest.mark.skipif(not HAVE_POPPLER, reason="pdftotext not installed")
def test_table_header_labels_keep_a_gap_between_columns(rn, tmp_path):
    """A function show rule on a header cell drops its inset and runs the labels together."""
    import re
    import subprocess

    src = tmp_path / "headers.md"
    src.write_text(HEADERS)
    out = tmp_path / "out"
    out.mkdir()
    dest, _ = rn.render(src, out)

    text = subprocess.run(
        ["pdftotext", "-layout", str(dest), "-"], capture_output=True, text=True
    ).stdout
    assert re.search(r"CASE\s+MUTATION\s+TESTS", text), text
