<!-- budget: 900 words -->
# Traps and the toolchain

## Traps

- **Build before `Reveal.initialize`.** reveal.js counts fragments when it
  starts. A fragment added later is never shown; `deck.js` builds everything
  first.
- **Scroll view hides fragments by scroll position.** On a phone a fragment
  appears as the page scrolls past it and hides again on the way back, so a
  screenshot taken after `Reveal.slide()` can show the slide half-built.
  `render` shows every fragment on the phone pass.
- **reveal.js paints the page white.** `.reveal-viewport` sets
  `background-color: #fff` on the body, so a background set only on `html` or
  `body` loses. `deck.css` sets it on `.reveal-viewport` too.
- **Slide backgrounds live on a separate layer.** `data-background-color`
  paints a layer beside the slides, which axe reads as an element overlapping
  the text. `check` gives each slide its own background colour while axe runs.
- **axe's 7:1 rule skips text that fails 4.5:1.** `color-contrast-enhanced`
  reports only text between the two thresholds; `check` runs both rules.
- **`file://` cannot fetch JSON.** A deck opened from disk cannot read a
  `.json` file, so data lives in a `.js` file that sets `window.DECK_DATA`.
- **The print PDF lays out after `ready`.** Wait for `.pdf-page` elements
  before printing, and set `pdfSeparateFragments: false` or each fragment
  becomes its own page.
- **The motion gate sees CSS animations and transitions.** A loop driven by
  `requestAnimationFrame` or a timer is invisible to it; check such a loop
  reads `matchMedia('(prefers-reduced-motion: reduce)')` by hand.
- **Notes come from reveal.js itself.** `check` and `script` read each slide's
  notes through reveal.js's speaker-view call, so `data-notes`, an `<aside
  class="notes">` and a markdown slide's `Note:` read exactly as the speaker view
  shows them.
- **A `<section>` inside slide content becomes slides.** reveal.js turns the slide
  holding it into a vertical stack and shows each nested section as its own
  slide. `check` warns (`nested-section`); use a `<div>` for columns.
- **`window.Reveal` must exist.** `check` and `render` drive the deck through the
  global `Reveal`. A deck that imports reveal.js as a module sets
  `window.Reveal = deck` after creating it.
- **SVG text is not contrast-checked.** axe skips text inside a figure marked
  `role="img"`. Colour figure text with the `deck.css` tokens, which clear 7:1.
- **A 16:9 canvas shrunk to a phone is unreadable.** At 390px wide it is
  scaled to about a third, and 30px text becomes 9px. The starter switches
  phones to a portrait canvas and stacks the columns.


## The toolchain, and why

`# research(2026-10)`

- **reveal.js 6.0.2** for new talks. It is MIT-licensed and maintained, has a
  speaker view, PDF export, and a scroll view for phones, and needs no build
  step: the deck is the HTML file. Slidev, the main alternative, builds through
  Vite and Vue. Hosted builders such as Claude Design export standalone HTML
  that `check` cannot read; borrow the look, and build the deck from the
  starter.
- **Playwright and axe-core** check and render in the same Chromium that will
  show the deck. axe-core 4.12.1 comes bundled in `axe-playwright-python`.
- **Typst + Touying** for a deck that must be a PDF, with math or generated
  figures. The compiler ships in the `typst` wheel `graphe:pdf` pins. Its
  `simple` theme takes a different signature and fails with "missing argument:
  body"; `metropolis`, `university` and `dewdrop` work.
- **pptxgenjs** only when the deck must be a `.pptx`: co-edited in PowerPoint,
  or delivered on a template. The Anthropic `pptx` skill covers the API.

