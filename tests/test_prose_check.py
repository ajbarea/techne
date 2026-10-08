"""Unit tests for the shared plain-prose check the latex and pdf gates run.

The patterns live in _shared/plain-prose.md, so the first tests pin that the
block parses at all: a rubric edit that breaks the fence silently disables every
pattern.
"""

from __future__ import annotations

import pathlib

import pytest

REVIEW, INFO = "REVIEW", "INFO"


def names(hits) -> set[str]:
    return {h.name for h in hits}


def test_the_rubric_block_parses_into_every_named_pattern(pc):
    got = {name for name, _ in pc.load_patterns()}
    assert got == {
        "em-dash",
        "throat-clearing",
        "self-commentary",
        "ornate-verb",
        "filler",
        "stacked-hedge",
        "llm-tell",
    }


def test_a_rubric_without_the_block_is_an_error_not_an_empty_list(pc, tmp_path):
    rubric = tmp_path / "plain-prose.md"
    rubric.write_text("# Plain prose\n\nNo patterns here.\n", encoding="utf-8")
    with pytest.raises(ValueError):
        pc.load_patterns(rubric)


@pytest.mark.parametrize(
    ("text", "name"),
    [
        ("The run failed — twice.", "em-dash"),
        ("It is worth noting that the cache was stale.", "throat-clearing"),
        ("This is the paper's least comfortable observation.", "self-commentary"),
        ("We leverage the registry to resolve entries.", "ornate-verb"),
        ("We cache records in order to limit load.", "filler"),
        ("The throttle may potentially recur.", "stacked-hedge"),
    ],
)
def test_each_pattern_fires_on_its_case(pc, text, name):
    assert name in names(pc.check(text))


def test_plain_sentences_raise_nothing(pc):
    text = "The cache held 29 old records. Each one still drifted. Records now carry a version."
    assert pc.check(text) == []


def test_ieeetran_abstract_and_index_terms_dashes_are_not_flagged(pc):
    """IEEEtran sets these dashes itself; the author cannot remove them."""
    text = "Abstract—Checkers catch errors.\n\nIndex Terms—software verification"
    assert "em-dash" not in names(pc.check(text))


def test_hits_are_counted_and_carry_the_first_example(pc):
    hits = pc.check("Leverage one. Then leveraging two.")
    (hit,) = [h for h in hits if h.name == "ornate-verb"]
    assert hit.count == 2
    assert "Leverage one" in hit.example


def test_a_long_sentence_is_reported(pc):
    text = " ".join(["word"] * 45) + "."
    assert "long-sentence" in names(pc.check(text))


def test_the_long_sentence_limit_is_exclusive(pc):
    text = " ".join(["word"] * 40) + "."
    assert "long-sentence" not in names(pc.check(text))


def test_a_title_block_without_a_full_stop_is_not_one_long_sentence(pc):
    """PDF text runs the title, authors and headings together with no full stop.
    Paragraph breaks are the only boundary they have."""
    title = "\n".join(["Checking the Checker Six Silent Failures"] * 10)
    text = title + "\n\nThe first case is short."
    assert "long-sentence" not in names(pc.check(text))


def test_the_reference_list_is_not_prose(pc):
    text = "The body is plain.\n\nREFERENCES\n\n[1] A. Author, It is worth noting, 2020."
    assert pc.check(text) == []


def test_a_word_hyphenated_across_lines_is_rejoined(pc):
    assert pc.body_of("lever-\naged") == "leveraged"


def test_markdown_code_and_link_targets_are_not_prose(pc):
    text = "Run `leverage.py` and see [docs](https://x.org/in-order-to).\n```\nutilize()\n```\n"
    assert pc.check(pc.markdown_prose(text)) == []


