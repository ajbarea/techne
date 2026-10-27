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


def guard_texcount():
    """Fail when TeX is not opted out of and texcount is missing."""
    if os.environ.get("TECHNE_NO_TEX") == "1" or shutil.which("texcount"):
        return
    raise AssertionError(
        "texcount missing and TECHNE_NO_TEX is unset: the word-count tests would skip "
        "silently. Install texlive-extra-utils, or set TECHNE_NO_TEX=1."
    )


def test_texcount_is_present_or_its_absence_is_declared():
    guard_texcount()


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
    (tmp_path / "more.tex").write_text("Many many words.\nAnd some more.\n")
    assert lb.tex_words(tmp_path / "doc.tex") == (1, "")


def _printed(lb, source):
    return lb._tex_code(source)


def test_a_commented_out_comment_environment_hides_nothing(lb):
    source = "A.\n%\\begin{comment}\nPrinted words.\n%\\end{comment}\nB.\n"
    assert "Printed words." in _printed(lb, source)


def test_a_comment_environment_in_code_still_hides(lb):
    source = "A.\n\\begin{comment} % note\nHidden.\n\\end{comment}\nB.\n"
    out = _printed(lb, source)
    assert "Hidden." not in out and "B." in out


def test_a_budget_line_after_a_commented_out_begin_is_read(lb):
    source = "%\\begin{comment}\n% budget: 3 pages\n%\\end{comment}\n"
    assert lb.read(source) == lb.Budget(3, None)


@needs_texcount
def test_latex_words_count_text_between_commented_out_begin_and_end(lb, tmp_path):
    (tmp_path / "doc.tex").write_text(
        "One.\n%\\begin{comment}\nPrinted three words.\n%\\end{comment}\n"
    )
    assert lb.tex_words(tmp_path / "doc.tex") == (4, "")


def test_the_else_branch_of_an_iffalse_is_kept(lb):
    out = _printed(lb, "A.\n\\iffalse\nCut.\n\\else\nShown.\n\\fi\nB.\n")
    assert "Cut." not in out and "Shown." in out and "B." in out


def test_a_nested_conditionals_else_does_not_end_the_skip(lb):
    src = "\\iffalse\n\\ifx a b\nX.\n\\else\nY.\n\\fi\nCut.\n\\else\nShown.\n\\fi\nB.\n"
    out = _printed(lb, src)
    assert "X." not in out and "Y." not in out and "Cut." not in out
    assert "Shown." in out and "B." in out


def test_a_nested_iffalse_in_the_else_branch_is_still_hidden(lb):
    src = "\\iffalse\nC.\n\\else\nS.\n\\iffalse\nD.\n\\fi\nT.\n\\fi\nB.\n"
    out = _printed(lb, src)
    assert "C." not in out and "D." not in out
    assert "S." in out and "T." in out and "B." in out


@needs_texcount
def test_latex_words_count_the_else_branch_of_an_iffalse(lb, tmp_path):
    (tmp_path / "doc.tex").write_text("\\iffalse\nCut words.\n\\else\nShown two.\n\\fi\nEnd.\n")
    assert lb.tex_words(tmp_path / "doc.tex") == (3, "")


@needs_texcount
def test_a_trailing_comment_in_an_input_file_does_not_swallow_the_roots_line(lb, tmp_path):
    (tmp_path / "doc.tex").write_text("\\input{more} Root words.\n")
    (tmp_path / "more.tex").write_text("Input. % trailing")
    assert lb.tex_words(tmp_path / "doc.tex") == (3, "")


def test_inlined_text_ends_with_a_newline(lb, tmp_path):
    (tmp_path / "more.tex").write_text("Input. % trailing")
    out = lb._inline_inputs("\\input{more} Root.\n", tmp_path)
    assert out == "Input. % trailing\n Root.\n"


@pytest.mark.parametrize("form", ["\\input chap", "\\input chap.tex", "\\input{chap}"])
def test_an_input_with_or_without_braces_is_inlined_and_preprocessed(lb, tmp_path, form):
    (tmp_path / "chap.tex").write_text("In.\n\\iffalse\nCut.\n\\fi\n")
    out = lb._inline_inputs(f"{form}\nRoot.\n", tmp_path)
    assert "In." in out and "Cut." not in out and "input" not in out


