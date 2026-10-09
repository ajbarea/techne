"""graphe:slides on a reveal.js web deck, checked and rendered in a real Chromium.

Each case copies the starter deck and breaks one thing. Chromium comes from Playwright
(`playwright install chromium`); a machine without it declares so with
TECHNE_NO_BROWSER=1, or the suite fails rather than skipping every web case unseen.
"""

from __future__ import annotations

import importlib.util
import os
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
STARTER = ROOT / "plugins" / "graphe" / "skills" / "slides" / "templates" / "web"
OPTED_OUT = os.environ.get("TECHNE_NO_BROWSER") == "1"
HAVE_LIBS = all(
    importlib.util.find_spec(m) is not None for m in ("playwright", "axe_playwright_python")
)


def _chromium_runs() -> bool:
    if not HAVE_LIBS:
        return False
    from playwright.sync_api import sync_playwright  # ty: ignore[unresolved-import]

    try:
        with sync_playwright() as pw:
            pw.chromium.launch().close()
    except Exception:
        return False
    return True


HAVE_BROWSER = not OPTED_OUT and _chromium_runs()
needs_browser = pytest.mark.skipif(
    not HAVE_BROWSER, reason="no Chromium (declared by TECHNE_NO_BROWSER)"
)


def test_the_browser_is_present_or_its_absence_is_declared():
    """Green by absence is the failure this guards."""
    assert HAVE_BROWSER or OPTED_OUT, (
        "Playwright's Chromium is not available and TECHNE_NO_BROWSER is unset: every web "
        "deck case would have skipped. Run `make test-unit` after `uv run --with "
        "playwright==1.63.0 playwright install chromium`, or set TECHNE_NO_BROWSER=1."
    )


def test_the_pins_agree_everywhere_they_are_written(sl):
    """slides.py, the Makefile, CI and SKILL.md each name the browser pins."""
    for path in ("Makefile", ".github/workflows/validate.yml"):
        text = (ROOT / path).read_text()
        assert sl.PLAYWRIGHT in text, f"{path} does not pin {sl.PLAYWRIGHT}"
    for path in ("Makefile", "plugins/graphe/skills/slides/SKILL.md"):
        assert sl.AXE in (ROOT / path).read_text(), f"{path} does not pin {sl.AXE}"


def test_the_vendored_reveal_is_the_version_the_skill_names():
    head = (STARTER / "vendor" / "reveal" / "reveal.js").read_text()[:400]
    skill = (STARTER.parent.parent / "SKILL.md").read_text()
    assert "reveal.js" in head
    version = re.search(r"reveal\.js (\d+\.\d+\.\d+)", skill)
    assert version, "SKILL.md names no reveal.js version"
    package = STARTER / "vendor" / "reveal" / "VERSION"
    assert package.read_text().strip() == version.group(1)


@pytest.fixture
def web(tmp_path):
    """A copy of the starter deck, with a helper that edits one of its files."""
    deck = tmp_path / "deck"
    shutil.copytree(STARTER, deck)

    def edit(old: str, new: str, name: str = "index.html") -> pathlib.Path:
        path = deck / name
        text = path.read_text()
        assert old in text, f"{old!r} not in {name}"
        path.write_text(text.replace(old, new, 1))
        return deck / "index.html"

    edit.index = deck / "index.html"  # ty: ignore[unresolved-attribute]
    return edit


CLAIM = "<h2>[Claim headline: one full sentence the figure proves]</h2>"


def _check(sl, path, **kw):
    return sl.check(path, **kw)


@needs_browser
def test_the_starter_passes_with_nothing_to_review(sl, web):
    found = _check(sl, web.index)
    assert [str(f) for f in found if f.severity != "INFO"] == []
    assert sl.verdict(found)[0] == 0


@needs_browser
def test_a_slide_without_a_heading_blocks(sl, web, gates):
    found = _check(sl, web(CLAIM, "<p>[No heading]</p>"))
    assert ("BLOCK", "no-title") in gates(found)


@needs_browser
def test_low_contrast_text_blocks(sl, web, gates):
    found = _check(sl, web(CLAIM, CLAIM + '<p style="color:#9ca3af">faint</p>'))
    assert ("BLOCK", "contrast") in gates(found)


