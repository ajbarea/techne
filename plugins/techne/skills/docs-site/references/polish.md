# Docs-site polish checklist

The bar every sister site is held to, learned by reviewing all of them side by side. A site
passes when `scripts/visual_qa.py` reports no findings and a person looking at each page's
contact sheet (light and dark; wide, desktop and phone) finds nothing off.

## Every page

- Both schemes are real themes: light has no dark slabs, dark has no bright ones. Surfaces,
  text, links, code and diagrams are redefined per scheme, not inherited from one.
- Text meets WCAG AA contrast in both schemes, including the parts nobody designs: footer
  prev/next labels, captions, eyebrows, code highlighting tokens, epithets, badges.
- Links take the site's palette, never the theme default, and stay AA on their surface.
- Nothing scrolls sideways at 390 wide. Wide tables scroll inside themselves.
- No raw markup: attr-list braces, `:icon:` codes, `!!!`, `$...$` read as math.
- Floating controls stay Zensical's own: the phone TOC button (`.md-sidebar--secondary`, 38px,
  bottom right) and back-to-top. They pass over text only while it scrolls by; a custom
  floating element that sits on text at rest, or lacks a solid background, fails.

## Landing page

- Lead with what makes the project special, in the words of a one-line pitch. Copy reads like
  a slide: short headings, one idea per block, no paragraph over three lines on desktop.
- Hero art and copy never overlap at any width, and on a 1920 screen the art sits beside
  the copy rather than at the screen's edge. Place the art in the layout (a grid column),
  not as a background positioned against the viewport.
- Hero art is the project's signature: on a phone it sits above the text, whole and visible,
  never faded to nothing, cropped by the edge, or running under the words.
- The hero title has no `¶`: hide `.hero .headerlink`.
- Tags under the hero are chips that wrap whole, never a pipe-separated line that breaks
  mid-phrase.
- Buttons: one primary, one secondary, both full-size pills; on a phone they stack with a
  gap, and no label wraps to two lines (shorten the label instead).
- Paragraphs longer than two lines are left-aligned on a phone; centring is for one-liners.
- The scroll hint never overlaps a chip, button or line of text.
- No theme footer (prev/next, grey bar) on the landing; one quiet footer line.
- Section rhythm is even: no voids, no section taller than its content needs.

## Verify

Serve the build under its repo path, the way GitHub Pages does, so absolute links resolve:

```bash
mkdir -p /tmp/serve && ln -sfn "$PWD/site" /tmp/serve/<repo>
python3 -m http.server -d /tmp/serve 8000 &
uv run --quiet --no-project --with playwright --with pillow \
    python ${CLAUDE_SKILL_DIR}/scripts/visual_qa.py http://127.0.0.1:8000/<repo>/ --out qa/
```

Then open `qa/home-sheet.png` and at least two inner pages' sheets and look at them. The
script catches contrast, overflow and wrong-scheme surfaces; only looking catches a cramped
hero, a clumsy wrap, or a page that does not say what the project is.