def test_a_macro_that_starts_like_input_is_not_an_input(lb, tmp_path):
    (tmp_path / "enc.tex").write_text("Wrong.\n")
    line = "\\inputenc{utf8}\n"
    assert lb._inline_inputs(line, tmp_path) == line


def test_input_tries_the_tex_suffix_first(lb, tmp_path):
    (tmp_path / "chap.tex").write_text("Right.\n")
    (tmp_path / "chap").write_text("Wrong.\n")
    assert "Right." in lb._inline_inputs("\\input{chap}\n", tmp_path)


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


@needs_texcount
def test_commented_import_macros_in_an_input_file_are_not_counted(lb, tmp_path):
    (tmp_path / "x.tex").write_text("Cut one two\nthree four five.\n")
    (tmp_path / "more.tex").write_text("Shown two.\n% \\subfile{x}\n% \\subimport{d/}{x}\n")
    (tmp_path / "doc.tex").write_text("\\input{more}\n")
    assert lb.tex_words(tmp_path / "doc.tex") == (2, "")


@needs_texcount
def test_a_subimported_file_is_followed_by_texcount_itself(lb, tmp_path):
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "f.tex").write_text(
        "Four printed words here.\n\\iffalse\nThree hidden words.\n\\fi\n"
    )
    root = "\\documentclass{article}\n\\usepackage{import}\n\\begin{document}\n"
    root += "\\subimport{d/}{f}\n\\end{document}\n"
    (tmp_path / "doc.tex").write_text(root)
    plain = subprocess.run(
        ["texcount", "-inc", "-sum", "-1", "doc.tex"], cwd=tmp_path, capture_output=True, text=True
    )
    count = lb.tex_words(tmp_path / "doc.tex")
    assert count == (int(plain.stdout.split()[0]), "")
    assert count[0] not in (None, 2)


def test_a_bom_before_the_budget_line_is_ignored(lb):
    assert lb.read("\ufeff% budget: 4 pages\n") == lb.Budget(4, None)
    assert lb.read("\ufeff<!-- budget: 4 pages -->\n", markdown=True) == lb.Budget(4, None)


@needs_texcount
def test_a_bom_in_an_input_file_does_not_join_its_first_word(lb, tmp_path):
    (tmp_path / "more.tex").write_text("\ufeffShown two.\n", encoding="utf-8")
    (tmp_path / "doc.tex").write_text("\\input{more}\n", encoding="utf-8")
    assert lb.tex_words(tmp_path / "doc.tex") == (2, "")


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
    # pdf_checks shells out to pdfinfo and pdffonts; stubbed so the outcome does not depend on them
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


def test_a_comment_after_an_unclosed_one_on_the_first_line_is_not_its_close(rn):
    source = "<!-- a --> <!-- b\nstill -->\n# Title\n\nBody.\n"
    title, _, body = rn.split_front_matter(source)
    assert title == "Title" and "<!-- b" in body


@needs_texcount
def test_texcount_input_is_utf8_whatever_the_locale(lb, monkeypatch, tmp_path):
    import locale

    monkeypatch.setattr(locale, "getencoding", lambda: "cp1252")
    tex = tmp_path / "doc.tex"
    tex.write_text(
        "\\documentclass{article}\n\\begin{document}\n\u65e5\u672c one two\n\\end{document}\n",
        encoding="utf-8",
    )
    words, why = lb.tex_words(tex)
    assert words is not None, why


# ---------------------------------------------------------- body pages --


@pytest.mark.parametrize(
    ("source", "budget"),
    [
        ("% budget: 7 pages, 6 body pages\n", (7, None, 6)),
        ("% budget: 6 body pages (MSR)\n", (None, None, 6)),
        ("% budget: 1 body page\n", (None, None, 1)),
        ("<!-- budget: 9 body pages, 8,000 words -->\n", (None, 8000, 9)),
        ("% budget: 7 pages\n", (7, None, None)),
    ],
)
def test_a_body_page_limit_is_read_beside_the_others(lb, source, budget):
    assert lb.read(source, markdown=source.startswith("<!--")) == lb.Budget(*budget)