@needs_browser
def test_an_image_without_alt_text_blocks(sl, web, gates):
    pixel = "data:image/gif;base64,R0lGODlhAQABAAAAACw="
    found = _check(sl, web(CLAIM, CLAIM + f'<img src="{pixel}" width="40" height="40">'))
    assert ("BLOCK", "alt-text") in gates(found)


@needs_browser
def test_a_missing_file_blocks(sl, web, gates):
    found = _check(sl, web(CLAIM, CLAIM + '<img src="figs/gone.png" alt="gone">'))
    assert ("BLOCK", "asset") in gates(found)


@needs_browser
def test_a_value_with_no_data_behind_it_blocks(sl, web, gates):
    found = _check(sl, web(CLAIM, CLAIM + '<p data-value="results.nothing"></p>'))
    assert ("BLOCK", "script") in gates(found)


@needs_browser
def test_an_em_dash_blocks(sl, web, gates):
    found = _check(sl, web(CLAIM, CLAIM + "<p>before — after</p>"))
    assert ("BLOCK", "em-dash") in gates(found)


@needs_browser
def test_a_network_dependency_warns(sl, web, gates):
    link = '<link rel="stylesheet" href="https://example.invalid/font.css">'
    found = _check(sl, web('<link rel="stylesheet" href="deck.css">', link))
    assert ("WARN", "offline") in gates(found)


@needs_browser
def test_text_past_the_slide_edge_warns(sl, web, gates):
    wide = '<p style="width:2400px">[a line far wider than the slide]</p>'
    found = _check(sl, web(CLAIM, CLAIM + wide))
    assert ("WARN", "overflow") in gates(found)


@needs_browser
def test_small_text_warns_on_desktop_and_phone(sl, web, gates):
    found = _check(sl, web(CLAIM, CLAIM + '<p style="font-size:11px">[fine print]</p>'))
    assert {("WARN", "small-text"), ("WARN", "phone")} <= gates(found)


@needs_browser
def test_motion_that_ignores_reduced_motion_warns(sl, web, gates):
    css = (STARTER / "deck.css").read_text()
    reduced = css[css.index("@media (prefers-reduced-motion") : css.index("@media print")]
    spin = "h2 { animation: spin 3s linear infinite; }\n@keyframes spin { to { opacity: 0.9; } }\n"
    web(reduced, spin, "deck.css")
    found = _check(sl, web.index)
    assert ("WARN", "motion") in gates(found)


@needs_browser
def test_a_talk_slide_without_notes_warns(sl, web, gates):
    note = '<aside class="notes">[Here\'s the problem.'
    path = web(note, '<aside class="unused">[Here\'s the problem.')
    found = _check(sl, path)
    assert ("WARN", "no-notes") in gates(found)


@needs_browser
def test_a_page_that_is_not_a_reveal_deck_is_unreadable(sl, tmp_path, gates):
    page = tmp_path / "page.html"
    page.write_text("<!doctype html><title>t</title><h1>Hello</h1>")
    assert ("ERROR", "unreadable") in gates(_check(sl, page))


def test_the_script_reads_notes_without_a_browser(sl):
    code, out = sl.script(STARTER / "index.html")
    assert code == 0
    assert "## 3. [Claim headline: one full sentence the figure proves]" in out
    assert "Walk the figure left to right" in out
    talk, backup = out.split("# Backup slides")
    assert "## 12. Backup slides" in backup
    assert "Backup" not in talk.split("\n", 2)[2]


def test_nested_sections_are_read_as_their_inner_slides(sl, tmp_path):
    deck = tmp_path / "stack.html"
    deck.write_text(
        '<div class="slides"><section><section><h2>One</h2><aside class="notes">first</aside>'
        "</section><section><h2>Two</h2></section></section></div>"
    )
    assert sl.html_slides(deck) == [("One", "first"), ("Two", "")]


@needs_browser
def test_render_writes_slides_phone_views_and_a_print_pdf(sl, web, tmp_path):
    out = tmp_path / "render"
    assert sl.render(web.index, out) == 0
    count = len(sl.html_slides(web.index))
    assert len(sorted(out.glob("slide-*.png"))) == count
    assert len(sorted(out.glob("phone-[0-9]*.png"))) == count
    pdf = out / "index.pdf"
    assert pdf.read_bytes()[:5] == b"%PDF-"
    if shutil.which("pdfinfo"):
        info = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True).stdout
        assert re.search(rf"Pages:\s+{count}\b", info)
