<!-- budget: 900 words -->
# Exports and other formats

## `pptx --editable`

`pptx --editable` is for a deck someone will edit in PowerPoint or Google Slides.
Chromium lays out each slide fully built, and the export places native shapes
where the browser put them:

- text becomes text boxes, one per block, keeping bold, italic, colour, size,
  letter-spacing, links and native list bullets and numbers; inline TeX
  (`data-tex`, KaTeX or MathJax source) becomes Unicode (`\alpha^{2}` reads α²);
- tables become native tables with their fills, borders and alignment, and no
  theme table style, so Google Slides does not repaint them;
- figures (`img`, `svg`, `canvas`, `video`) and display equations become
  pictures with alt text (an equation's alt text is its TeX), since slide math
  renders blank outside PowerPoint;
- everything else (cards, rules, decoration, icons inside text) is baked into
  the slide background, taken with the text made transparent, so it cannot be
  dragged by mistake; a background of one colour becomes a solid fill. Text the
  page cannot hand over stays there too, still visible: CSS counters
  (`content: counter(n)`) and gradient text (`background-clip: text`);
- the first `h1` to `h3` fills the title placeholder where it stands, and the
  notes carry over. Text sits above pictures and tables, so none is hidden
  under a figure.

Text boxes are about 6% wider than the browser's, and a line the browser did not
wrap is set not to wrap, because PowerPoint and Google Slides set most fonts a
little wider than Chromium; tables get the same slack. The summary lists the
fonts the deck uses and names any PowerPoint does not ship: install those where
the deck is presented, or text rewraps in a substitute font. Generic families
(`sans-serif`, `monospace`) become Arial and Courier New.

It reads a reveal.js deck or a custom one: one `<section class="slide">` per
slide, the slide on screen marked with the class `active` (the export sets it),
fragments revealed with `visible`, and notes in `<template class="speaker-notes">`
or `<aside class="notes">`. Whatever is not inside the slide, such as the deck's
own buttons, stays out. A slide larger than the browser window is captured
whole: the window grows until it fits. One that never fits (sized to the window,
or pushed off its edge) is exported as far as it shows, and the summary names it. A .pptx has one slide size, taken from slide 1; the summary names any
slide of another shape, whose content past the page's height is off the slide.
`check`, `render`, `script` and `pdf` still need reveal.js. Render the result (`render <deck>.pptx`) and compare it with the
browser before handing it over; `--images` writes the browser's pictures for that.

`# research(2026-10)` The choices follow what Microsoft's html2pptx hit in
production ([GOTCHAS](https://github.com/microsoft/ResearchStudio/blob/main/ResearchStudio-Reel/skills/paper2poster/html2pptx/GOTCHAS.md)):
colours read through a canvas so `oklab()` and `color-mix()` resolve (G5), blocks
told apart by tag rather than CSS display (G6), native bullets with a hanging
indent (G10), no wrap on a line the browser kept whole (G16), equations as
pictures because slide math is blank outside PowerPoint (G19), hairline borders
kept at one pixel (G20). Google Slides repaints a table that keeps a theme
style; "No Style, No Grid" leaves it as drawn.

## A deck that is already a .pptx or a PDF

For a deck that already exists as a `.pptx` or a PDF:

- **`.pptx`**: `check` reads the XML directly: title placeholders, contrast
  resolved through fills and backgrounds, alt text, fonts that render in both
  PowerPoint and Google Slides (`font`), and speaker notes. `render` exports
  through PowerPoint when it is installed (natively or from WSL), otherwise
  LibreOffice, which substitutes fonts and can show overflow the real deck does
  not have. PowerPoint is single-instance, so `render` quits only an instance it
  started. pptxgenjs table margins are in inches since v3.8.0.
- **PDF** (Typst, Beamer): `check` reads each page's text with poppler's
  `pdftotext`, a page's first line standing for its title, and runs the gates
  text can answer; contrast, alt text and notes live in the source and are
  reported as not checked. `render` rasterises it as built.


## A deck the team edits in Google Slides

`# research(2026-11)` When the deliverable is a Google Slides deck, build a `.pptx` (python-pptx, or
`pptx --editable` from a web deck) and upload it to Drive with conversion. What a 2026-11 build
taught:

- Google renders any Google Fonts family by name, so `check`'s `font` warning is expected there.
  Upload a one-slide pilot first and read its thumbnail to confirm the face before building.
- The Drive connector refuses uploads over about 7 MB: save photos and screenshots as JPEG at
  about 220 dpi of their size on the slide; keep charts as PNG.
- Draw charts at the exact size they fill, with a transparent background, so their type keeps its
  point size and no pale box shows against the slide's ground.
- python-pptx's default layouts are 4:3: set every title placeholder's position on a 16:9 deck.
- The Slides API refuses `createVideo` from Drive: put a poster frame linked to the video and
  insert the video by hand.
- Read every slide back with `read_slide_page_thumbnail`; that is Google's own render. Stitch the
  2000 px thumbnails into the PDF backup, which then matches the presented deck.