@pytest.mark.parametrize(
    "source",
    [
        "% budget: 6 body pages, 7 body pages\n",
        "% budget: 0 body pages\n",
        "% budget: 6 bodypages\n",
        "% budget: 7 pages, 9 body pages\n",
    ],
)
def test_a_body_page_limit_it_cannot_accept_is_an_error(lb, source):
    with pytest.raises(ValueError):
        lb.read(source)


def _pages(*pages: list[str]) -> list[str]:
    return ["\n".join(lines) + "\n" for lines in pages]


@pytest.mark.parametrize(
    ("pages", "start"),
    [
        (_pages(["Intro text."], ["More text."], ["References", "[1] A."]), (3, 1)),
        (_pages(["Intro text."], ["Body.", "R EFERENCES", "[1] A."]), (2, 2)),
        (_pages(["Body."], ["8 References", "[1] A."]), (2, 1)),
        (_pages(["Body."], ["VIII. REFERENCES", "[1] A."]), (2, 1)),
        (_pages(["Body."], ["Bibliography", "[1] A."]), (2, 1)),
        (_pages(["Body."], ["References to the API are below.", "More."]), None),
        (_pages(["Body."], ["Body."]), None),
        # A running head and a folio ahead of the heading are not lines.
        (
            _pages(
                ["Conf '27, Rome", "Body.", "1"],
                ["Conf '27, Rome", "Body.", "2"],
                ["Conf '27, Rome", "3", "References", "[1] A."],
            ),
            (3, 1),
        ),
        # A line on one page of its parity is no running head, so it stays a line.
        (_pages(["Same line.", "Body."], ["Same line.", "References"]), (2, 2)),
        # Heads that alternate between odd and even pages, as acmart and twoside print them.
        (
            _pages(
                ["The title.", "Body one."],
                ["Author et al.", "Body two."],
                ["A Short Title", "Body three."],
                ["Author et al.", "Body four."],
                ["A Short Title", "REFERENCES", "[1] A."],
            ),
            (5, 1),
        ),
        # Heads that carry the page number, as LNCS prints them.
        (
            _pages(
                ["The title.", "Body one."],
                ["2 F. Author", "Body two."],
                ["Short Title 3", "Body three."],
                ["4 F. Author", "Body four."],
                ["Short Title 5", "Body five."],
                ["6 F. Author", "References", "[1] A."],
            ),
            (6, 1),
        ),
        # A lone number that is not the page's folio stays a line.
        (_pages(["Body."], ["Body two."], ["42", "References"]), (3, 2)),
        # A wrapped lowercase word is not a heading.
        (_pages(["Body."], ["Text about", "references", "more."], ["References"]), (3, 1)),
        (_pages(["Body."], ["7.1 References", "[1] A."]), (2, 1)),
        # A second references list later (an appendix's) never makes the first one running.
        (_pages(["Body."], ["Body.", "References"], ["References", "[9] Z."]), (2, 2)),
        (
            _pages(["Body."], ["Body.", "References"], ["[1] A."], ["References", "[9] Z."]),
            (2, 2),
        ),
        # A content line repeated at two page edges is no head while other pages carry none.
        (_pages(["Results.", "body"], ["body2"], ["Results.", "References"], ["more"]), (3, 2)),
        # A lone number at the edge stays a line unless it is the page's own folio.
        (
            _pages(["a body", "1"], ["b body", "2"], ["c body", "3"], ["42", "References", "4"]),
            (4, 2),
        ),
        # A contents page's entry is not the references.
        (
            _pages(
                ["The title.", "Contents", "1 Introduction", "References", "Body."],
                ["Body two."],
                ["References", "[1] A."],
            ),
            (3, 1),
        ),
        # A review copy's line-number ruler is not lines.
        (
            _pages(
                [f"{i:03d}" for i in range(30)] + ["Body one."],
                [f"{i:03d}" for i in range(30, 60)] + ["Body two."],
                [f"{i:03d}" for i in range(60, 90)] + ["References", "[1] A."],
            ),
            (3, 1),
        ),
        # The same head on every page after the first is a head in a three-page document.
        (
            _pages(["Title.", "Body."], ["Short head", "Body two."], ["Short head", "References"]),
            (3, 1),
        ),
        # Under three pages no head can be confirmed, so the count leans loud.
        (_pages(["Under review", "Body."], ["Under review", "References"]), (2, 2)),
        (_pages(["Body."], ["Works cited", "[1] A."]), (2, 1)),
        (_pages(["Body."], ["REFERENCES", "[1] A."]), (2, 1)),
        # In a headed document a line repeated mid-page stays a line.
        (
            _pages(
                ["Title.", "Body.", "x", "y", "z"],
                ["Head A", "b2", "c2", "d2", "e2"],
                ["Head B", "b3", "Same label.", "d3", "e3"],
                ["Head A", "b4", "c4", "d4", "e4"],
                ["Head B", "b5", "Same label.", "References", "e5", "f5"],
            ),
            (5, 3),
        ),
        # A references heading at the edge of two pages is never a running head.
        (
            _pages(
                ["Title.", "Body."],
                ["Head A", "b2"],
                ["Head B", "References", "[1] A."],
                ["Head A", "b4"],
                ["Head B", "References", "[9] Z."],
            ),
            (3, 1),
        ),
        # One unheaded page after the first keeps every line, so a repeated line is no head.
        (
            _pages(
                ["Title.", "b1"],
                ["Head A", "b2"],
                ["Results.", "x3"],
                ["Head A", "b4"],
                ["Results.", "References"],
                ["Head A", "b6"],
                ["plain7", "z7"],
            ),
            (5, 2),
        ),
        # A line without letters is never a running head.
        (
            _pages(
                ["Title.", "b1"],
                ["Head A", "b2"],
                ["Head B", "* * *", "c3"],
                ["Head A", "b4"],
                ["Head B", "* * *", "References", "r5"],
            ),
            (5, 2),
        ),
        # A line repeated on a page of the other parity is no running head.
        (
            _pages(
                ["Title.", "b1"],
                ["Head A", "Note.", "b2"],
                ["Head B", "Note.", "References"],
                ["Head A", "b4"],
                ["Head B", "b5"],
            ),
            (3, 2),
        ),
        # Only a page's edge lines can be running; a repeated line mid-page stays a line.
        (
            _pages(
                ["Top one.", "Text.", "Same label.", "Text.", "End one."],
                ["Top two.", "Text two.", "End two."],
                ["Top three.", "Text.", "Same label.", "References", "[1] A.", "End."],
            ),
            (3, 4),
        ),
    ],
)
def test_the_references_start_at_their_first_heading_line(lb, pages, start):
    assert lb.references_start(pages) == start