def test_the_cli_reads_markdown(pc, tmp_path, monkeypatch, capsys):
    doc = tmp_path / "doc.md"
    doc.write_text("It is worth noting that this fires.\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["prose_check.py", str(doc)])
    assert pc.main() == 0
    assert "throat-clearing" in capsys.readouterr().out


def test_a_pattern_line_without_a_bar_is_an_error(pc, tmp_path):
    """Without the bar the regex is empty and matches at every position."""
    rubric = tmp_path / "plain-prose.md"
    rubric.write_text("```prose-patterns\npassive \\bwas\\b\n```\n", encoding="utf-8")
    with pytest.raises(ValueError):
        pc.load_patterns(rubric, None)


def test_the_glossary_llm_tells_are_checked(pc):
    assert "llm-tell" in names(pc.check("We delve into the cache."))


def test_nor_is_a_tell_but_normal_is_not(pc):
    assert "llm-tell" in names(pc.check("Nor do they show it."))
    assert "llm-tell" not in names(pc.check("The normal run passed."))


def test_markdown_triple_dash_between_words_counts_as_an_em_dash(pc):
    """Typst's smart punctuation sets `---` as U+2014 in the PDF."""
    assert "em-dash" in names(pc.check(pc.markdown_prose("The run failed --- twice.\n")))


@pytest.mark.parametrize("md", ["One.\n\n---\n\nTwo.\n", "| A | B |\n| --- | --- |\n| x | y |\n"])
def test_a_markdown_rule_or_table_separator_is_not_an_em_dash(pc, md):
    assert "em-dash" not in names(pc.check(pc.markdown_prose(md)))


def test_an_appendix_after_the_references_is_still_checked(pc):
    text = "Body.\n\nREFERENCES\n\n[1] A cite.\n\nAPPENDIX A\n\nIt is worth noting this."
    assert "throat-clearing" in names(pc.check(text))


def test_a_markdown_reference_heading_is_recognised(pc):
    text = "Body.\n\n## References\n\n- Leveraging caches, 2020.\n"
    assert pc.check(text) == []


def test_bullet_items_are_not_joined_into_one_sentence(pc):
    item = "- " + " ".join(["word"] * 20) + "."
    assert "long-sentence" not in names(pc.check("\n".join([item] * 4)))


# ----------------------------------------------------------- gate wiring --


def test_latex_reports_prose_hits_as_review(lx, monkeypatch, gates):
    assert lx.prose_check is not None, "latex.py cannot import _shared/prose_check.py"
    monkeypatch.setattr(lx.prose_check, "pdf_text", lambda _pdf: "It is worth noting this.")
    found = lx.prose_findings(pathlib.Path("doc.pdf"))
    assert gates(found) == {(REVIEW, "prose")}
    assert "throat-clearing" in found[0].message


def test_prose_review_does_not_change_the_exit_code(lx):
    found = [lx.Finding(REVIEW, "prose", "1x filler")]
    code, line = lx.verdict(found, pathlib.Path("d.pdf"), pathlib.Path("d.log"))
    assert code == 0
    assert "1 item(s) to confirm by eye" in line


def test_a_missing_prose_check_is_reported_not_fatal(lx, monkeypatch, gates):
    monkeypatch.setattr(lx, "prose_check", None)
    assert gates(lx.prose_findings(pathlib.Path("doc.pdf"))) == {(INFO, "prose")}


def test_a_malformed_rubric_is_reported_not_fatal(lx, rn, monkeypatch, gates, tmp_path):
    """An advisory check must not turn a clean build into a traceback."""

    def broken():
        raise ValueError("no prose-patterns block")

    monkeypatch.setattr(lx.prose_check, "default_patterns", broken)
    monkeypatch.setattr(lx.prose_check, "pdf_text", lambda _pdf: "Text.")
    assert gates(lx.prose_findings(pathlib.Path("doc.pdf"))) == {(INFO, "prose")}

    src = tmp_path / "doc.md"
    src.write_text("# T\n\nText.\n", encoding="utf-8")
    monkeypatch.setattr(rn.prose_check, "default_patterns", broken)
    (line,) = rn.prose_lines(src)
    assert line.strip().startswith("INFO")


def test_render_reports_prose_hits_in_the_markdown_source(rn, tmp_path):
    src = tmp_path / "doc.md"
    src.write_text("# Title\n\nIt is worth noting that `leverage()` is code.\n", encoding="utf-8")
    lines = rn.prose_lines(src)
    assert len(lines) == 1
    assert "REVIEW prose" in lines[0] and "throat-clearing" in lines[0]


def test_render_prose_check_is_skipped_on_request(rn, tmp_path, monkeypatch, capsys):
    src = tmp_path / "doc.md"
    src.write_text("# T\n\nIt is worth noting this.\n", encoding="utf-8")
    monkeypatch.setattr(rn, "render", lambda s, o: (o / f"{s.stem}.pdf", ["Libertinus"]))
    assert rn.main([str(src), str(tmp_path / "out"), "--no-prose"]) == 0
    assert "REVIEW" not in capsys.readouterr().out
