"""Unit tests for techne:slides' check gates and renderer choice.

Decks are built in-test as minimal OOXML packages: only the parts the checker
reads (presentation, slide, layout, master, notes and their rels). No Office
install and no pptx library is needed.
"""

from __future__ import annotations

import pathlib
import zipfile

import pytest

ERROR, BLOCK, WARN, REVIEW, INFO = "ERROR", "BLOCK", "WARN", "REVIEW", "INFO"

_NS = (
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
    'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
)
_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG = 'xmlns="http://schemas.openxmlformats.org/package/2006/relationships"'
EMU = 914400


def _rels(*entries: tuple[str, str, str]) -> str:
    body = "".join(
        f'<Relationship Id="{i}" Type="{_REL}/{t}" Target="{tg}"/>' for i, t, tg in entries
    )
    return f"<Relationships {_PKG}>{body}</Relationships>"


def _run(
    text: str,
    color: str | None = "111111",
    size: float | None = 20,
    bold: bool = False,
    font: str | None = "Calibri",
) -> str:
    attrs = (f' sz="{int(size * 100)}"' if size else "") + (' b="1"' if bold else "")
    fill = f'<a:solidFill><a:srgbClr val="{color}"/></a:solidFill>' if color else ""
    latin = f'<a:latin typeface="{font}"/>' if font else ""
    return f'<a:r><a:rPr lang="en-US"{attrs}>{fill}{latin}</a:rPr><a:t>{text}</a:t></a:r>'


def _xfrm(x: float, y: float, w: float, h: float) -> str:
    return (
        f'<a:xfrm><a:off x="{int(x * EMU)}" y="{int(y * EMU)}"/>'
        f'<a:ext cx="{int(w * EMU)}" cy="{int(h * EMU)}"/></a:xfrm>'
    )


def title(text: str, color: str = "111111") -> str:
    # Attributes split across lines, as pptxgenjs writes them.
    return (
        '<p:sp><p:nvSpPr><p:cNvPr id="2" name="t"/><p:cNvSpPr/>'
        '<p:nvPr><p:ph\n\t\t idx="100"\n\t\t type="title"\n\t\t/>'
        f"</p:nvPr></p:nvSpPr><p:spPr>{_xfrm(0.5, 0.5, 12, 1)}</p:spPr>"
        f"<p:txBody><a:bodyPr/><a:p>{_run(text, color, 32, True)}</a:p></p:txBody></p:sp>"
    )


def textbox(
    text: str,
    color: str = "111111",
    size: float = 20,
    bold: bool = False,
    at: tuple[float, float, float, float] = (1, 2, 4, 1),
    font: str = "Calibri",
) -> str:
    return (
        f'<p:sp><p:nvSpPr><p:cNvPr id="3" name="b"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>'
        f"<p:spPr>{_xfrm(*at)}<a:noFill/></p:spPr>"
        f"<p:txBody><a:bodyPr/><a:p>{_run(text, color, size, bold, font)}</a:p></p:txBody></p:sp>"
    )


def rect(fill: str, at: tuple[float, float, float, float] = (0.5, 1.5, 6, 2)) -> str:
    return (
        f'<p:sp><p:nvSpPr><p:cNvPr id="4" name="r"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>'
        f"<p:spPr>{_xfrm(*at)}"
        f'<a:solidFill><a:srgbClr val="{fill}"/></a:solidFill></p:spPr></p:sp>'
    )


def picture(descr: str = "") -> str:
    return (
        f'<p:pic><p:nvPicPr><p:cNvPr id="5" name="img" descr="{descr}"/>'
        "<p:cNvPicPr/><p:nvPr/></p:nvPicPr>"
        f"<p:blipFill/><p:spPr>{_xfrm(7, 2, 4, 3)}</p:spPr></p:pic>"
    )


def slide_number() -> str:
    return (
        '<p:sp><p:nvSpPr><p:cNvPr id="6" name="n"/><p:cNvSpPr/>'
        '<p:nvPr><p:ph type="sldNum"/></p:nvPr></p:nvSpPr>'
        f"<p:spPr>{_xfrm(0.5, 7, 1, 0.3)}</p:spPr><p:txBody><a:bodyPr/><a:p>"
        '<a:fld id="{1}" type="slidenum"><a:rPr lang="en-US" sz="1000"/><a:t>3</a:t></a:fld>'
        "</a:p></p:txBody></p:sp>"
    )