@pytest.mark.parametrize(
    ("pages", "body", "where"),
    [
        (_pages(["Body."], ["References", "[1] A."]), 1, "references start on page 2, line 1"),
        (_pages(["Body."], ["Body.", "References"]), 2, "references start on page 2, line 2"),
        (_pages(["Body."], ["Body."]), None, "no references heading found"),
    ],
)
def test_body_pages_end_where_the_references_start(lb, monkeypatch, pages, body, where):
    monkeypatch.setattr(lb, "page_texts", lambda _pdf, _reading=None: pages)
    assert lb.body_pages(pathlib.Path("doc.pdf"))[:2] == (body, where)


def test_body_pages_say_why_without_pdftotext(lb, monkeypatch, tmp_path):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.7\n")
    monkeypatch.setattr(lb.shutil, "which", lambda _tool: None)
    assert lb.body_pages(pdf) == (None, "pdftotext is not installed", 0)


@pytest.mark.parametrize(
    ("budget", "pages", "body", "over", "measured", "unmeasured"),
    [
        ((7, None, 6), 7, 6, [], "7 of 7 pages, body 6 of 6 pages", False),
        ((7, None, 6), 7, 7, ["body 7 pages, budget 6"], "7 of 7 pages, body 7 of 6 pages", False),
        ((None, None, 6), 8, 6, [], "8 pages, body 6 of 6 pages", False),
        ((None, None, 1), 2, None, [], "2 pages, body ? of 1 page", True),
    ],
)
def test_compare_reads_the_body_limit(lb, budget, pages, body, over, measured, unmeasured):
    assert lb.compare(lb.Budget(*budget), pages, None, body) == (over, measured, unmeasured)


