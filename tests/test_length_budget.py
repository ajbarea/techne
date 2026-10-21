"""Unit tests for the length budget the latex and pdf gates enforce.

A document declares its budget in its source. The gates block a PDF over it and
ask for one when none is declared, because a sentence-level prose check passes
a document that is twice as long as it should be.
"""

from __future__ import annotations

import pathlib
import zlib

import pytest

BLOCK, REVIEW, INFO = "BLOCK", "REVIEW", "INFO"


@pytest.fixture(scope="module")
def lb(lx):
    assert lx.length_budget is not None, "latex.py cannot import _shared/length_budget.py"
    return lx.length_budget


# ------------------------------------------------------------- reading --


@pytest.mark.parametrize(
    ("source", "markdown", "pages", "words"),
    [
        ("% budget: 4 pages\n\\documentclass{article}", False, 4, None),
        ("%% Budget: 1 page, 900 words\n", False, 1, 900),
        ("\\documentclass{article}\n  % budget: 3000 words\n", False, None, 3000),
        ("# Title\n\n<!-- budget: 1200 words -->\n\nBody.\n", True, None, 1200),
        ("<!--budget: 3 pages, 1500 words-->\n", True, 3, 1500),
        ("% budget: 3,000 words\n", False, None, 3000),
        ("% budget: 8 pages; 6,500 words (ACM)\n", False, 8, 6500),
        ("% budget: 4 pages and 500 words\n", False, 4, 500),
        ("% budget: 4 pages (IEEE conference)\n", False, 4, None),
        ("% budget: none\n", False, None, None),
        ("<!-- budget: Unlimited -->\n", True, None, None),
    ],
)
def test_a_declared_budget_is_read(lb, source, markdown, pages, words):
    assert lb.read(source, markdown=markdown) == lb.Budget(pages, words)


@pytest.mark.parametrize(
    ("source", "markdown"),
    [
        ("\\documentclass{article}\nThe budget: 4 pages is prose.\n", False),
        ("% the budget is four pages\n", False),
        ("# T\n\n```\n<!-- budget: 2 pages -->\n```\n", True),
        ("# T\n\n% budget: 2 pages\n", True),
        ("<!-- budget: 2 pages -->\n", False),
        ("# T\n\n~~~~\n```\n<!-- budget: 2 pages -->\n```\n~~~~\n", True),
    ],
)
def test_only_the_comment_form_for_the_source_counts(lb, source, markdown):
    assert lb.read(source, markdown=markdown) is None


def test_a_budget_line_shown_as_example_text_is_not_a_second_declaration(lb):
    source = (
        "% budget: 4 pages\n\\begin{verbatim}\n% budget: 9 pages\n\\end{verbatim}\n"
        "\\begin{comment}\n% budget: 2 pages\n\\end{comment}\n\\iffalse\n% budget: 1 page\n\\fi\n"
    )
    assert lb.read(source) == lb.Budget(4, None)


@pytest.mark.parametrize(
    ("source", "says"),
    [
        ("% budget: 4 pages\n% budget: 5 pages\n", "2 budget lines"),
        ("% budget: four pages\n", "cannot read"),
        ("% budget: 4 lines\n", "cannot read"),
        ("% budget:\n", "cannot read"),
        ("% budget: 4 pages, 5 pages\n", "two page limits"),
        ("% budget: 0 pages\n", "a budget of 0"),
        ("% budget: 3.5 pages\n", "cannot read"),
    ],
)
def test_a_budget_line_it_cannot_read_is_an_error(lb, source, says):
    with pytest.raises(ValueError, match=says):
        lb.read(source)


# ------------------------------------------------------------ measuring --


def test_words_skip_table_bars_bullets_and_the_reference_list(lb):
    text = "| Case | Group |\n|---|---|\n| one | two |\n\n- three\n\nReferences\n[1] Not counted.\n"
    assert lb.count_words(text) == 5


@pytest.mark.parametrize(
    "heading", ["Works Cited", "7 References", "VII. REFERENCES", "## 5 References"]
)
def test_words_skip_reference_lists_under_other_headings(lb, heading):
    assert lb.count_words(f"One two three.\n{heading}\n[1] Not counted at all.\n") == 3


def test_an_appendix_after_the_references_is_counted(lb):
    source = "\\bibliography{refs}\n\\appendix\n\\section{Proof of the theorem}\nText.\n"
    titles = lb.appendix_titles(source)
    text = (
        "Body words here.\nReferences\n[1] A. Smith. Paper.\nA\nProof of the theorem\nIt holds.\n"
    )
    assert titles == ("Proof of the theorem",)
    assert lb.count_words(text, titles) == 10