@pytest.fixture
def deck(tmp_path):
    """Write a deck from a list of slides, each a list of shape XML strings."""

    def _deck(
        *slides: list[str], bg: str = "FFFFFF", notes: bool = True, order: list[int] | None = None
    ) -> pathlib.Path:
        path = tmp_path / "deck.pptx"
        order = order or list(range(1, len(slides) + 1))
        with zipfile.ZipFile(path, "w") as z:
            ids = "".join(f'<p:sldId id="{255 + n}" r:id="rId{n}"/>' for n in order)
            z.writestr(
                "ppt/presentation.xml",
                f"<p:presentation {_NS}><p:sldIdLst>{ids}</p:sldIdLst></p:presentation>",
            )
            z.writestr(
                "ppt/_rels/presentation.xml.rels",
                _rels(
                    *[
                        (f"rId{n}", "slide", f"slides/slide{n}.xml")
                        for n in range(1, len(slides) + 1)
                    ]
                ),
            )
            z.writestr(
                "ppt/slideMasters/slideMaster1.xml",
                f"<p:sldMaster {_NS}><p:cSld><p:bg><p:bgPr>"
                f'<a:solidFill><a:srgbClr val="{bg}"/></a:solidFill>'
                "</p:bgPr></p:bg><p:spTree/></p:cSld></p:sldMaster>",
            )
            z.writestr(
                "ppt/slideLayouts/slideLayout1.xml",
                f"<p:sldLayout {_NS}><p:cSld><p:spTree/></p:cSld></p:sldLayout>",
            )
            z.writestr(
                "ppt/slideLayouts/_rels/slideLayout1.xml.rels",
                _rels(("rId1", "slideMaster", "../slideMasters/slideMaster1.xml")),
            )
            for n, shapes in enumerate(slides, 1):
                z.writestr(
                    f"ppt/slides/slide{n}.xml",
                    f"<p:sld {_NS}><p:cSld><p:spTree>{''.join(shapes)}</p:spTree></p:cSld></p:sld>",
                )
                rels = [("rId1", "slideLayout", "../slideLayouts/slideLayout1.xml")]
                if notes:
                    rels.append(("rId2", "notesSlide", f"../notesSlides/notesSlide{n}.xml"))
                    z.writestr(
                        f"ppt/notesSlides/notesSlide{n}.xml",
                        f"<p:notes {_NS}><p:cSld><p:spTree><p:sp><p:nvSpPr>"
                        '<p:cNvPr id="2" name="n"/><p:cNvSpPr/>'
                        '<p:nvPr><p:ph type="body"/></p:nvPr></p:nvSpPr>'
                        f"<p:txBody><a:bodyPr/><a:p>{_run('Say this.')}</a:p>"
                        "</p:txBody></p:sp></p:spTree></p:cSld></p:notes>",
                    )
                z.writestr(f"ppt/slides/_rels/slide{n}.xml.rels", _rels(*rels))
        return path

    return _deck


def _blocks(sl, path, **kw) -> set[tuple[str, str]]:
    return {(f.severity, f.gate) for f in sl.check(path, **kw)}


# ---------------------------------------------------------------- colour --


def test_contrast_bounds(sl):
    assert sl.contrast("FFFFFF", "000000") == pytest.approx(21.0)
    assert sl.contrast("777777", "777777") == pytest.approx(1.0)


def test_large_text_definition(sl):
    assert sl.is_large(18, False)
    assert sl.is_large(14, True)
    assert not sl.is_large(14, False)
    assert not sl.is_large(None, True)


# ----------------------------------------------------------------- gates --


def test_clean_deck_passes(sl, deck):
    path = deck([title("Opening"), textbox("Hello")], [title("Second point"), textbox("More")])
    found = sl.check(path)
    code, _ = sl.verdict(found)
    assert code == 0
    assert not [f for f in found if f.severity in (BLOCK, WARN, REVIEW)]


def test_multiline_placeholder_tag_counts_as_a_title(sl, deck):
    """The grep trap: `<p:ph` and `type="title"` sit on different lines."""
    path = deck([title("Real title"), textbox("x")])
    assert (BLOCK, "no-title") not in _blocks(sl, path)


def test_text_box_title_is_not_a_title(sl, deck):
    path = deck([textbox("Looks like a title", size=32, bold=True)])
    found = sl.check(path)
    assert (BLOCK, "no-title") in {(f.severity, f.gate) for f in found}
    assert sl.verdict(found)[0] == 2


def test_low_contrast_blocks_normal_text_at_aaa(sl, deck):
    # 6B6B63 on FAFAF8 is 5.14:1: fails 7:1, passes 4.5:1.
    path = deck([title("T"), textbox("muted", color="6B6B63", size=16)], bg="FAFAF8")
    assert (BLOCK, "contrast") in _blocks(sl, path)
    assert (BLOCK, "contrast") not in _blocks(sl, path, level="AA")


def test_large_text_gets_the_lower_threshold(sl, deck):
    path = deck([title("T"), textbox("big", color="6B6B63", size=24)], bg="FAFAF8")
    assert (BLOCK, "contrast") not in _blocks(sl, path)