@pytest.mark.parametrize(
    ("pages", "expected", "says"),
    [
        (_pages(["One."], ["Two."], ["References"]), INFO, "body 2 of 2 pages"),
        (
            _pages(["One."], ["Two."], ["Three.", "References"]),
            BLOCK,
            "body 3 pages, budget 2 (references start on page 3, line 2)",
        ),
        (_pages(["One."], ["Two."], ["Three."]), REVIEW, "no references heading found"),
    ],
)
def test_the_gate_blocks_a_body_past_its_pages(lb, monkeypatch, tmp_path, pages, expected, says):
    monkeypatch.setattr(lb, "page_texts", lambda _pdf, _reading=None: pages)
    monkeypatch.setattr(lb, "pdf_pages", lambda _pdf: 3)
    (severity, message, anchor) = lb.assess(
        "% budget: 3 pages, 2 body pages\n",
        tmp_path / "doc.pdf",
        hint="h",
        source_name="doc.tex",
        tex=tmp_path / "doc.tex",
    )[0]
    assert (severity, anchor) == (expected, "doc.pdf")
    assert says in message


def _text_pdf(path: pathlib.Path, pages: list[list[str]]) -> None:
    """A PDF whose pages print the given lines top to bottom, in Helvetica."""

    def escape(text: str) -> str:
        return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    kids = []
    for lines in pages:
        shown = " T* ".join(f"({escape(line)}) Tj" for line in lines)
        stream = f"BT /F1 12 Tf 72 720 Td 16 TL {shown} ET".encode()
        objects.append(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream))
        content = len(objects)
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 3 0 R >> >> /Contents %d 0 R >>" % content
        )
        kids.append(f"{len(objects)} 0 R")
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>".encode()
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    path.write_bytes(bytes(out))


@pytest.mark.skipif(shutil.which("pdftotext") is None, reason="pdftotext (poppler) not installed")
@pytest.mark.parametrize(
    ("pages", "body"),
    [
        ([["A body line."], ["Another body line."], ["References", "[1] An entry."]], 2),
        ([["A body line."], ["Another body line."], ["The last body line.", "References"]], 3),
    ],
)
def test_body_pages_read_a_real_pdf_through_pdftotext(lb, tmp_path, pages, body):
    pdf = tmp_path / "doc.pdf"
    _text_pdf(pdf, pages)
    assert lb.pdf_pages(pdf) == len(pages)
    assert lb.body_pages(pdf)[0] == body


def test_a_body_page_budget_alone_does_not_count_words(lb, monkeypatch, tmp_path):
    monkeypatch.setattr(
        lb, "page_texts", lambda _pdf, _reading=None: _pages(["One."], ["References"])
    )
    monkeypatch.setattr(lb, "pdf_pages", lambda _pdf: 2)
    monkeypatch.setattr(lb, "tex_words", lambda _tex: pytest.fail("texcount ran"))
    (severity, _message, _anchor) = lb.assess(
        "% budget: 1 body page\n",
        tmp_path / "doc.pdf",
        hint="h",
        source_name="doc.tex",
        tex=tmp_path / "doc.tex",
    )[0]
    assert severity == INFO


def test_only_a_body_overrun_names_where_the_references_start(lb, monkeypatch, tmp_path):
    monkeypatch.setattr(
        lb, "page_texts", lambda _pdf, _reading=None: _pages(["One."], ["Two."], ["References"])
    )
    monkeypatch.setattr(lb, "pdf_pages", lambda _pdf: 5)
    (severity, message, _anchor) = lb.assess(
        "% budget: 4 pages, 3 body pages\n",
        tmp_path / "doc.pdf",
        hint="h",
        source_name="doc.tex",
        tex=tmp_path / "doc.tex",
    )[0]
    assert severity == BLOCK
    assert "5 pages, budget 4" in message
    assert "references start" not in message


@pytest.mark.skipif(shutil.which("pdftotext") is None, reason="pdftotext (poppler) not installed")
def test_alternating_running_heads_in_a_real_pdf_are_not_body(lb, tmp_path):
    pdf = tmp_path / "doc.pdf"
    _text_pdf(
        pdf,
        [
            ["The title.", "Body one."],
            ["Author et al.", "Body two."],
            ["A Short Title", "Body three."],
            ["Author et al.", "Body four."],
            ["A Short Title", "References", "[1] An entry."],
        ],
    )
    assert lb.body_pages(pdf) == (4, "references start on page 5, line 1", 1)