def test_pages_fall_back_to_the_page_objects_without_poppler(lb, monkeypatch, tmp_path):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.7\n<< /Type /Pages /Count 2 >>\n<< /Type /Page >>\n<</Type/Page>>\n")
    monkeypatch.setattr(lb.shutil, "which", lambda _tool: None)
    assert lb.pdf_pages(pdf) == 2


def test_pages_are_found_inside_compressed_object_streams(lb, monkeypatch, tmp_path):
    objects = zlib.compress(b"<< /Type /Pages /Kids [4 0 R 5 0 R 6 0 R] /Count 3 >>")
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.5\n<< /Type /ObjStm >>\nstream\n" + objects + b"\nendstream\n")
    monkeypatch.setattr(lb.shutil, "which", lambda _tool: None)
    assert lb.pdf_pages(pdf) == 3


def test_pages_ignore_page_objects_repeated_by_an_incremental_update(lb, monkeypatch, tmp_path):
    page = b"<< /Type /Page >>\n"
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.7\n<< /Type /Pages /Count 2 >>\n" + page * 4)
    monkeypatch.setattr(lb.shutil, "which", lambda _tool: None)
    assert lb.pdf_pages(pdf) == 2


@pytest.mark.parametrize(
    ("budget", "pages", "words", "over", "measured", "unmeasured"),
    [
        ((4, None), 5, 100, ["5 pages, budget 4"], "5 of 4 pages, 100 words", False),
        ((4, None), 4, 100, [], "4 of 4 pages, 100 words", False),
        ((None, 900), 9, 901, ["901 words, budget 900"], "9 pages, 901 of 900 words", False),
        ((3, 900), 2, 800, [], "2 of 3 pages, 800 of 900 words", False),
        ((3, None), None, 800, [], "? of 3 pages, 800 words", True),
        ((None, 900), None, 800, [], "? pages, 800 of 900 words", False),
        ((None, None), 12, 9000, [], "12 pages, 9000 words (no limit declared)", False),
    ],
)
def test_compare_names_each_limit_it_is_over(lb, budget, pages, words, over, measured, unmeasured):
    assert lb.compare(lb.Budget(*budget), pages, words) == (over, measured, unmeasured)


# ---------------------------------------------------------- gate wiring --


def _tex(tmp_path, first_line: str) -> tuple[pathlib.Path, pathlib.Path]:
    tex = tmp_path / "doc.tex"
    tex.write_text(f"{first_line}\n\\documentclass{{article}}\n", encoding="utf-8")
    return tex, tmp_path / "doc.pdf"


@pytest.mark.parametrize(
    ("line", "pages", "expected"),
    [
        ("% budget: 4 pages", 5, BLOCK),
        ("% budget: 4 pages", 4, INFO),
        ("% budget: 4 sheets", 4, BLOCK),
        ("% no budget here", 4, REVIEW),
        ("% budget: none", 40, INFO),
        ("% budget: 4 pages", None, REVIEW),
        ("% budget: 900 words", None, INFO),
    ],
)
def test_latex_gates_on_the_declared_budget(
    lx, lb, monkeypatch, tmp_path, gates, line, pages, expected
):
    tex, pdf = _tex(tmp_path, line)
    monkeypatch.setattr(lb, "pdf_pages", lambda _pdf: pages)
    assert gates(lx.budget_findings(tex, pdf, "Some words here.")) == {(expected, "budget")}


def test_latex_over_budget_is_not_submittable(lx, lb, monkeypatch, tmp_path):
    tex, pdf = _tex(tmp_path, "% budget: 900 words")
    found = lx.budget_findings(tex, pdf, "word " * 901)
    code, line = lx.verdict(found, pdf, tex.with_suffix(".log"))
    assert code == 2, line
    assert "901 words, budget 900" in found[0].message


def _render_main(rn, monkeypatch, tmp_path, source: str, pages: int | None) -> int:
    src = tmp_path / "doc.md"
    src.write_text(source, encoding="utf-8")
    monkeypatch.setattr(rn, "render", lambda s, o: (o / f"{s.stem}.pdf", ["Libertinus"]))
    monkeypatch.setattr(rn.length_budget, "pdf_pages", lambda _pdf: pages)
    return rn.main([str(src), str(tmp_path / "out"), "--no-prose"])


def test_render_fails_a_pdf_over_budget(rn, monkeypatch, tmp_path, capsys):
    code = _render_main(rn, monkeypatch, tmp_path, "# T\n\n<!-- budget: 3 pages -->\n\nBody.\n", 11)
    captured = capsys.readouterr()
    assert code == 1
    assert "BLOCK  budget over budget: 11 pages, budget 3" in captured.out
    assert "over budget:" in captured.err


def test_render_passes_a_pdf_within_budget(rn, monkeypatch, tmp_path, capsys):
    code = _render_main(rn, monkeypatch, tmp_path, "# T\n\n<!-- budget: 3 pages -->\n\nBody.\n", 3)
    assert code == 0
    assert "INFO   budget 3 of 3 pages" in capsys.readouterr().out