def test_text_over_a_filled_shape_is_measured_against_the_fill(sl, deck):
    """White text in a separate text box on a dark card: the slide background is not behind it."""
    on_card = deck([title("T"), rect("00527F"), textbox("white", color="FFFFFF", at=(1, 2, 4, 1))])
    assert (BLOCK, "contrast") not in _blocks(sl, on_card)
    bare = deck([title("T"), textbox("white", color="FFFFFF", at=(1, 2, 4, 1))])
    assert (BLOCK, "contrast") in _blocks(sl, bare)


def test_a_fill_drawn_after_the_text_is_not_behind_it(sl, deck):
    path = deck([title("T"), textbox("white", color="FFFFFF", at=(1, 2, 4, 1)), rect("00527F")])
    assert (BLOCK, "contrast") in _blocks(sl, path)


def test_picture_needs_alt_text(sl, deck):
    assert (BLOCK, "alt-text") in _blocks(sl, deck([title("T"), picture()]))
    assert (BLOCK, "alt-text") not in _blocks(sl, deck([title("T"), picture("four apps")]))


def test_em_dash_blocks(sl, deck):
    assert (BLOCK, "em-dash") in _blocks(sl, deck([title("T"), textbox("this \u2014 that")]))


def test_small_text_warns_but_the_slide_number_field_is_exempt(sl, deck):
    small = deck([title("T"), textbox("fine print", size=11)])
    assert (WARN, "small-text") in _blocks(sl, small)
    numbered = deck([title("T"), textbox("x"), slide_number()])
    assert (WARN, "small-text") not in _blocks(sl, numbered)


def test_non_portable_font_warns(sl, deck):
    assert (WARN, "font") in _blocks(sl, deck([title("T"), textbox("x", font="Inter")]))


def test_missing_notes_warn(sl, deck):
    assert (WARN, "no-notes") in _blocks(sl, deck([title("T"), textbox("x")], notes=False))


def test_duplicate_titles_warn(sl, deck):
    assert (WARN, "duplicate-title") in _blocks(sl, deck([title("Same")], [title("Same")]))


def test_figures_are_reviewed_on_talk_slides_only(sl, deck):
    path = deck(
        [title("Opening"), textbox("23 September 2026")],
        [title("Result"), textbox("75% leaked, 6 of 8")],
        [title("Backup slides")],
        [title("Table"), textbox("450/541 killed, 2.67")],
    )
    figures = [f.slide for f in sl.check(path) if f.gate == "figures"]
    assert figures == [2]


def test_labels_are_not_figures(sl, deck):
    path = deck(
        [title("Opening")], [title("Lessons"), textbox("01 Name it. 02 Enforce it. Stage 4")]
    )
    assert not [f for f in sl.check(path) if f.gate == "figures"]


def test_dense_body_text_is_reviewed(sl, deck):
    words = " ".join(["word"] * 70)
    path = deck([title("Opening")], [title("Wall of text"), textbox(words, at=(0.5, 2, 12, 4))])
    dense = [f for f in sl.check(path) if f.gate == "dense"]
    assert [f.slide for f in dense] == [2]


def test_slide_order_follows_the_id_list_not_file_names(sl, deck):
    path = deck([title("First file")], [textbox("no title here")], order=[2, 1])
    found = [f for f in sl.check(path) if f.gate == "no-title"]
    assert [f.slide for f in found] == [1]


def test_unreadable_file_is_an_error(sl, tmp_path):
    bad = tmp_path / "not.pptx"
    bad.write_text("plain text")
    found = sl.check(bad)
    assert (ERROR, "unreadable") in {(f.severity, f.gate) for f in found}
    assert sl.verdict(found)[0] == 1


# ---------------------------------------------------------------- render --


def test_renderer_prefers_powerpoint(sl, monkeypatch):
    monkeypatch.setattr(sl, "powerpoint_available", lambda: True)
    monkeypatch.setattr(sl, "libreoffice", lambda: "/usr/bin/soffice")
    assert sl.pick_renderer() == "powerpoint"
    assert sl.pick_renderer("libreoffice") == "libreoffice"


def test_renderer_falls_back_then_refuses(sl, monkeypatch):
    monkeypatch.setattr(sl, "powerpoint_available", lambda: False)
    monkeypatch.setattr(sl, "libreoffice", lambda: "/usr/bin/soffice")
    assert sl.pick_renderer() == "libreoffice"
    with pytest.raises(SystemExit):
        sl.pick_renderer("powerpoint")
    monkeypatch.setattr(sl, "libreoffice", lambda: None)
    with pytest.raises(SystemExit):
        sl.pick_renderer()


def test_export_script_only_quits_an_instance_it_started(sl):
    """PowerPoint is single-instance: an unguarded Quit() closes the user's open decks."""
    script = sl.PS1.format(src="C:\\a.pptx", dst="C:\\a.pdf")
    assert "$before = $app.Presentations.Count" in script
    assert "if ($before -eq 0) { $app.Quit() }" in script
    script.encode("ascii")  # PowerShell 5 misreads non-ASCII in a BOM-less .ps1