def test_body_pages_reuse_text_the_caller_already_read(lb, monkeypatch):
    monkeypatch.setattr(lb.shutil, "which", lambda _tool: pytest.fail("pdftotext ran"))
    reading = "Body one.\n\fBody two.\n\fReferences\n[1] A.\n\f"
    assert lb.body_pages(pathlib.Path("doc.pdf"), reading) == (
        2,
        "references start on page 3, line 1",
        1,
    )


def test_a_number_inside_a_line_is_kept_when_matching_heads(lb):
    pages = _pages(
        ["Title.", "b1"],
        ["Head A", "Table 2 x"],
        ["Head B", "Fig 3a", "c3"],
        ["Head A", "b4"],
        ["Head B", "Fig 5a", "References"],
    )
    assert lb.references_start(pages) == (5, 2)


@pytest.mark.parametrize(
    ("pages", "starts"),
    [
        # A head that names the section prints REFERENCES above the body that ends it.
        (
            _pages(
                ["Body one."], ["Body two."], ["REFERENCES", "The last body line.", "REFERENCES"]
            ),
            [(3, 1), (3, 3)],
        ),
        # A contents list run on to a page without its "Contents" line.
        (
            _pages(["Contents", "Intro"], ["References", "Body."], ["Body."], ["References"]),
            [(2, 1), (4, 1)],
        ),
        # A table column called References.
        (_pages(["Tool", "References", "Year"], ["Body."], ["References"]), [(1, 2), (3, 1)]),
        # Folios offset from the page index (a first page set to 101).
        (
            _pages(["Title", "Intro", "101"], ["Body.", "102"], ["103", "References", "[1] x"]),
            [(3, 1)],
        ),
        # An offset seen once is no folio pattern, so the number stays a line.
        (_pages(["Title", "Intro"], ["57", "References", "[1] x"]), [(2, 2)]),
        # One other page with the same offset is chance, not a folio sequence.
        (_pages(["Title", "Intro", "40"], ["Body.", "Text."], ["42", "References"]), [(3, 2)]),
        # A ruler on full pages marks the copy, so the short last page drops its numbers too.
        (
            _pages(
                [f"{i:03d}" for i in range(30)] + ["Body one."],
                [f"{i:03d}" for i in range(30, 33)] + ["References", "[1] A."],
            ),
            [(2, 1)],
        ),
    ],
)
def test_every_heading_like_line_is_found(lb, pages, starts):
    assert lb.references_starts(pages) == starts


@pytest.mark.parametrize(
    ("pages", "total", "expected", "says"),
    [
        # Several heading-like lines and room to doubt: a look, not a pass.
        (
            _pages(["One."], ["Two."], ["REFERENCES", "Three.", "REFERENCES"]),
            3,
            REVIEW,
            "2 references headings (page 3 line 1, page 3 line 3)",
        ),
        # The earliest already runs over, so the body does too.
        (
            _pages(["One."], ["Two."], ["Three.", "References"], ["References"]),
            4,
            BLOCK,
            "body 3 pages, budget 2",
        ),
        # A PDF no longer than the body limit cannot run over, heading or not.
        (_pages(["One."], ["Two."]), 2, INFO, "body 2 of 2 pages"),
        (_pages(["References"], ["References"]), 2, INFO, "body 0 of 2 pages"),
    ],
)
def test_the_gate_passes_a_body_only_when_it_is_sure(
    lb, monkeypatch, tmp_path, pages, total, expected, says
):
    monkeypatch.setattr(lb, "page_texts", lambda _pdf, _reading=None: pages)
    monkeypatch.setattr(lb, "pdf_pages", lambda _pdf: total)
    (severity, message, _anchor) = lb.assess(
        "% budget: 2 body pages\n",
        tmp_path / "doc.pdf",
        hint="h",
        source_name="doc.tex",
        tex=tmp_path / "doc.tex",
    )[0]
    assert severity == expected, message
    assert says in message


def test_an_empty_reading_falls_back_to_reading_the_pdf(lb, monkeypatch):
    monkeypatch.setattr(lb.prose_check, "reading_text", lambda _pdf: "Body.\n\fReferences\n")
    assert lb.page_texts(pathlib.Path("doc.pdf"), "") == ["Body.\n", "References\n"]