def test_render_asks_for_a_budget_without_failing(rn, monkeypatch, tmp_path, capsys):
    assert _render_main(rn, monkeypatch, tmp_path, "# T\n\nBody.\n", 3) == 0
    assert "REVIEW budget no length budget declared" in capsys.readouterr().out


def test_render_counts_words_without_the_budget_comment_or_code(rn, monkeypatch, tmp_path):
    source = "# T\n\n<!-- budget: 4 words -->\n\nOne two three.\n\n```\nnot counted at all\n```\n"
    assert _render_main(rn, monkeypatch, tmp_path, source, 1) == 0


def test_render_flags_a_page_limit_it_cannot_count(rn, monkeypatch, tmp_path, capsys):
    source = "# T\n\n<!-- budget: 3 pages -->\n\nBody.\n"
    code = _render_main(rn, monkeypatch, tmp_path, source, None)
    assert code == 0
    assert "REVIEW budget could not measure the PDF" in capsys.readouterr().out


def test_render_reports_the_length_of_a_document_with_no_limit(rn, monkeypatch, tmp_path, capsys):
    code = _render_main(rn, monkeypatch, tmp_path, "# T\n\n<!-- budget: none -->\n\nBody.\n", 30)
    out = capsys.readouterr().out
    assert code == 0
    assert "INFO   budget 30 pages, 2 words (no limit declared)" in out
    assert "REVIEW" not in out


# ------------------------------------------------ second-review cases --


def test_a_contents_entry_for_the_references_does_not_cut_the_body(lb):
    text = (
        "Contents\n1 Introduction\nReferences\nA Proof\n"
        "1 Introduction\nThe body has seven words in it.\n"
        "References\n[1] A. Smith. Not counted.\n"
    )
    assert lb.count_words(text) == 15


def test_an_appendix_title_inside_a_reference_entry_does_not_resume_the_count(lb):
    text = "Body words here.\nReferences\n[1] A. Smith. Data mining at scale.\n"
    assert lb.count_words(text, ("Data",)) == 3


@pytest.mark.parametrize(
    ("source", "titles"),
    [
        (
            "\\appendix\n\\section{Proof of the \\emph{main} theorem}",
            ("Proof of the main theorem",),
        ),
        ("\\appendix\n\\section{\\texorpdfstring{$\\alpha$ bound}{Alpha bound}}", ("Alpha bound",)),
        ("\\begin{appendices}\n\\section{More data}\n\\end{appendices}", ("More data",)),
        ("% \\appendix\n\\section{Method}", ()),
        ("\\appendix\n% \\section{Old}\n\\section*[s]{New}", ("New",)),
    ],
)
def test_appendix_titles_read_through_markup(lb, source, titles):
    assert lb.appendix_titles(source) == titles


def test_an_appendix_in_an_input_file_is_found(lb, tmp_path):
    (tmp_path / "doc.tex").write_text("\\begin{document}\n\\input{appendix}\n\\end{document}\n")
    (tmp_path / "appendix.tex").write_text("\\appendix\n\\section{Extra results}\n")
    titles = lb.appendix_titles(lb.expand_inputs(tmp_path / "doc.tex"))
    assert titles == ("Extra results",)


@pytest.mark.parametrize(
    "source",
    [
        "% budget: 4 pages\n\\iffalse\n\\ifx\\a\\b x\\fi\n% budget: 9 pages\n\\fi\n",
        "\\let\\ifblind\\iffalse\n% budget: 4 pages\n\\fi\n",
        "% uses \\iffalse\n% budget: 4 pages\n",
    ],
)
def test_iffalse_hides_only_what_it_encloses(lb, source):
    assert lb.read(source) == lb.Budget(4, None)


def test_a_numbered_list_item_is_not_a_references_heading(lb):
    assert lb.count_markdown_words("One two.\n\n3. References are cited inline.\n\nFour.\n") == 8


def test_a_longer_closing_fence_ends_the_code_block(lb):
    assert lb.count_markdown_words("```\ncode here\n````\n\nTwo words.\n") == 2


def test_an_indirect_page_count_is_not_read_as_the_count(lb, monkeypatch, tmp_path):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.7\n<< /Type /Pages /Count 9 0 R >>\n<< /Type /Page >>\n")
    monkeypatch.setattr(lb.shutil, "which", lambda _tool: None)
    assert lb.pdf_pages(pdf) == 1


def test_latex_asks_for_a_look_when_a_word_limit_meets_no_text(lx, lb, tmp_path, gates):
    tex, pdf = _tex(tmp_path, "% budget: 900 words")
    assert gates(lx.budget_findings(tex, pdf, "  \n")) == {(REVIEW, "budget")}
