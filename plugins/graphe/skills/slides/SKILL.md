---
name: slides
description: Build a talk deck and gate it before it is presented. Use when making or revising slides or a talk, an animated web deck to present from a browser or publish on GitHub Pages, a PowerPoint deck, or a Typst or Beamer PDF deck; turning a paper or a draft deck into a talk or a recorded video; drawing how the work differs from related work; writing the script to read aloud on each slide; adapting a deck for a new audience; or asking whether a deck is ready to present. Covers the starter web deck, how to write and animate slides a newcomer can follow, the gates that catch a deck that opens fine but fails its audience (untitled slides, low contrast, missing alt text, missing files, text off the slide or unreadable on a phone, motion that ignores reduced-motion settings), rendering, publishing, and briefing the presenter. Works alongside a general pptx skill, which owns the .pptx file API; this one owns what goes on the slides and whether the deck is ready.
disable-model-invocation: false
allowed-tools: Bash Glob Grep Read Edit Write
---

# Slides

A deck is done when someone who has never seen it can present it from the
slides alone, and its owner can answer questions on it, not when the file
opens. New talks are web decks: plain HTML on reveal.js, presented from a
browser, with diagrams that build step by step, and a link that serves as the
handout. Start from the starter deck, write for the room, put a figure on every
content slide, gate it, render it, look at every slide, publish it, then brief
the presenter.

## Run it

```
B="uv run --no-project --quiet --with playwright==1.63.0 --with axe-playwright-python==0.1.8 --with pillow"
$B python ${CLAUDE_SKILL_DIR}/scripts/slides.py check  <deck/index.html> [--jargon "term,term"] [--backup-from N]
$B python ${CLAUDE_SKILL_DIR}/scripts/slides.py render <deck/index.html> <out-dir>
uv run --no-project --quiet python ${CLAUDE_SKILL_DIR}/scripts/slides.py script <deck/index.html> > <deck>-script.md
```

A web deck is checked and rendered in Chromium through Playwright. Install the
browser once with `uv run --no-project --with playwright==1.63.0 playwright
install chromium`. `script` reads the HTML and needs no browser.

