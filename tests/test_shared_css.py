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
.md-typeset table:not([class]) td:first-child code { white-space: normal; }
.md-typeset table:not([class]) td code.words { word-break: break-all; }
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
        page = browser.new_page(viewport={"width": width, "height": 800})
        page.set_content(PAGE)
        assert page.evaluate(WORDS_SPLIT) == []
        command = page.locator("table code").nth(1)
        assert command.evaluate("e => e.classList.contains('words')")
        assert command.evaluate("e => e.getClientRects().length") > 1, "words should still wrap"
        browser.close()
