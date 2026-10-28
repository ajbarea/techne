"""The shared docs-site stylesheet and script in a real Chromium: code in a table stays whole
even when a site's own CSS, which loads after shared.css, tries to make it wrap."""

from __future__ import annotations

import pathlib

import pytest
from test_slides_web import needs_browser

SHARED = (
    pathlib.Path(__file__).resolve().parent.parent
    / "plugins/techne/skills/docs-site/templates/shared/docs"
)
# Zensical's own rule, then the phone rule keryx carried, which outranks the shared
# selector and loads after it.
SITE_CSS = """
.md-typeset code { word-break: break-word; }
@media (max-width: 600px) {
  .md-typeset table:not([class]) td:first-child code { white-space: normal; }
}
.md-typeset table:not([class]) td code { white-space: nowrap; }
"""
PAGE = f"""<!doctype html><html><head>
<meta name=viewport content="width=device-width,initial-scale=1">
<style>{(SHARED / "stylesheets/shared.css").read_text()}</style>
<style>{SITE_CSS}</style></head><body><article class="md-typeset">
<table style="width:14rem"><tr>
<td><code>distinct_voices_setting</code></td>
<td><code>/plugin install dokimasia@techne</code></td>
<td>a description with enough words to take most of the width</td>
</tr></table></article>
<script>{(SHARED / "javascripts/shared.js").read_text()}</script></body></html>"""

WORDS_SPLIT = """() => [...document.querySelectorAll("table code")].flatMap((c) => {
  const out = [];
  const walker = document.createTreeWalker(c, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    for (const m of n.data.matchAll(/\\S+/g)) {
      const r = document.createRange();
      r.setStart(n, m.index);
      r.setEnd(n, m.index + m[0].length);
      if (new Set([...r.getClientRects()].map((x) => Math.round(x.top))).size > 1) out.push(m[0]);
    }
  }
  return out;
})"""


@needs_browser
@pytest.mark.parametrize("width", [390, 1280])
def test_table_code_stays_whole_against_a_site_override(width):
    from playwright.sync_api import sync_playwright  # ty: ignore[unresolved-import]

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": width, "height": 800})
            page.set_content(PAGE)
            assert page.evaluate(WORDS_SPLIT) == []
            command = page.locator("table code").nth(1)
            assert command.evaluate("e => e.classList.contains('words')")
            lines = command.evaluate(
                "e => new Set([...e.querySelectorAll('.nobr')]"
                ".map((s) => Math.round(s.getBoundingClientRect().top))).size"
            )
            assert lines > 1, "a command should still wrap between its words"
        finally:
            browser.close()


FOOTER = """<!doctype html><html><head><style>{css}</style>
<style>body {{ margin: 0; background: {bg}; }} .md-copyright {{ color: {fg}; font-size: 40px; }}
</style></head><body><div class="md-copyright"><div class="md-copyright__highlight">
2026 <span class="footer-brand" aria-hidden="true"></span> AJ Barea</div></div></body></html>"""


@needs_browser
@pytest.mark.parametrize(
    ("bg", "fg"), [("#1e2129", "rgb(255, 255, 255)"), ("#ffffff", "rgb(0, 0, 0)")]
)
def test_footer_brand_mark_takes_the_footer_text_color(bg, fg):
    """The mark is drawn in the footer's text color, so it reads on a dark and a light
    footer alike, at the height of the text."""
    from playwright.sync_api import sync_playwright  # ty: ignore[unresolved-import]

    css = (SHARED / "stylesheets/shared.css").read_text()
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page()
            page.set_content(FOOTER.format(css=css, bg=bg, fg=fg))
            mark = page.locator(".footer-brand")
            box = mark.bounding_box()
            assert box is not None
            assert box["height"] == pytest.approx(40, abs=1)
            assert box["width"] == pytest.approx(40 * 0.583, abs=1)
            assert mark.evaluate("e => getComputedStyle(e).backgroundColor") == fg
            # The glyph is masked, not a filled box: on a transparent page only part of
            # the mark's box paints (the brand image is about a third ink).
            assert mark.evaluate("e => getComputedStyle(e).maskImage").startswith(
                'url("data:image/png'
            )
            from io import BytesIO

            from PIL import Image  # ty: ignore[unresolved-import]

            page.evaluate("document.body.style.background = 'transparent'")
            alpha = Image.open(BytesIO(mark.screenshot(omit_background=True))).getchannel("A")
            counts = alpha.histogram()
            painted = sum(counts[129:]) / sum(counts)
            assert 0.05 < painted < 0.8, painted
            # Forced colors drop backgrounds; the mark keeps a system-color fill.
            page.emulate_media(forced_colors="active")
            fill = mark.evaluate("e => getComputedStyle(e).backgroundColor")
            assert fill not in ("rgba(0, 0, 0, 0)", "transparent")
        finally:
            browser.close()