`check` and `script` also take a `.pptx`, and `check` and `render` take a PDF
(a Typst or Beamer deck), for decks that already exist in those formats; see
[Other formats](#other-formats).

`render` writes one PNG per slide at 1920x1080 with every fragment shown, one
per slide on a 390px-wide phone, 2x2 contact sheets of both (`sheet-*`,
`phone-sheet-*`), and the print PDF reveal.js makes, one page per slide. Read
the sheets: it is the fastest way to look at a whole deck.

**`render` needs a folder of its own.** It deletes old `slide-*`, `phone-*` and
`sheet-*` images and overwrites `<deck>.pdf` there, so it refuses any non-empty
folder it did not create (it marks its own with `.techne-slides`). Never point
it at the deck's folder.

| Code | Meaning |
|---|---|
| 0 | Every gate passed. `REVIEW` lines still need a decision. |
| 1 | The file could not be read, or a web page never started reveal.js. |
| 2 | `BLOCK` findings. |

## The gates

On a web deck, each slide is read with every fragment shown, on its 1280x720
canvas.

| Severity | Gate | Catches |
|---|---|---|
| BLOCK | `no-title` | A slide with no `h1`, `h2` or `h3` (on a .pptx, no title placeholder). The outline and screen readers see an untitled slide. |
| BLOCK | `contrast` | Text below 7:1 (4.5:1 for large text). `--level AA` drops to 4.5:1 / 3:1. Web decks are measured by axe-core against each slide's own background; text inside an SVG figure, or over an image or gradient, is counted as unchecked. |
| BLOCK | `alt-text` | An image, or an SVG with `role="img"`, with no text alternative. |
| BLOCK | `em-dash` | An em-dash in slide text. |
| BLOCK | `asset` | A file the deck asks for and cannot load: a renamed figure, a missing script. |
| BLOCK | `script` | A console error, including a `data-value` with no data behind it. |
| WARN | `small-text` | Text under `--min-pt` (14pt, 19px on the canvas). |
| WARN | `overflow` | Something drawn past the slide's edge. |
| WARN | `phone` | On a 390px-wide phone: text under 12px, content past the slide's edge, or a page that scrolls sideways. |
| WARN | `motion` | Animation still running with reduced motion requested. |
| WARN | `offline` | The deck fetches from the network, so it fails on a projector laptop with no Wi-Fi. |
| WARN | `no-notes` / `duplicate-title` | A talk slide with no script (backup slides are exempt), or two slides a screen reader cannot tell apart. |
| REVIEW | `figures` / `dense` | Percentages, ratios, decimals, `x of y` and long numbers (years and digits inside identifiers are labels), or more than 60 words, on talk slides. Slide 1 is exempt, and so is everything after a divider titled exactly `Backup`, `Backup slides` or `Appendix`, or from `--backup-from`. Words inside figures count: a `dense` on a figure-heavy slide is not a reason to cut the figure. |
| REVIEW | `jargon` | A `--jargon` term on a talk slide. Use the plain word on the slide and the term in a muted footnote. |
| REVIEW | `long-title` | Titles over 14 words, on every slide. |

What `check` cannot see: a diagram that reads wrong, a label on the wrong
mark, a build order that gives away the punchline. That is what `render` is
for. Look at every slide, desktop and phone, including the ones you did not
change.

## Writing it for the room

`# research(2026-10)`

The test for every slide: someone who has never heard the terms follows it.
The slide text and the script follow `${CLAUDE_PLUGIN_ROOT}/_shared/plain-prose.md`; the
guidance below is what a deck adds to it. To check a script, run
`uv run --no-project --quiet python ${CLAUDE_PLUGIN_ROOT}/_shared/prose_check.py <deck>-script.md`.

- **The headline is the slide's claim**, a short full sentence ("Every query
  passes a code-only checkpoint first"), not a topic ("Architecture").
  Engineering students taught from claim headlines over visual evidence showed
  better comprehension and fewer misconceptions than with topic headlines over
  bullets ([2025 study](https://www.sciencedirect.com/science/article/pii/S2307187725001701)).
- **An agenda slide right after the title.** The talk's parts, in order, in
  plain words, plus where the discussion stops fall. It orients the room, and
  it is the presenter's map when a question pulls the talk off course. Keep
  the section names identical to the kicker labels on the slides they
  introduce ("3 · How it works · Before the data").
- **A story arc.** The problem, the catch that makes it hard, the idea, how it
  works, what was found (including where it failed and what is still
  untested), what comes next, and a plain closing slide: "Thank you", the
  presenter's name and contact. No tagline or contrast-statement slide; the
  presenter introduces themselves and states the take-home aloud, in the script.
  A general audience keeps three to five main
  points ([Science Communication Toolkit](https://ecampusontario.pressbooks.pub/scicommtoolkit/chapter/talks/)).
  An honest limits slide makes the claims before it believable.
- **Plain words on the slide, the source's term underneath.** Name each idea
  in words a newcomer already knows ("Read-only, twice"), and put the paper's
  name for it in a muted footnote ("Paper term: law documents"). The room
  follows the plain version; anyone who reads the paper later can map it back.
  Spell out every acronym.
- **Define a term on the slide where it first appears**, in one muted line
  ("Air-gapped: cut off from the internet."). A vocabulary slide early in the
  talk collects the few terms that keep coming back, one everyday sentence
  each.
- **A concrete case before the general rule.** Show one worked instance (one
  player, three datasets, three IDs), then name the pattern it stands for ("the
  analyst's ID problem"). Newcomers learn from the concrete case first; the
  named rule is what transfers
  ([concreteness fading](https://www.learningscientists.org/blog/2018/2/1-1)).
- **Text alone or figure alone, the point lands.** Read each talk slide twice:
  once with the figure covered, once with the text covered. Both readings must
  give its main point. The sentence headline carries it in words; the figure
  carries it in marks, labelled inside the figure. This is the assertion-evidence
  design: a claim headline over visual evidence, which audiences understand and
  recall better than topic titles over bullets ([Garner and Alley](https://www.researchgate.net/publication/286042632_How_the_Design_of_Presentation_Slides_Affects_Audience_Comprehension_A_Case_for_the_Assertion-Evidence_Approach)).
- **A figure on every content slide, and the diagram is the last thing cut.**
  Agenda, discussion, closing and divider slides are exempt. A
  slide of text cards is a draft: turn it into a picture of the idea. Shapes
  that recur: a concrete before-and-after (what the tool gets wrong, what the
  expert wants), a flow of numbered stages, a two-group comparison, a timeline,
  or three small labelled panels. When a talk runs long, cut words from the
  script and footnotes, never a diagram that carries a slide.
- **Self-explaining figures.** Labels sit inside the figure ("average", "one
  split"), the caption says what each mark means ("filled: found"), and an
  invented example or a bar with no data behind its height says so
  ("Illustrative example", "Bars are not to scale").
- **One idea per slide, and little text.** The 7x7 rule is the right instinct:
  a slide holds phrases, and the explanation goes in the figure or the script.
  When a `dense` review fires on prose, cut and move the words rather than
  shrinking the font.
- **Numbers when this audience needs them.** It is a call per room, not a rule.
  For a general audience, state the claim ("most got through; after the fixes,
  none did") and put the figures on backup slides; for a technical one, the
  figure may be the claim. A count drawn as marks (nineteen of twenty dots
  filled) is a figure too: it traces to the same source a typed number would.
- **Discussion stops** go right after the slide whose idea they generalize: a
  dark slide, one short personal question anyone can answer without the paper
  ("What's one thing you would never let an AI do for you?"), and a muted line
  of example answers that gets the room started ("Send a message as you? Spend
  your money? Grade your work?").
- **Talk lean, backup unlimited.** A `Backup slides` divider (or an FAQ
  section, with `--backup-from`) separates the talk from Q&A material. Behind
  it, a slide can be as long and detailed as an answer needs: it is read when
  someone asks, not presented cold.
- **Source-bound.** When only one artifact is cleared for release (a prepub
  paper, say), every claim on a slide comes from it. Flag what you left out.

## The script

The speaker notes hold the script: the words the presenter says out loud on
each slide, written to be read from like a teleprompter. It supports the
slides and never replaces them: a presenter giving the talk at a moment's
notice may not read it, so every point the talk needs is on the slide. A
presenter who knows the material may never open it; one recording a video
reads it line by line.
In a web deck the script is each slide's `<aside class="notes">`. Press `S` and
reveal.js opens the speaker view: the script, a timer, and the next slide, beside
the one the room sees ([reveal.js](https://revealjs.com/speaker-view/)).

- **First person, spoken sentences, start to finish.** "Here's the problem.
  An analyst's evidence lives in four different systems..." Not reminders, not
  briefing notes ("The paper calls this...").
- **The same plain words as the slides.** Say what each term means the first
  time it is used, and say the paper's name for it only when someone will need
  it later.
- **Exact wording where it matters.** Where a word would overclaim, the script
  already uses the safe one ("tamper-evident", never "tamper-proof").
- **End each slide with the line that leads into the next.**
- **Discussion slides:** the script reads the question, offers one example
  answer, and ends with the sentence that closes the discussion and ties it
  back to the talk.
- **Length.** Presenters speak at about 130 to 150 words a minute
  ([VirtualSpeech](https://virtualspeech.com/blog/average-speaking-rate-words-per-minute)).
  `script` prints the total, a guide to the time slot rather than a gate: when
  the talk runs long, cut slides' words and the script's asides, not figures.
- **Figures and answers to likely questions stay out of the script.** They go
  on backup slides and into the briefing.

Hand the presenter the exported `script` file along with the deck; they
should not have to find the notes pane to see it.

## The starter deck

`templates/web/` is a whole deck that passes `check` with nothing to review.
Copy it and replace every bracketed placeholder:

```
cp -r ${CLAUDE_SKILL_DIR}/templates/web <talk-dir>
```

| File | Holds |
|---|---|
| `index.html` | One `<section>` per slide: title, agenda, claim with a figure that builds, concrete case, quick bet, method steps, related-work map, timeline, discussion, limits, Thank you, backup divider, backup table. Drop the layouts the talk does not need; copy one to add a slide. |
| `deck.css` | Colour tokens (every text colour clears 7:1 on its surface; figure marks use the colour-blind-safe Okabe-Ito hues), layouts, the phone layout, and the reduced-motion rule. |
| `deck.js` | Builds what comes from data, then starts reveal.js. |
| `data/deck-data.js` | Every figure and every related-work entry the deck shows. |
| `vendor/reveal/` | reveal.js 6.0.2 (MIT), so the deck opens with no network. |

Open `index.html` in a browser to present. `S` opens the speaker view, `O` the
slide overview, `F` full screen, `B` blanks the screen; links like
`#/5` jump to a slide.

**Nothing on a slide is typed by hand when it comes from data.** Slides read
`data/deck-data.js`: `data-value="results.failShare"` fills in a number
(`data-format="pct"` for a share), `data-dots` draws a share as filled dots, and
`data-source="related"` builds the related-work map or timeline. In a repo with
results, generate that file from the artifacts in the build, the way a paper's
tables are harvested; a key with no data behind it is a console error, which
`check` blocks. It is a `.js` file rather than JSON so the deck opens from
`file://` with no server.

**The chapter rail and the agenda come from `data-chapter`.** Give each talk
slide its chapter (`data-chapter="2 · How it works"`, the same words as its
kicker). The agenda slide lists the chapters in order, and a rail across the top
shows which one the talk is in; click a chapter to jump to it.

**Show how the work differs from related work, from data.** Each entry in
`related.works` has a year, a group, a position on the two axes (`x`, `y`), a
one-line summary, and for a rival, the one sentence on how ours differs. The map
places rivals by the two axes, brings ours in last, and lists the differences
beside it; the timeline draws the same entries by year, one lane per group.
Choose axes on which ours sits alone: what each method reads and when it looks,
say. Hovering or tabbing to a dot shows its summary.

**On a phone** (600px wide or less) the deck switches to a portrait canvas in
reveal.js scroll view: columns stack, and a wide figure keeps a readable size
and pans sideways. Look at the phone sheets; `check` warns on text under 12px.

## Motion

`# research(2026-10)`

Motion is for building an idea in steps and pointing at the one mark that
matters. It is never decoration.

- **Build a process in steps.** A figure that adds one stage per click (a
  `class="fragment"` on each SVG group or card) lets the room follow a complex
  idea at the presenter's pace. Learner-paced segments improved transfer in
  three of three tests ([Mayer, segmenting
  principle](https://www.cambridge.org/core/books/multimedia-learning/segmenting-principle/37240877DDA0362355ADB39936027982)).
- **Point at the mark.** Bring in the one dot, bar or arrow the claim is about
  last, in the accent colour. Cues that point at the essential material help
  learning ([signaling](https://u.osu.edu/multimedialearning/?p=88)); the cue does the work, not the movement.
- **Do not reveal bullets one at a time.** A direct test found no learning
  difference between full, progressive, dimmed and highlighted text
  ([Virginia Tech](https://vtechworks.lib.vt.edu/handle/10919/88726)). Show the
  list.
- **Ask, then reveal.** A quick bet (hands up for each option, then the dots
  fill in) makes the room commit before the answer.
- **Honour reduced motion.** `deck.css` stops every animation and transition
  when the viewer asks for reduced motion, and `deck.js` turns off slide
  transitions. Keep that rule when adding animations; `check` warns when it is
  missing.

## Publish

A web deck is published with GitHub Pages, and the link is the handout.
Publish only what is cleared for release; a public repo's Pages site is public.

1. Commit the deck folder to the repo.
2. Copy `${CLAUDE_SKILL_DIR}/templates/pages.yml` to `.github/workflows/deck.yml`
   and replace `DECK_DIR` with the deck folder's path.
3. Set the Pages source to GitHub Actions:
   `gh api -X POST repos/<owner>/<repo>/pages -f build_type=workflow`
   (or `-X PUT` if Pages already exists). A private repo needs a paid plan for
   Pages.
4. Push. The deploy job prints the URL; put it on the closing slide.

The template's actions are pinned to commit SHAs, and techne's guard keeps them
equal to the pins its own docs workflow uses.

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
- **SVG text is not contrast-checked.** axe skips text inside a figure marked
  `role="img"`. Colour figure text with the `deck.css` tokens, which clear 7:1.
- **A 16:9 canvas shrunk to a phone is unreadable.** At 390px wide it is
  scaled to about a third, and 30px text becomes 9px. The starter switches
  phones to a portrait canvas and stacks the columns.

## Other formats

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

## Done means

1. `check` exits 0, and each `REVIEW` item is resolved or deliberately kept.
2. `render` ran, and every slide was looked at, on desktop and on the phone.
3. Every content slide passes the text-alone and figure-alone reading, and has a
   figure. The script is handed over with the deck; its length is near the
   slot, and the slides stand without it.
4. The deck is published (or deliberately kept local) and the link is on the
   closing slide.
5. The presenter has been briefed. A polished deck can outrun its owner. Offer a
   mock Q&A, with questions out of order and no notes, before the talk rather
   than after. Two basic questions about material already in the deck mean stop
   polishing and start drilling.

## Not this skill

- Markdown to a print PDF: `graphe:pdf`.
- A LaTeX document: `graphe:latex`.
