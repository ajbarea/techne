"""Unit tests for techne:pdf's markdown-to-Typst front end.

The compile step needs the typst wheel and is covered in test_pdf_render_e2e.
Everything here is string handling: what gets lifted out of the markdown, and
what reaches the .typ driver.
"""

from __future__ import annotations

import pytest

# ------------------------------------------------------------- escaping --


def test_a_quote_in_a_title_does_not_end_the_typst_string(rn):
    assert rn._typst_str('A "quoted" word') == '"A \\"quoted\\" word"'


def test_a_backslash_is_escaped_before_the_quotes_are(rn):
    r"""Escaping quotes first would turn \" into \\", which closes the string
    and leaves the rest of the title as Typst code."""
    assert rn._typst_str(r"C:\path") == r'"C:\\path"'
    assert rn._typst_str('back\\ and "quote"') == '"back\\\\ and \\"quote\\""'


def test_a_font_list_is_a_trailing_comma_tuple(rn):
    """A one-element Typst tuple without the trailing comma is a plain string."""
    assert rn._typst_list(["Charter"]) == '("Charter",)'
    assert rn._typst_list(["A", "B"]) == '("A", "B",)'


# -------------------------------------------------------- front matter --


def test_title_and_italic_subtitle_are_both_lifted(rn):
    title, subtitle, body = rn.split_front_matter("# The Title\n*A subtitle*\n\nBody text.\n")
    assert (title, subtitle) == ("The Title", "A subtitle")
    assert body == "Body text."


def test_an_underscore_subtitle_is_read_the_same_way(rn):
    _, subtitle, _ = rn.split_front_matter("# T\n_A subtitle_\n\nBody.\n")
    assert subtitle == "A subtitle"


def test_leading_blank_lines_do_not_hide_the_title(rn):
    title, _, body = rn.split_front_matter("\n\n# The Title\n\nBody.\n")
    assert title == "The Title"
    assert body == "Body."


def test_a_document_with_no_heading_keeps_all_of_its_text(rn):
    title, subtitle, body = rn.split_front_matter("Just a paragraph.\n")
    assert title is None and subtitle is None
    assert body == "Just a paragraph."


def test_bold_is_not_mistaken_for_a_subtitle(rn):
    title, subtitle, body = rn.split_front_matter("# T\n**Not a subtitle**\n\nBody.\n")
    assert title == "T"
    assert subtitle is None
    assert body.startswith("**Not a subtitle**")


def test_ordinary_first_paragraph_stays_in_the_body(rn):
    _, subtitle, body = rn.split_front_matter("# T\n\nA normal opening line.\n")
    assert subtitle is None
    assert body == "A normal opening line."


def test_an_italic_line_further_down_is_left_alone(rn):
    _, subtitle, body = rn.split_front_matter("# T\n\nOpening.\n\n*An aside.*\n")
    assert subtitle is None
    assert "*An aside.*" in body


def test_a_subtitle_without_a_title_is_not_lifted(rn):
    title, subtitle, body = rn.split_front_matter("*Italic first line.*\n\nBody.\n")
    assert (title, subtitle) == (None, None)
    assert body.startswith("*Italic first line.*")


def test_a_deeper_heading_is_not_the_title(rn):
    title, _, body = rn.split_front_matter("## Section\n\nBody.\n")
    assert title is None
    assert body.startswith("## Section")


# ------------------------------------------------------- .typ assembly --


def test_every_template_placeholder_is_filled(rn, tmp_path):
    """A placeholder added to the template without a matching replace reaches
    Typst verbatim and renders as literal braces."""
    src = tmp_path / "doc.md"
    src.write_text("# T\n*S*\n\nBody.\n")
    typ = rn.build_typ(src, tmp_path)
    assert "{{" not in typ.read_text()


