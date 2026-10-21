"""Unit tests for the length budget the latex and pdf gates enforce.

A document declares its budget in its source. The gates block a PDF over it and
ask for one when none is declared, because a sentence-level prose check passes
a document that is twice as long as it should be.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
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
        ("<!-- budget: None -->\n", True, None, None),
        ("% budget: None.\n", False, None, None),
        ("% budget: unlimited\n", False, None, None),
        ("% budget: no limit (journal)\n", False, None, None),
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
        ("% budget: 4pages\n", "cannot read"),
        ("% budget: four pages\n", "cannot read"),
        ("% budget: __BUDGET__\n", "cannot read"),
        ("% budget: 4 pages, 5 pages\n", "two page limits"),
        ("% budget: 0 pages\n", "a budget of 0"),
        ("% budget: 3.5 pages\n", "cannot read"),
    ],
)
def test_a_budget_line_it_cannot_read_is_an_error(lb, source, says):
    with pytest.raises(ValueError, match=says):
        lb.read(source)


# ------------------------------------------------------------ measuring --


@pytest.mark.parametrize(
    "source",
    [
        "% Budget: personnel costs justified below\n",
        "% Budget: none of the travel is covered\n",
        "% budget:\n",
        "% budget: one of the options\n",
    ],
)
def test_a_budget_comment_that_states_no_limit_is_an_ordinary_comment(lb, source):
    assert lb.read(source) is None


def test_an_ordinary_budget_comment_does_not_hide_the_declaration(lb):
    assert lb.read("% Budget: costs below\n% budget: 4 pages\n") == lb.Budget(4, None)


@pytest.mark.parametrize("env", ["Verbatim", "BVerbatim", "filecontents", "filecontents*"])
def test_a_budget_line_in_a_fancyvrb_or_filecontents_block_is_example_text(lb, env):
    source = f"% budget: 4 pages\n\\begin{{{env}}}\n% budget: 9 pages\n\\end{{{env}}}\n"
    assert lb.read(source) == lb.Budget(4, None)


@pytest.mark.parametrize("indent", ["    ", "\t"])
def test_a_budget_line_in_an_indented_markdown_code_block_is_example_text(lb, indent):
    source = f"# T\n\n<!-- budget: 4 pages -->\n\nExample:\n\n{indent}<!-- budget: 9 pages -->\n"
    assert lb.read(source, markdown=True) == lb.Budget(4, None)


@pytest.mark.parametrize(
    "source",
    [
        "% budget: 4 pages\n\\iffalse\n\\ifx\\a\\b x\\fi\n% budget: 9 pages\n\\fi\n",
        "\\let\\ifblind\\iffalse\n% budget: 4 pages\n\\fi\n",
        "% uses \\iffalse\n% budget: 4 pages\n",
        "\\iffalse\n\\newif\\ifdraft\n\\fi\n% budget: 4 pages\n",
        "\\newif\\ifdraft\n\\iffalse\n\\ifdraft x\\fi\n% budget: 9 pages\n\\fi\n"
        "% budget: 4 pages\n",
    ],
)
def test_iffalse_hides_only_what_it_encloses(lb, source):
    assert lb.read(source) == lb.Budget(4, None)


# ------------------------------------------------------ markdown words --


def test_markdown_words_skip_table_bars_bullets_code_and_comments(lb):
    source = (
        "| Case | Group |\n|---|---|\n| one | two |\n\n- three `inline code`\n\n"
        "```\nfenced code\n```\n\n<!-- budget: 9 words -->\n"
    )
    assert lb.markdown_words(source) == 5


def test_markdown_words_count_nested_list_items_and_continuation_paragraphs(lb):
    source = "- one two\n    - three four\n        - five\n\n- six seven\n\n    eight nine ten\n"
    assert lb.markdown_words(source) == 10


@pytest.mark.parametrize(
    "heading", ["# Works Cited", "## 5. References", "## REFERENCES", "# Bibliography"]
)
def test_markdown_words_skip_a_reference_section(lb, heading):
    source = f"# Intro\n\nOne two three.\n\n{heading}\n\nNot counted at all.\n"
    assert lb.markdown_words(source) == 4


def test_a_reference_section_runs_to_the_next_heading_of_its_level_or_higher(lb):
    source = (
        "# Body\n\nOne two.\n\n## References\n\nDropped.\n\n### Sub\n\nDropped too.\n\n"
        "## Appendix\n\nKept words.\n\n# References\n\nDropped.\n\n# End\n\nLast.\n"
    )
    assert lb.markdown_words(source) == len("Body One two. Appendix Kept words. End Last.".split())


def test_a_numbered_list_item_is_not_a_references_heading(lb):
    assert lb.markdown_words("One two.\n\n3. References are cited inline.\n\nFour.\n") == 8


@pytest.mark.parametrize("underline", ["=====", "-----", "="])
def test_a_setext_references_heading_starts_a_reference_section(lb, underline):
    source = f"Intro\n=====\n\nOne two.\n\nReferences\n{underline}\n\nNot counted.\n"
    assert lb.markdown_words(source) == 3


def test_a_setext_reference_section_ends_at_the_next_heading_of_its_level(lb):
    source = "Body\n----\n\nOne.\n\nReferences\n----------\n\nDropped.\n\nEnd\n---\n\nLast.\n"
    assert lb.markdown_words(source) == len("Body One. End Last.".split())


def test_a_references_line_under_a_paragraph_is_not_a_setext_heading(lb):
    assert lb.markdown_words("Some text\nReferences\n---\n\nKept.\n") == 4


def test_a_references_heading_inside_code_is_not_a_heading(lb):
    assert lb.markdown_words("One.\n\n```\n# References\n```\n\nTwo.\n") == 2


def test_a_longer_closing_fence_ends_the_code_block(lb):
    assert lb.markdown_words("```\ncode here\n````\n\nTwo words.\n") == 2


def test_an_indented_budget_example_is_no_declaration_but_its_words_count(lb):
    source = "<!-- budget: 3 words -->\n\nOne two.\n\n    <!-- budget: 9 words -->\n    code\n"
    assert lb.read(source, markdown=True) == lb.Budget(None, 3)
    assert lb.markdown_words(source) == 3


# -------------------------------------------------------- latex words --


needs_texcount = pytest.mark.skipif(
    os.environ.get("TECHNE_NO_TEX") == "1" or not shutil.which("texcount"),
    reason="texcount not available or TECHNE_NO_TEX=1",
)

TEX_DOC = (
    "\\documentclass{article}\n\\title{Not counted title}\n\\begin{document}\n\\maketitle\n"
    "\\section{Two words}\nBody has five words.\n\\input{more}\n"
    "\\begin{figure}\\caption{Caption three words}\\end{figure}\n"
    "\\begin{thebibliography}{9}\\bibitem{a} Excluded entry text.\\end{thebibliography}\n"
    "\\end{document}\n"
)


@needs_texcount
def test_latex_words_follow_inputs_and_leave_out_the_bibliography(lb, tmp_path):
    (tmp_path / "doc.tex").write_text(TEX_DOC)
    (tmp_path / "more.tex").write_text("Input adds four words.\n")
    # headers + text + input + caption + the \title texcount counts as a header
    assert lb.tex_words(tmp_path / "doc.tex") == (2 + 4 + 4 + 3 + 3, "")


@needs_texcount
def test_latex_words_come_from_the_roots_own_folder(lb, tmp_path, monkeypatch):
    (tmp_path / "doc.tex").write_text(TEX_DOC)
    (tmp_path / "more.tex").write_text("Input adds four words.\n")
    monkeypatch.chdir(tmp_path.parent)
    assert lb.tex_words(tmp_path / "doc.tex")[0] == 16


@needs_texcount
def test_latex_words_are_unmeasured_when_an_input_is_missing(lb, tmp_path):
    (tmp_path / "doc.tex").write_text(TEX_DOC)
    words, why = lb.tex_words(tmp_path / "doc.tex")
    assert words is None and "texcount" in why


HIDDEN = (
    "\\documentclass{article}\n\\begin{document}\nOne visible.\n"
    "\\iffalse\nCut paragraph kept here.\n\\fi\n"
    "\\begin{comment}\nAlso cut words.\n\\end{comment}\n"
)


@needs_texcount
def test_latex_words_leave_out_iffalse_and_comment_blocks(lb, tmp_path):
    (tmp_path / "doc.tex").write_text(HIDDEN + "\\end{document}\n")
    assert lb.tex_words(tmp_path / "doc.tex") == (2, "")


@needs_texcount
def test_latex_words_leave_out_hidden_blocks_in_input_files(lb, tmp_path):
    (tmp_path / "doc.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nRoot.\n\\input{sub/part}\n"
        "\\include{inc}\n\\end{document}\n"
    )
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "part.tex").write_text(HIDDEN.split("\\begin{document}\n")[1])
    (tmp_path / "inc.tex").write_text("\\iffalse\nCut.\n\\fi\nKept.\n")
    assert lb.tex_words(tmp_path / "doc.tex") == (1 + 2 + 1, "")


@needs_texcount
def test_a_commented_input_is_not_followed(lb, tmp_path):
    (tmp_path / "doc.tex").write_text("Root.\n% \\input{more}\n")
    (tmp_path / "more.tex").write_text("Many many words.\n")
    assert lb.tex_words(tmp_path / "doc.tex") == (1, "")


def test_a_page_only_budget_does_not_call_texcount(lb, tmp_path, monkeypatch):
    def fail(_tex):
        raise AssertionError("texcount called")

    monkeypatch.setattr(lb, "tex_words", fail)
    monkeypatch.setattr(lb, "pdf_pages", lambda _pdf: 2)
    tex = tmp_path / "doc.tex"
    tex.write_text("% budget: 3 pages\n")
    ((severity, message, _),) = lb.assess(
        tex.read_text(), tmp_path / "doc.pdf", hint="h", source_name="doc.tex", tex=tex
    )
    assert severity == INFO and message == "2 of 3 pages"


def test_latex_words_need_texcount(lb, tmp_path, monkeypatch):
    monkeypatch.setattr(lb.shutil, "which", lambda _tool: None)
    assert lb.tex_words(tmp_path / "doc.tex") == (None, "texcount not found")


def test_a_word_limit_without_texcount_asks_for_a_look(lb, tmp_path, monkeypatch):
    monkeypatch.setattr(lb.shutil, "which", lambda _tool: None)
    monkeypatch.setattr(lb, "pdf_pages", lambda _pdf: 1)
    tex = tmp_path / "doc.tex"
    tex.write_text("% budget: 900 words\n")
    ((severity, message, anchor),) = lb.assess(
        tex.read_text(), tmp_path / "doc.pdf", hint="h", source_name="doc.tex", tex=tex
    )
    assert severity == REVIEW
    assert "word limit cannot be measured: texcount not found" in message
    assert anchor == "doc.pdf"


def test_a_texcount_failure_shows_its_first_stderr_line(lb, tmp_path, monkeypatch):
    monkeypatch.setattr(lb.shutil, "which", lambda _tool: "/usr/bin/texcount")
    done = subprocess.CompletedProcess(
        [], 1, "2 (errors:1)\n", "! File not found: more.tex\nnext\n"
    )
    monkeypatch.setattr(lb.subprocess, "run", lambda *_a, **_k: done)
    (tmp_path / "doc.tex").write_text("Text.\n")
    words, why = lb.tex_words(tmp_path / "doc.tex")
    assert words is None
    assert "File not found: more.tex" in why and "next" not in why


@pytest.mark.parametrize(
    "macro",
    [
        "\\ifthenelse{\\a}{x}{y}",
        "\\iftoggle{t}{a}{b}",
        "\\ifbool{b}{a}{b}",
        "\\ifmymacro{arg}",
        "\\ifthenelse {\\a}{x}{y}",
    ],
)
def test_a_macro_that_takes_braces_does_not_open_a_conditional_in_iffalse(lb, macro):
    source = f"\\iffalse\n{macro}\n\\fi\n% budget: 4 pages\n"
    assert lb.read(source) == lb.Budget(4, None)


@pytest.mark.parametrize(
    "macro",
    [
        "\\subimport{d/}{f}",
        "\\import{d/}{f}",
        "\\subfile{f}",
        "\\includefrom{d}{f}",
        "\\inputfrom{d}{f}",
    ],
)
def test_a_word_count_warns_of_files_texcount_does_not_follow(lb, tmp_path, monkeypatch, macro):
    name = macro.split("{")[0]
    source = f"% budget: 900 words\n{macro}\n"
    monkeypatch.setattr(lb, "tex_words", lambda _tex: (10, ""))
    tex = tmp_path / "doc.tex"
    tex.write_text(source)
    found = lb.assess(source, tmp_path / "doc.pdf", hint="h", source_name="doc.tex", tex=tex)
    assert [s for s, _, _ in found] == [INFO, REVIEW]
    assert f"word count may miss files texcount does not follow ({name})" in found[1][1]


def test_no_warning_for_commented_or_input_files(lb, tmp_path, monkeypatch):
    source = "% budget: 900 words\n% \\subimport{d/}{f}\n\\input{f}\n"
    monkeypatch.setattr(lb, "tex_words", lambda _tex: (10, ""))
    tex = tmp_path / "doc.tex"
    tex.write_text(source)
    found = lb.assess(source, tmp_path / "doc.pdf", hint="h", source_name="doc.tex", tex=tex)
    assert [s for s, _, _ in found] == [INFO]


@pytest.mark.parametrize(
    ("source", "markdown", "budget"),
    [
        ("% budget: 1200 words.\n", False, (None, 1200)),
        ("% budget: 4 pages, 3000 words.\n", False, (4, 3000)),
        ("<!-- budget: 1200 words. -->\n", True, (None, 1200)),
        ("% budget: 4 pages (IEEE).\n", False, (4, None)),
    ],
)
def test_a_trailing_period_after_a_spec_is_read(lb, source, markdown, budget):
    assert lb.read(source, markdown=markdown) == lb.Budget(*budget)


@pytest.mark.parametrize(
    "spec",
    [
        "max 4 pages",
        "Maximum 4 pages",
        "~1200 words",
        "up to 4 pages",
        "4 pp",
        "<= 4 pages",
        "at most 900 words",
        "1200 wrods",
        "4-page limit",
        "4 sheets",
        "2026 costs below",
        "4 lines of help",
        "3,000 wrods",
    ],
)
def test_a_spec_that_intends_a_limit_in_another_form_is_unreadable_and_shows_the_form(lb, spec):
    with pytest.raises(ValueError, match="cannot read") as err:
        lb.read(f"% budget: {spec}\n")
    assert "`4 pages`" in str(err.value) and "`1200 words`" in str(err.value)


def test_a_spec_in_another_form_blocks_instead_of_asking_for_a_budget(lb, tmp_path):
    ((severity, message, anchor),) = lb.assess(
        "% budget: max 4 pages\n",
        tmp_path / "doc.pdf",
        hint="h",
        source_name="doc.tex",
        tex=tmp_path / "doc.tex",
    )
    assert (severity, anchor) == (BLOCK, "doc.tex")
    assert "no budget declared" not in message


# ----------------------------------------------------------- pages --


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


def test_an_indirect_page_count_is_not_read_as_the_count(lb, monkeypatch, tmp_path):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.7\n<< /Type /Pages /Count 9 0 R >>\n<< /Type /Page >>\n")
    monkeypatch.setattr(lb.shutil, "which", lambda _tool: None)
    assert lb.pdf_pages(pdf) == 1


def test_a_pdf_stream_is_decompressed_only_when_it_is_an_object_stream(lb, monkeypatch, tmp_path):
    objects = zlib.compress(b"<< /Type /Pages /Count 3 >>")
    content = zlib.compress(b"BT (page text) Tj ET")
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(
        b"%PDF-1.5\n1 0 obj\n<< /Length 9 /Filter /FlateDecode >>\nstream\n"
        + content
        + b"\nendstream\nendobj\n2 0 obj\n<< /Type /ObjStm /N 1 >>\nstream\n"
        + objects
        + b"\nendstream\nendobj\n"
    )
    seen = []
    real = zlib.decompress
    monkeypatch.setattr(lb.zlib, "decompress", lambda data: seen.append(data) or real(data))
    monkeypatch.setattr(lb.shutil, "which", lambda _tool: None)
    assert lb.pdf_pages(pdf) == 3
    assert seen == [objects]


@pytest.mark.parametrize(
    "line",
    [
        "% budget: 8 pages before references",
        "% budget: 8 pages before references, 6000 words",
        "% budget: 900 words before references",
    ],
)
def test_a_before_references_scope_is_unreadable_and_shows_the_accepted_forms(lb, line):
    with pytest.raises(ValueError, match="cannot read") as err:
        lb.read(line + "\n")
    assert "`4 pages`" in str(err.value) and "`1200 words`" in str(err.value)


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
        ((None, 1), 1, 1, [], "1 page, 1 of 1 word", False),
    ],
)
def test_compare_names_each_limit_it_is_over(lb, budget, pages, words, over, measured, unmeasured):
    assert lb.compare(lb.Budget(*budget), pages, words) == (over, measured, unmeasured)


def test_one_is_singular_for_pages_and_words(lb):
    assert lb.compare(lb.Budget(1, None), 1, 10).measured == "1 of 1 page, 10 words"
    assert lb.compare(lb.Budget(None, 1), 1, 1).measured == "1 page, 1 of 1 word"
    assert lb.compare(lb.Budget(None, None), 1, 1).measured == "1 page, 1 word (no limit declared)"
    assert lb.compare(lb.Budget(None, 1), 1, 2).over == ["2 words, budget 1"]


# ---------------------------------------------------------- gate wiring --


def _tex(tmp_path, first_line: str) -> tuple[pathlib.Path, pathlib.Path]:
    tex = tmp_path / "doc.tex"
    tex.write_text(f"{first_line}\n\\documentclass{{article}}\n", encoding="utf-8")
    return tex, tmp_path / "doc.pdf"


@pytest.fixture
def words_of(lb, monkeypatch):
    def set_words(n):
        monkeypatch.setattr(lb, "tex_words", lambda _tex: (n, "" if n is not None else "why"))

    return set_words


@pytest.mark.parametrize(
    ("line", "pages", "expected"),
    [
        ("% budget: 4 pages", 5, BLOCK),
        ("% budget: 4 pages", 4, INFO),
        ("% budget: four pages", 4, BLOCK),
        ("% budget: 4 sheets", 4, BLOCK),
        ("% no budget here", 4, REVIEW),
        ("% budget: none", 40, INFO),
        ("% budget: 4 pages", None, REVIEW),
        ("% budget: 900 words", None, INFO),
    ],
)
def test_latex_gates_on_the_declared_budget(
    lx, lb, monkeypatch, tmp_path, gates, words_of, line, pages, expected
):
    tex, pdf = _tex(tmp_path, line)
    words_of(50)
    monkeypatch.setattr(lb, "pdf_pages", lambda _pdf: pages)
    assert gates(lx.budget_findings(tex, pdf)) == {(expected, "budget")}


def test_latex_over_budget_is_not_submittable(lx, lb, tmp_path, words_of):
    tex, pdf = _tex(tmp_path, "% budget: 900 words")
    words_of(901)
    found = lx.budget_findings(tex, pdf)
    code, line = lx.verdict(found, pdf, tex.with_suffix(".log"))
    assert code == 2, line
    assert "901 words, budget 900" in found[0].message


def test_latex_asks_for_a_look_when_a_word_limit_cannot_be_counted(lx, tmp_path, gates, words_of):
    tex, pdf = _tex(tmp_path, "% budget: 900 words")
    words_of(None)
    assert gates(lx.budget_findings(tex, pdf)) == {(REVIEW, "budget")}


@pytest.mark.parametrize(
    ("line", "pages", "words", "where"),
    [
        ("% no budget here", 1, 5, "doc.tex"),
        ("% budget: 0 pages", 1, 5, "doc.tex"),
        ("% budget: 1 page", 2, 5, "doc.pdf"),
        ("% budget: 3 pages", 2, 5, "doc.pdf"),
        ("% budget: 3 pages", None, 5, "doc.pdf"),
    ],
)
def test_latex_findings_point_at_the_source_or_the_pdf(
    lx, lb, monkeypatch, tmp_path, words_of, line, pages, words, where
):
    tex, pdf = _tex(tmp_path, line)
    words_of(words)
    monkeypatch.setattr(lb, "pdf_pages", lambda _pdf: pages)
    (finding,) = lx.budget_findings(tex, pdf)
    assert finding.where == where


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
    assert "doc.pdf: over budget:" in captured.err


def test_render_points_an_unreadable_line_at_the_source(rn, monkeypatch, tmp_path, capsys):
    code = _render_main(rn, monkeypatch, tmp_path, "# T\n\n<!-- budget: 0 pages -->\n\nBody.\n", 1)
    assert code == 1
    assert "doc.md: unreadable budget line" in capsys.readouterr().err


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
    assert "INFO   budget 30 pages, 1 word (no limit declared)" in out
    assert "REVIEW" not in out


def test_render_does_not_count_the_title_block_as_words(rn, monkeypatch, tmp_path):
    source = "# A long title\n\n*A subtitle line*\n\n<!-- budget: 2 words -->\n\nOne two.\n"
    assert _render_main(rn, monkeypatch, tmp_path, source, 1) == 0


def test_render_drops_the_reference_section_from_the_word_count(rn, monkeypatch, tmp_path):
    source = "# T\n\n<!-- budget: 2 words -->\n\nOne two.\n\n## References\n\n[1] Not counted.\n"
    assert _render_main(rn, monkeypatch, tmp_path, source, 1) == 0


def test_render_reads_the_source_once(rn, monkeypatch, tmp_path):
    src = tmp_path / "doc.md"
    src.write_text("# T\n\n<!-- budget: 9 words -->\n\nBody.\n", encoding="utf-8")
    reads = []
    real = pathlib.Path.read_text
    monkeypatch.setattr(
        pathlib.Path,
        "read_text",
        lambda self, *a, **k: (reads.append(self.name), real(self, *a, **k))[1],
    )
    monkeypatch.setattr(rn, "render", lambda s, o: (o / f"{s.stem}.pdf", ["Libertinus"]))
    monkeypatch.setattr(rn.length_budget, "pdf_pages", lambda _pdf: 1)
    assert rn.main([str(src), str(tmp_path / "out")]) == 0
    assert reads.count("doc.md") == 1


def test_assess_reads_missing_unreadable_and_none(lb, tmp_path, monkeypatch):
    pdf = tmp_path / "doc.pdf"
    monkeypatch.setattr(lb, "pdf_pages", lambda _pdf: 1)

    def run(source):
        return lb.assess(source, pdf, hint="H", source_name="doc.md", body=source)

    assert run("Plain.\n")[0][0] == REVIEW
    assert "H" in run("Plain.\n")[0][1]
    assert run("<!-- budget: 0 pages -->\n")[0][0] == BLOCK
    ((severity, message, _),) = run("<!-- budget: none -->\n")
    assert severity == INFO and "1 page," in message


def _no_poppler(args, **_kw):
    # pdf_checks shells out to pdfinfo and pdffonts, which CI does not install
    return subprocess.CompletedProcess(args, 0, "", "")


def test_latex_ignores_a_stale_pdf_from_a_failed_build(lx, monkeypatch, tmp_path, capsys):
    tex = tmp_path / "doc.tex"
    tex.write_text("% budget: 20 pages\n\\documentclass{article}\n")
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    os.utime(pdf, (4_000_000_000, 4_000_000_000))  # newer than the clock: only a snapshot is safe
    monkeypatch.setattr(lx, "require_tools", lambda: None)
    monkeypatch.setattr(lx, "build", lambda _tex, _engine: 1)
    monkeypatch.setattr(lx, "pdf_text", lambda _pdf: "FILL in the answer")
    monkeypatch.setattr(lx.length_budget, "pdf_pages", lambda _pdf: 9)
    monkeypatch.setattr("sys.argv", ["latex.py", str(tex), "--no-prompt"])
    lx.main()
    out = capsys.readouterr().out
    assert "budget" not in out and "draft-marker" not in out and "prose" not in out


def test_latex_checks_a_pdf_the_failed_build_rewrote(lx, monkeypatch, tmp_path, capsys):
    tex = tmp_path / "doc.tex"
    tex.write_text("% budget: 20 pages\n\\documentclass{article}\n")
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    os.utime(pdf, (1_000_000, 1_000_000))

    def build(_tex, _engine):
        pdf.write_bytes(b"%PDF-1.4\nnew")
        return 1

    monkeypatch.setattr(lx, "require_tools", lambda: None)
    monkeypatch.setattr(lx, "build", build)
    monkeypatch.setattr(lx, "pdf_text", lambda _pdf: "FILL in the answer")
    monkeypatch.setattr(lx.length_budget, "pdf_pages", lambda _pdf: 9)
    monkeypatch.setattr(lx.length_budget, "tex_words", lambda _tex: (5, ""))
    monkeypatch.setattr(lx.subprocess, "run", _no_poppler)
    monkeypatch.setattr("sys.argv", ["latex.py", str(tex), "--no-prompt"])
    lx.main()
    out = capsys.readouterr().out
    # the draft marker is a BLOCK, which a failed build folds into the cascade line
    assert "INFO   budget" in out and "downstream finding" in out


def test_latex_checks_an_up_to_date_pdf_when_the_build_succeeds(lx, monkeypatch, tmp_path, capsys):
    tex = tmp_path / "doc.tex"
    tex.write_text("% budget: 20 pages\n\\documentclass{article}\n")
    (tmp_path / "doc.pdf").write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(lx, "require_tools", lambda: None)
    monkeypatch.setattr(lx, "build", lambda _tex, _engine: 0)
    monkeypatch.setattr(lx, "pdf_text", lambda _pdf: "text")
    monkeypatch.setattr(lx.length_budget, "pdf_pages", lambda _pdf: 9)
    monkeypatch.setattr(lx.length_budget, "tex_words", lambda _tex: (5, ""))
    monkeypatch.setattr(lx.subprocess, "run", _no_poppler)
    monkeypatch.setattr("sys.argv", ["latex.py", str(tex), "--no-prompt"])
    lx.main()
    assert "INFO   budget" in capsys.readouterr().out


@pytest.mark.parametrize(
    "lead",
    [
        "<!-- budget: 3 pages, 1500 words -->\n",
        "\n<!-- note\nover two lines -->\n\n<!-- budget: 3 pages -->\n",
    ],
)
def test_a_leading_comment_does_not_hide_the_title_block(rn, lb, lead):
    source = f"{lead}# Title\n\n*Subtitle*\n\nBody.\n"
    title, subtitle, body = rn.split_front_matter(source)
    assert (title, subtitle) == ("Title", "Subtitle")
    assert "budget:" in body and "Body." in body
    assert lb.read(body, markdown=True) is not None


@pytest.mark.parametrize(
    "lead",
    ["<!-- note --> draft\n", "<!-- a --> <!-- b --> x\n"],
)
def test_text_after_a_closed_comment_on_the_first_line_is_not_an_open_comment(rn, lead):
    title, _, body = rn.split_front_matter(f"{lead}# Title\n\nBody.\n")
    assert title is None
    assert lead.strip() in body and "Body." in body


def test_an_unclosed_comment_ends_at_the_first_line_with_a_close(rn):
    source = "<!-- one\nstill --> trailing\n# Title\n\nBody.\n"
    title, _, body = rn.split_front_matter(source)
    assert title == "Title" and "<!-- one" in body


def test_several_complete_comments_on_a_line_are_skipped(rn):
    title, _, body = rn.split_front_matter("<!-- a --> <!-- b -->\n# Title\n\nBody.\n")
    assert title == "Title" and "<!-- a -->" in body
