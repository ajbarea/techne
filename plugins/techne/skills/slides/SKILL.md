---
name: slides
description: Build a talk deck and gate it before it is presented. Use when making or revising slides or a PowerPoint deck, turning a paper or a draft deck into a talk or a recorded video, writing the script to read aloud on each slide, adapting a deck for a new audience, or asking whether a deck is ready to present. Covers the toolchain choice, a starter deck, how to write slides a newcomer can follow, the gates that catch a deck that opens fine but fails its audience (untitled slides, low contrast, missing alt text, stray figures), rendering through the app that will show it, and briefing the presenter. Works alongside a general pptx skill, which owns the .pptx file API; this one owns what goes on the slides and whether the deck is ready.
disable-model-invocation: false
allowed-tools: Bash Glob Grep Read Edit Write
---

# Slides

A deck is done when its presenter can talk through it and answer questions on
it, not when the file opens. Start from the starter deck, write for the room,
write the script, gate the file, render it through the app that will show it,
look at every slide, then brief the presenter.

## Run it

```
uv run --quiet python ${CLAUDE_SKILL_DIR}/scripts/slides.py check  <deck.pptx>
uv run --quiet --with pillow python ${CLAUDE_SKILL_DIR}/scripts/slides.py render <deck.pptx> <out-dir>
uv run --quiet python ${CLAUDE_SKILL_DIR}/scripts/slides.py script <deck.pptx> > <deck>-script.md
```

`check` has no dependencies. `render` needs poppler, plus PowerPoint (native
Windows, or Windows reached from WSL) or LibreOffice; with Pillow it also writes
2x2 contact sheets, which is the fastest way to look at a whole deck. `script`
prints the speaker notes as one Markdown script, slide by slide, with the talk
length at 140 words a minute (`--wpm` to change it); backup slides are listed
after the talk and left out of the length.

**`render` needs a folder of its own.** It deletes old `slide-*.png` and
`sheet-*.png` and overwrites `<deck>.pdf` there, so it refuses any non-empty
folder it did not create (it marks its own with `.techne-slides`). Never point
it at the deck's folder: that is where the PDF someone is about to send lives.

| Code | Meaning |
|---|---|
| 0 | Every gate passed. `REVIEW` lines still need a decision. |
| 1 | The file, or a part it points at, could not be read. |
| 2 | `BLOCK` findings. Fix them in the generator, not the packed XML. |

## The gates

| Severity | Gate | Catches |
|---|---|---|
| BLOCK | `no-title` | A slide with no title placeholder. A bold text box looks like a title; screen readers and the outline see an untitled slide. |
| BLOCK | `contrast` | Text below 7:1 (4.5:1 for 18pt+, or 14pt+ bold). `--level AA` drops to 4.5:1 / 3:1. The colour behind the text is resolved: its own fill, else the topmost filled shape under its centre, else the first of slide, layout and master that defines a background. Text over a picture, gradient, theme-styled or translucent fill, or inside a group, is counted as unchecked rather than guessed. A title with no size of its own takes the master's title size. |
| BLOCK | `alt-text` | A picture with no description and no decorative flag. |
| BLOCK | `em-dash` | An em-dash in slide text. |
| WARN | `small-text` | An explicit size under `--min-pt` (14). The slide-number field is exempt. |
| WARN | `font` | A family outside the set that renders in both PowerPoint and Google Slides. Theme references (`+mn-lt`, `+mj-lt`) resolve through the master's theme. |
| WARN | `no-notes` / `duplicate-title` | A talk slide with no script in its speaker notes (backup slides are exempt), or two slides a screen reader cannot tell apart. |
| REVIEW | `figures` / `dense` | Percentages, ratios, decimals, `x of y` and long numbers, or body text over 60 words, on talk slides. Slide 1 is exempt, and so is everything after a divider titled exactly `Backup`, `Backup slides` or `Appendix`. |
| REVIEW | `long-title` | Titles over 14 words, on every slide. |

What `check` cannot see: text overflowing its box, shapes overlapping, a
diagram that reads wrong. That is what `render` is for. Look at every slide,
including the ones you did not change.

## Writing it for the room

`# research(2026-09)`