def test_the_body_is_written_without_the_title_block(rn, tmp_path):
    src = tmp_path / "doc.md"
    src.write_text("# The Title\n*A subtitle*\n\nBody text.\n")
    rn.build_typ(src, tmp_path)
    body = (tmp_path / "doc.body.md").read_text()
    assert body == "Body text."
    assert "The Title" not in body


def test_an_absent_subtitle_becomes_typst_none(rn, tmp_path):
    src = tmp_path / "doc.md"
    src.write_text("# The Title\n\nBody.\n")
    filled = rn.build_typ(src, tmp_path).read_text()
    assert "none" in filled
    assert '"The Title"' in filled


def test_an_untitled_document_falls_back_to_its_filename(rn, tmp_path):
    src = tmp_path / "quarterly-report.md"
    src.write_text("Body only.\n")
    assert '"quarterly-report"' in rn.build_typ(src, tmp_path).read_text()


def test_the_driver_points_at_the_body_by_name_not_by_path(rn, tmp_path):
    """Typst compiles with the work dir as root; an absolute path escapes it."""
    src = tmp_path / "doc.md"
    src.write_text("# T\n\nBody.\n")
    filled = rn.build_typ(src, tmp_path).read_text()
    assert '"doc.body.md"' in filled
    assert str(tmp_path) not in filled


# ------------------------------------------------------------- reading --


def test_embedded_font_families_are_read_through_their_subset_tags(rn, tmp_path):
    pdf = tmp_path / "doc.pdf"
    pdf.write_text(
        "/BaseFont /ABCDEF+LibertinusSerif-Regular\n"
        "/BaseFont /GHIJKL+LibertinusSerif-Bold\n"
        "/BaseFont /TeXGyreHeros\n"
    )
    assert rn.pdf_fonts(pdf) == ["LibertinusSerif", "TeXGyreHeros"]


# ---------------------------------------------------------------- main --


def test_an_empty_directory_is_reported_rather_than_rendered(rn, tmp_path, capsys):
    assert rn.main([str(tmp_path), str(tmp_path / "out")]) == 2
    assert "no markdown files" in capsys.readouterr().err


def test_font_drift_fails_the_run(rn, tmp_path, monkeypatch):
    src = tmp_path / "doc.md"
    src.write_text("# T\n\nBody.\n")
    monkeypatch.setattr(rn, "render", lambda s, o: (o / "doc.pdf", ["LibertinusSerif"]))
    code = rn.main([str(src), str(tmp_path / "out"), "--check-fonts", "Charter"])
    assert code == 1


def test_the_expected_font_set_passes(rn, tmp_path, monkeypatch):
    src = tmp_path / "doc.md"
    src.write_text("# T\n\nBody.\n")
    monkeypatch.setattr(rn, "render", lambda s, o: (o / "doc.pdf", ["Charter", "TeXGyreHeros"]))
    code = rn.main([str(src), str(tmp_path / "out"), "--check-fonts", "TeXGyreHeros", "Charter"])
    assert code == 0


def test_a_font_check_is_order_insensitive(rn, tmp_path, monkeypatch):
    src = tmp_path / "doc.md"
    src.write_text("# T\n\nBody.\n")
    monkeypatch.setattr(rn, "render", lambda s, o: (o / "doc.pdf", ["A", "B"]))
    assert rn.main([str(src), str(tmp_path / "out"), "--check-fonts", "B", "A"]) == 0


@pytest.mark.parametrize("names", [["doc-b.md", "doc-a.md"], ["z.md", "a.md", "m.md"]])
def test_a_directory_renders_every_markdown_file(rn, tmp_path, monkeypatch, names):
    for name in names:
        (tmp_path / name).write_text("# T\n\nBody.\n")
    seen = []
    monkeypatch.setattr(rn, "render", lambda s, o: (seen.append(s.name), (o / "x.pdf", ["A"]))[1])
    assert rn.main([str(tmp_path), str(tmp_path / "out")]) == 0
    assert seen == sorted(names)