The test for every slide: someone who has never heard the terms follows it.

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
  untested), what comes next, and a closing slide that states the one message
  to remember as a contrast ("The bar is not *does it sound right?* It is *can
  you prove how you got it?*"). A general audience keeps three to five main
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
- **One idea per slide, and little text.** The 7x7 rule is the right instinct:
  a slide holds phrases, and the explanation goes in the script. When a `dense`
  review fires, cut and move the words to the script rather than shrinking the
  font.
- **Numbers when this audience needs them.** It is a call per room, not a rule.
  For a general audience, state the claim ("most got through; after the fixes,
  none did") and put the figures on backup slides; for a technical one, the
  figure may be the claim.
- **Discussion stops** go right after the slide whose idea they generalize: a
  dark slide, one short personal question anyone can answer without the paper
  ("What's one thing you would never let an AI do for you?"), and a muted line
  of example answers that gets the room started ("Send a message as you? Spend
  your money? Grade your work?").
- **A `Backup slides` divider** separates the talk from Q&A material.
- **Source-bound.** When only one artifact is cleared for release (a prepub
  paper, say), every claim on a slide comes from it. Flag what you left out.

## The script

The speaker notes hold the script: the words the presenter says out loud on
each slide, written to be read from like a teleprompter. A presenter who knows
the material may never open it; one recording a video reads it line by line.
PowerPoint's Presenter View shows it beside the slide, and its recording
teleprompter scrolls it while the camera runs
([Microsoft](https://support.microsoft.com/en-us/powerpoint/record-your-presentation)).

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
  `script` prints the total; match it to the time slot.
- **Figures and answers to likely questions stay out of the script.** They go
  on backup slides and into the briefing.

Hand the presenter the exported `script` file along with the deck; they
should not have to find the notes pane to see it.

## The starter deck

`templates/deck.js` is a pptxgenjs generator for the look this skill was
built from: warm off-white background, near-black text, blue labels, an
orange accent for costs and limits, content in cards with a bold label and
one plain line, a kicker above every title, and dark discussion slides. It has
one of each layout: title, agenda, claim with cards and footnotes, vocabulary,
concrete case, discussion, limits, closing statement, backup divider, backup
table. Every colour clears 7:1, and the starter passes `check` with nothing to
review.

```
cp ${CLAUDE_SKILL_DIR}/templates/deck.js <talk-dir>/build.js
cd <talk-dir> && npm i pptxgenjs && node build.js talk.pptx
```

Replace every bracketed placeholder, drop the layouts the talk does not need,
and copy a layout to add slides. Keep its helpers (`base`, `kicker`, `card`,
`footnote`, `discussion`, `backup`): they put titles in the title placeholder
and keep the kicker, colours and sizes consistent.

## The toolchain, and why

`# research(2026-09)`

- **Typst + Touying** for a deck you own and present as a PDF, with math,
  diagrams, or generated figures. The compiler ships in the `typst` wheel the
  fleet already pins for `techne:pdf`, so there are no new dependencies. Touying
  is actively maintained
  ([0.7.x on Typst Universe](https://typst.app/universe/package/touying/)). Its
  `simple` theme takes a different signature and fails with "missing argument:
  body"; `metropolis`, `university` and `dewdrop` work.
- **pptxgenjs** when the deck must be a `.pptx`: it will be presented from
  PowerPoint or Google Slides, co-edited, recorded, or delivered on a template.
  Generate it from a script (start from the starter deck) so a rebuild is one
  command. The Anthropic `pptx` skill covers
  the API; the traps it does not cover are below.
- **Fonts: Calibri for text, Consolas for code.** Both render in PowerPoint and
  in Google Slides, so the deck looks the same wherever it opens. A font that
  exists only on the build machine is substituted silently on the presenter's.
- **Render through the presenting app.** PowerPoint via COM is the ground truth
  when it is installed; `render` finds it from WSL. LibreOffice substitutes
  fonts it lacks, so its preview can show overflow the real deck does not have,
  or hide overflow it does.

## Traps

- **pptxgenjs table margins are inches** since v3.8.0. Older docs and search
  results say points. `margin: [0, 6, 0, 6]` is six-inch padding and collapses
  every column to one character wide.
- **Put titles in a title placeholder.** In pptxgenjs, define a master with
  `placeholder: { options: { type: "title", align: "left" } }` and add each
  title with `{ placeholder: "title" }`. The placeholder centres text unless
  told otherwise.
- **Parse the XML, do not grep it.** pptxgenjs writes `<p:ph` and `type="title"`
  on different lines, so a one-line grep reports a deck full of titles as
  untitled.
- **Text boxes on cards.** A text box drawn over a filled shape has no fill of
  its own. Contrast is only meaningful against the card, which is why the gate
  resolves the shape underneath.
- **PowerPoint is single-instance.** `Quit()` on an instance the user already
  had open closes their presentations. `render` quits only an instance it
  started.
- **PowerShell 5 reads a `.ps1` without a BOM as the ANSI code page**, so a
  non-ASCII user name in a temp path arrives mangled. Write generated scripts
  as UTF-8 with a BOM.
- **A deck open in PowerPoint is locked** (a `~$<name>.pptx` file sits beside
  it). Copying over it fails, but a PDF beside it copies fine, which leaves a
  mismatched pair. Publish the `.pptx` first and stop on failure; when it is
  locked, write the new version under a new name and say so.
- **Headless LibreOffice on the user's own profile** hands the job to an
  already-open LibreOffice window, which may drop it, and `soffice` still exits
  0. Give it a private `-env:UserInstallation` profile and check the PDF exists.

## Done means

1. `check` exits 0, and each `REVIEW` item is resolved or deliberately kept.
2. `render` ran through the presenting app, and every slide was looked at.
3. Every talk slide has its script, `script`'s length fits the slot, and the
   exported script went to the presenter with the deck.
4. The presenter has been briefed. A polished deck can outrun its owner. Offer a
   mock Q&A, with questions out of order and no notes, before the talk rather
   than after. Two basic questions about material already in the deck mean stop
   polishing and start drilling.

## Not this skill

- Markdown to a print PDF: `techne:pdf`.
- A LaTeX document: `techne:latex`.
