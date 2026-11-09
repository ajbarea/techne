---
name: slides
description: Build a talk deck and gate it before it is presented. Use when making or revising slides or a talk, an animated web deck to present from a browser or publish on GitHub Pages, a PowerPoint deck, or a Typst or Beamer PDF deck; turning a paper or a draft deck into a talk or a recorded video; drawing how the work differs from related work; writing the script to read aloud on each slide; adapting a deck for a new audience; or asking whether a deck is ready to present. Covers the starter web deck, how to write and animate slides a newcomer can follow, the gates that catch a deck that opens fine but fails its audience (untitled slides, low contrast, missing alt text, missing files, text off the slide or unreadable on a phone, motion that ignores reduced-motion settings), rendering, publishing, and briefing the presenter. Works alongside a general pptx skill, which owns the .pptx file API; this one owns what goes on the slides and whether the deck is ready.
disable-model-invocation: false
allowed-tools: Bash Glob Grep Read Edit Write
---

# Slides

`<skill-dir>` is the directory holding this SKILL.md, and `<plugin-root>` is the plugin's root directory, two levels above it.

A deck is done when someone who has never seen it can present it from the
slides alone, and its owner can answer questions on it, not when the file
opens. New talks are web decks: plain HTML on reveal.js, presented from a
browser, with diagrams that build step by step, and a link that serves as the
handout. Start from the starter deck, write for the room, put a figure on every
content slide, gate it, render it, look at every slide, publish it, then brief
the presenter.

## Run it

```
B="uv run --no-project --quiet --with playwright==1.63.0 --with axe-playwright-python==0.1.8 --with pillow --with python-pptx==1.0.2"
$B python <skill-dir>/scripts/slides.py check  <deck/index.html> [--jargon "term,term"] [--backup-from N] [--allow-dark]
$B python <skill-dir>/scripts/slides.py render <deck/index.html> <out-dir>
$B python <skill-dir>/scripts/slides.py script <deck/index.html> > <deck>-script.md
$B python <skill-dir>/scripts/slides.py pptx   <deck/index.html> <deck>.pptx [--images <dir>] [--editable]
$B python <skill-dir>/scripts/slides.py pdf    <deck/index.html> <deck>.pdf
uv run --no-project --quiet --with colorspacious==1.1.2 --with numpy python <skill-dir>/scripts/slides.py palette "#6a1b6e,#e66100,#33bbee"
```

A web deck is checked and rendered in Chromium through Playwright. Install the
browser once with `uv run --no-project --with playwright==1.63.0 playwright
install chromium`. `script` reads a web deck in the same browser, so its notes are
what the speaker view shows.

`check`, `render` and `script` also take a `.pptx`, and `check` and `render`
take a PDF (a Typst or Beamer deck), for decks that already exist in those
formats; see [references/exports.md](references/exports.md).

`pptx` exports a web deck for PowerPoint: each slide becomes one picture of it at
1920x1080, fully built, with its script in the speaker notes and its title kept
in the title placeholder just above the slide, where the outline, the slide list
and screen readers find it. Each picture's alt text is the slide's visible text
(title first, cut at 1000 characters); mark browser-only text, such as "hover
for a summary", with `class="web-only"` and the export hides it. It is for presenting from PowerPoint and handing out
a file; the pictures cannot be edited, links in them do not work, and nothing
animates. Build it, never commit it: it is regenerated from the web deck.
`--images` also writes the slide PNGs to a folder render's rules govern.

`pptx --editable` is for a deck someone will edit in PowerPoint or Google Slides: native text and
tables where the browser laid them out, figures and equations as pictures. How it works and what it
leaves out: [references/exports.md](references/exports.md).

`pdf` exports the same web deck as a PDF: reveal.js's `?print-pdf` layout printed by
Chromium, one page per slide with every fragment shown (it sets
`pdfSeparateFragments: false` itself, so the deck's setting cannot add pages),
vector text you can select and search, and live links (`#/slide-id` links are
rewritten to anchors, which the browser turns into links). A footnote pinned to
the slide's bottom stays on the page, and `class="web-only"` text and reveal.js's
own navigation are left out, as in `pptx`. Speaker notes never appear in it, even
in a deck that sets reveal.js's `showNotes`, so it is safe to submit (`pptx`'s
and `render`'s pictures leave them out too). It is the file
to hand out or print; use `pptx` when the audience will present from PowerPoint. Build it, never commit
it. `render`'s `<deck>.pdf` is the same file.

`render` writes one PNG per slide at 1920x1080 with every fragment shown, one
per slide on a 390px-wide phone, contact sheets of both (`sheet-*` two across,
`phone-sheet-*` four across), and the print PDF reveal.js makes, one page per
slide. Read the sheets: it is the fastest way to look at a whole deck.

**`render` needs a folder of its own.** It deletes old `slide-*`, `phone-*` and
`sheet-*` images and overwrites `<deck>.pdf` there, so it refuses any non-empty
folder it did not create (it marks its own with `.techne-slides`). Never point
it at the deck's folder.

| Code | Meaning |
|---|---|
| 0 | Every gate passed. `REVIEW` lines still need a decision. |
| 1 | The file could not be read, has no slides, or a web page never started reveal.js (the console errors that stopped it are printed). |
| 2 | `BLOCK` findings. |

## The gates

On a web deck, each slide is read with every fragment shown, on its own canvas
(1280x720 in the starter). A failure to start in the reduced-motion or phone
pass is reported on its own, beside the desktop findings.

| Severity | Gate | Catches |
|---|---|---|
| BLOCK | `no-title` | A slide with no `h1`, `h2` or `h3` (on a .pptx, no title placeholder). The outline and screen readers see an untitled slide. |
| BLOCK | `contrast` | Text below 7:1 (4.5:1 for large text). `--level AA` drops to 4.5:1 / 3:1. Web decks are measured by axe-core against each slide's own background colour; text inside an SVG figure, or on a slide whose background is an image or gradient, is counted as unchecked. |
| BLOCK | `alt-text` | An image, or an SVG with `role="img"`, with no text alternative. |
| BLOCK | `em-dash` | An em-dash in slide text. |
| BLOCK | `asset` | A file the deck asks for and cannot load: a renamed figure, a missing script. |
| BLOCK | `script` | A console error, including a `data-value` with no data behind it. |
| BLOCK | `dark-slides` | A web deck whose talk slides are mostly dark, naming them (solid backgrounds only; title, closing, backup and picture-backed slides do not count). `--allow-dark` is for a deck the presenter asked to be dark. Not checked on a .pptx or PDF. |
| WARN | `small-text` | Text under `--min-pt` (14pt: 19px on a 1280-wide canvas, scaled to the deck's own width). |
| WARN | `overflow` | Something drawn past the edge of the slide canvas, clipped or not. Content inside a container that scrolls sideways is exempt. |
| BLOCK | `phone-clip` | Content drawn past the slide's edge on a 390px or 360px-wide phone. A phone cannot pan to it: reflow the figure or draw a tall version for the phone. |
| BLOCK | `contribution` | A web deck with no slide marked `data-contribution`, more than one, the marked slide after slide 5 (title, agenda, then the first content slides), or no script on it. It checks where the slide is, never what it says; see [What we did and why you should care](#what-we-did-and-why-you-should-care). Not checked on a .pptx or PDF. |
| BLOCK | `conclusion` | A web deck with no slide marked `data-conclusion`, more than one, or the marked slide anywhere but right before the closing slide (the last slide before the backup divider). It checks where the slide is, never what it says; see [The conclusion](#the-conclusion). Not checked on a .pptx or PDF. |
| WARN | `conclusion` | The conclusion slide titled with a topic word, such as `Conclusion`, `Summary` or `Takeaways`, instead of the main point. |
| WARN | `phone` | On a 390px-wide phone: text under 12px, a page that scrolls sideways, or no viewport meta tag. Figures that pan sideways are listed as INFO. |
| WARN | `nested-section` | A `<section>` inside a slide's content, which reveal.js shows as separate slides. |
| WARN | `motion` | Animation on a slide still running a quarter second after it opens, with reduced motion requested. |
| WARN | `unbound-data` | A path in `window.DECK_DATA` that no `data-*` attribute binds, in the page as built or in its source; a binding in the speaker notes counts, one on a `data-visibility="hidden"` slide does not, and reveal.js's own attributes never do. The data file is published with the deck, so a figure no slide shows (a withheld reading, a cut slide's numbers) still ships: cut it from the file, or generate only the paths `index.html` binds. |
| WARN | `offline` | The deck fetches from the network, so it fails on a projector laptop with no Wi-Fi. |
| WARN | `no-notes` / `duplicate-title` | A talk slide with no script, in `<aside class="notes">` or `data-notes` (backup slides are exempt), or two slides a screen reader cannot tell apart. |
| REVIEW | `own-look` | A web deck that kept the starter's colours, whose title slide still shows the placeholder illustration, or whose title slide has no picture at a quarter of the slide's height or more. It sees only those three things; whether the look suits the talk is yours to judge. See [The look](#the-look). |
| REVIEW | `figures` / `dense` | Percentages, ratios, decimals, `x of y` and long numbers (years and digits inside identifiers are labels), or more than 60 words, on talk slides. Slide 1 is exempt, and so is everything after a divider titled exactly `Backup`, `Backup slides` or `Appendix`, or from `--backup-from`. Words inside figures count: a `dense` on a figure-heavy slide is not a reason to cut the figure. |
| REVIEW | `jargon` | A `--jargon` term on a talk slide. Use the plain word on the slide; the term goes in a muted footnote only when the room will meet it again (in Q&A, or in the paper they will read). |
| REVIEW | `footnotes` | An element with `class="footnote"` on more than half the slides after the title and up to the closing slide. Each footnote must pass the test in [Writing it for the room](#writing-it-for-the-room); a footnote on most slides is usually padding. |
| REVIEW | `long-title` | Titles over 14 words, on every slide. |

What `check` cannot see: a diagram that reads wrong, a label on the wrong
mark, a build order that gives away the punchline. That is what `render` is
for. Look at every slide, desktop and phone, including the ones you did not
change.

## The look

`# research(2026-11)`

The starter is a working skeleton, not a look: it passes the gates and is meant to be replaced. `check` raises an `own-look` review until a deck has its own colours and a real title illustration.

- **Give each talk its own identity.** No shared theme across talks: each talk gets its own ground, type, colour and title illustration, taken from its subject. Styling from a culture or a cast (Greek type, a mascot, a character's colours) belongs only on a talk about it.
- **Light on the slides the room reads.** Dark slides wash out when the lights stay on, so talk slides sit on a light ground; a dark title or closing slide can be part of a talk's identity. `check` blocks a deck whose talk slides are mostly dark, and `--allow-dark` is for a deck the presenter asked to be dark.
- **Read an analogy as a level of care.** "Like X" means "with the care X got", so state the reading in one line before starting, and borrow X's content only when the talk is about X.
- **Match the subject before raising saturation.** A colour request names a mood. Match the subject's real look first; a full-bleed title bar in the accent colour is rarely what was asked for.
- **Show a change of look before shipping it.** Before and after at 1920 wide and on a phone, every time the ask is about how it looks. When asked for a look, mock two or three directions on the same three slides (title, a claim with its figure, a table) and let the owner pick; load `frontend-design` when it is installed.
- **Chrome is part of the identity.** Style the chapter rail and the other chrome in the talk's own CSS, never one rail across talks, and not rounded pills. Keep what they do: keyboard reach, 44px under a finger, and the current chapter marked by more than colour.
- **Colour is for one job each.** Give each colour one meaning across the talk and put names on the figure instead of a legend. Carry state with outlines and symbols: pale fills disappear under room light. When a figure needs a group of colours, score the candidates with `palette` and keep the set with the widest closest pair; see [references/look.md](references/look.md). A mark's meaning cannot be computed, so this is judgment, not a gate.
- **Judge at 1920 wide and on a phone.** `render` writes both; read the sheets as the room and a reader will see them.

## Writing it for the room

`# research(2026-10)`

The test for every slide: someone who has never heard the terms follows it.
The slide text and the script follow `<plugin-root>/_shared/plain-prose.md`; the
guidance below is what a deck adds to it. To check a script, run
`uv run --no-project --quiet python <plugin-root>/_shared/prose_check.py <deck>-script.md`.

- **The headline is the slide's claim**, a short full sentence ("Every query
  passes a code-only checkpoint first"), not a topic ("Architecture").
  Engineering students taught from claim headlines over visual evidence showed
  better comprehension and fewer misconceptions than with topic headlines over
  bullets ([2025 study](https://www.sciencedirect.com/science/article/pii/S2307187725001701)).
- **An agenda slide right after the title.** The talk's parts, in order, in
  plain words, and nothing else: it never mentions pauses, questions or
  discussion stops. It orients the room, and it is the presenter's map
  when a question pulls the talk off course. Keep the section names
  identical to the kicker labels on the slides they introduce ("3 · How it works · Before the data").
- **One slide says what we did and why this audience should care.** See
  [below](#what-we-did-and-why-you-should-care). It is a standing requirement
  for every talk.
- **A story arc.** The problem, the catch that makes it hard, the idea, how it
  works, what was found (including where it failed and what is still
  untested), what comes next, a short [conclusion](#the-conclusion) that
  sums it up, and a plain closing slide: "Thank you", the
  presenter's name and contact. No tagline or contrast-statement slide; the
  presenter introduces themselves and states the take-home aloud, in the script.
  A general audience keeps three to five main
  points ([Science Communication Toolkit](https://ecampusontario.pressbooks.pub/scicommtoolkit/chapter/talks/)).
  An honest limits slide makes the claims before it believable.
- **Plain words on the slide.** Name each idea in words a newcomer already
  knows ("Read-only, twice"). Add the paper's name for it in a muted footnote
  ("Paper term: law documents") only when the room will meet that term again:
  someone may use it in Q&A, or the audience will read the paper. Otherwise the
  plain words are enough. Spell out every acronym.
- **A footnote only when the room would miss it.** Footnotes are optional, and
  no slide needs one. Keep a footnote only if the audience would miss it: the
  source and date behind a number someone may question, a term they need, a
  caveat that changes how to read the figure ("Illustrative example", "Bars are
  not to scale"). Cut a footnote that restates the slide, explains a legend
  that is already obvious, or carries process detail (commit hashes, tool
  versions, how the figure was built); that goes in the script or on a backup
  slide. `check` raises a `footnotes` review when most talk slides carry one.
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
  Agenda, conclusion, closing and divider slides are exempt. A
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
- **Questions at the end, never a stop mid-talk.** Invite interruptions on
  the title slide ("Please stop me any time"), then take questions after the
  closing slide. Put no questions-only or discussion slide inside the talk:
  a stop just before the part the room will ask about earns only "I'm about
  to get to that". Holding questions for the end suits a talk that builds
  its case part by part ([Throughline](https://www.throughlinegroup.com/2013/10/03/five-times-to-take-questions-from-your-audience/)),
  and the title slide's invitation still lets anyone interrupt.
  An optional discussion prompt lives behind the backup divider, for a quiet
  Q&A: a plain slide with one short personal question anyone can answer
  without the paper ("What's one thing you would never let an AI do for
  you?"), and a muted line of example answers that gets the room started
  ("Send a message as you? Spend your money? Grade your work?").
- **Talk lean, backup unlimited.** A `Backup slides` divider (or an FAQ
  section, with `--backup-from`) separates the talk from Q&A material. Behind
  it, a slide can be as long and detailed as an answer needs: it is read when
  someone asks, not presented cold.
- **Source-bound.** When only one artifact is cleared for release (a prepub
  paper, say), every claim on a slide comes from it. Flag what you left out.

## What we did and why you should care

`# research(2026-10)`

Every talk deck makes two things plain, on one slide among the first two or
three content slides, right after the agenda:

- **What we did**: a concrete claim with a number or an artifact. What was
  built, measured or found, in one sentence a newcomer follows ("We ran 1,200
  agent sessions and found 61 leaked a credential"), not a topic or a goal.
- **Why this audience should care**: the stakes in the room's own terms,
  rewritten per room. A security audience hears what an attacker gains, a lab
  hears what it changes in their next experiment, a class hears what the
  method lets them do.

Rules that go with it:

- Mark the slide `data-contribution` (the starter's slide 3 does). `check`
  warns when no slide, or more than one, carries it, when it comes after slide
  5, or when it has no script.
- Every major section ties back to it: one plain line on its first slide or in
  its script says how the section serves the claim or the stakes.
- The script says the why-you-should-care line aloud, in the first person.
- It is a plain fact and its stakes, never a slogan. The anti-slogan rule in
  [A story arc](#writing-it-for-the-room) stands: no tagline intro, no
  contrast-statement slide, close on a plain "Thank you". "Why you should
  care" is a reason, not a catchphrase; "Security that never sleeps" fails it.

`check` cannot read meaning, so it does not try, and a slogan in the marked
slide passes it. A person decides, and the agent reports each item at the end
of the run:

1. The slide names what was done, with a number or an artifact.
2. It names a stake this room would state in its own words.
3. Each major section ties back to it.
4. The script says the stakes aloud.

## The conclusion

`# research(2026-11)`

The last content slide, right before the closing "Thank you", is a short
conclusion. It repeats the talk's point so the room leaves with it, and it
tells the room the talk is over. The structure is the old one: tell them what
you will tell them (the agenda), tell them, then tell them what you told them.
Dr. Pengcheng Shi's research-foundations lecture at RIT puts it this way:
the conclusion gives "a summary of the key results", gives open problems, and
indicates that the talk is over; summary slides "should be short"; use
repetition; do not overrun.

- **Mark it `data-conclusion`** (the starter's second-to-last talk slide does).
  `check` blocks when no slide, or more than one, carries it, or when it is not
  the slide right before the closing slide.
- **The title restates the main point in fresh words**, a claim like every
  other headline, never "Conclusion" or "Summary" (`check` warns on those).
- **Two to four key results the talk already showed**, one phrase each. No new
  material: a result first seen here is a result the room cannot weigh.
- **One or two open problems or next steps**, taken from the source work's own
  limits or future work, not invented for the slide.
- **Short.** Phrases, no new figure; it is read in under a minute.
- **The script ends with a clear "That's my talk."** Then the closing slide's
  script thanks the room and takes questions.
- **No `data-chapter`.** The agenda lists the parts of the talk, not the
  wrap-up: Peyton Jones, Hughes and Launchbury call "introduction" and
  "conclusion" trivia an outline should never list
  ([How to give a good research talk](https://www.cvast.tuwien.ac.at/sites/default/files/research-tips/good-talks.pdf)).
- **The one place the take-home is on a slide.** The no-tagline rule in
  [A story arc](#writing-it-for-the-room) still holds: the conclusion's
  headline is a claim the talk has earned, not a slogan.

## The script

The speaker notes hold the script: the words the presenter says out loud on
each slide, written to be read from like a teleprompter. A presenter who talks
from the slides rather than reading can keep three glanceable bullets per slide
in the notes (the points and numbers that must be said) and the full script in a
file beside the deck, one section per slide, which is the one to time. It supports the
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
- **The conclusion's script ends with "That's my talk."** It says the main
  point once more, in new words, and names the results and the open problem
  without adding anything.
- **The closing slide's script ends by taking questions** ("I'm glad to take
  questions."). A backup discussion prompt's script reads the question, offers
  one example answer, and ties it back to the talk.
- **Length.** Presenters speak at about 130 to 150 words a minute
  ([VirtualSpeech](https://virtualspeech.com/blog/average-speaking-rate-words-per-minute)).
  `script` prints the total, a guide to the time slot rather than a gate: when
  the talk runs long, cut slides' words and the script's asides, not figures.
- **Figures and answers to likely questions stay out of the script.** They go
  on backup slides and into the briefing.

Hand the presenter the exported `script` file along with the deck; they
should not have to find the notes pane to see it.

## The starter deck

`templates/web/` is a whole deck that passes `check` with one thing to review, its
`own-look`: it is a skeleton, not a look. Copy it, replace every bracketed placeholder, then
give it its own look (see [The look](#the-look)):

```
cp -r <skill-dir>/templates/web <talk-dir>
```

| File | Holds |
|---|---|
| `index.html` | One `<section>` per slide: title with a placeholder illustration, agenda, what we did and why you should care (`data-contribution`), claim with a figure that builds, concrete case, quick bet, method steps, related-work map, timeline, limits, conclusion (`data-conclusion`), Thank you, backup divider, backup discussion prompt, backup table. Drop the layouts the talk does not need; copy one to add a slide. |
| `deck.css` | A plain placeholder look, every slide light. The first block is the talk's tokens (ground, ink, four colour roles, faces) to replace. Then layouts, the chapter rail (working parts to keep, styling to replace), the phone layout, and the reduced-motion rule. |
| `fonts/` | Atkinson Hyperlegible Next and Mono (SIL Open Font License), served with the deck so it looks the same offline; a talk adds or swaps its own faces. |
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
kicker); the conclusion and closing slides take none. The agenda slide lists the chapters in order, and a rail across the top
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

## Figures for numbers

`# research(2026-10)`

- **Attrition: a flow of stages, never one width scale.** When stages count
  different things (comments, then pairs, then examples), a Sankey's shared
  widths are false. Draw a flow in the CONSORT style, a box per stage with its
  count and its reasons. Bars are to scale within a stage only, and the final
  count is set apart (ink, or gold when it is the speaker's own result). CONSORT recommends a flow diagram and
  prescribes no format ([CONSORT 2025](https://doi.org/10.1136/bmj-2024-081123)).
  The generator places every step of the source in a stage, or fails.
- **Parts of one estimate: a forest plot on one scale.** A dot and its interval
  for the whole, then for each part, against a "no effect" line, every panel on
  one shared axis so groups compare by eye. Say in the caption what the parts
  need to add up to the whole.
- **The headline claims only what the intervals show.** Compute the flags a
  sentence depends on in the build: interval above zero, interval holds zero.
  Bind the wording to them with `data-if` and `data-unless`. A changed result
  then changes the slide rather than leaving a stale claim.
- **Worked examples:** `buildFlow` and `buildForest` in
  [ajbarea/talks](https://github.com/ajbarea/talks) `shared/deck.js`, each with
  a tall phone layout.

## Motion

`# research(2026-10)`

Motion is for building an idea in steps and pointing at the one mark that
matters. It is never decoration.

- **Build a process in steps.** A figure that adds one stage per click (a
  `class="fragment"` on each SVG group or card) lets the room follow a complex
  idea at the presenter's pace. Learner-paced segments improved transfer in
  three of three tests ([Mayer, segmenting
  principle](https://www.cambridge.org/core/books/multimedia-learning/segmenting-principle/37240877DDA0362355ADB39936027982)).
- **Reveal in the order the speaker talks.** Each click shows what the script
  says next: a talk that goes column by column builds column by column (a
  group, its cases and its guard), not one row across every column at once.
  Set `data-fragment-index` when the order on the page differs from it.
- **Point at the mark.** Bring in the one dot, bar or arrow the claim is about
  last, in ink or the colour of its role. Cues that point at the essential material help
  learning ([signaling](https://u.osu.edu/multimedialearning/?p=88)); the cue does the work, not the movement.
- **Move no more than the eye can follow.** Viewers track about three to four
  moving objects as a set, and only one or two when each must keep its identity.
  Past that, move groups held together by a line or a shared colour, or move a
  few at a time ([Jiang et al.
  2026](https://doi.org/10.1186/s41235-026-00724-y), from the
  multiple-object-tracking literature).
- **One kind of change per step.** Show positions, then sizes, then colours, each
  in its own fragment, rather than all at once (task staging, same source). The
  presenter's click is the pacing control the same review recommends.
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

A web deck is published with GitHub Pages, and the link is the handout. Publish only what is cleared for release, and put the link on the closing slide: [references/publish.md](references/publish.md) holds the one-repo-per-talk layout and the steps.

## Traps

Before debugging a deck that loads wrong, draws wrong or checks wrong, read [references/traps.md](references/traps.md): the reveal.js, axe and print-layout pitfalls, and why the toolchain is what it is.

## Done means

1. `check` exits 0, and each `REVIEW` item is resolved or deliberately kept.
   The four manual items under [What we did and why you should
   care](#what-we-did-and-why-you-should-care) each pass, and the report says
   how. The conclusion restates the main point as a claim, lists only results
   the talk showed, takes its open problems from the work's own limits, and
   its script ends with "That's my talk."
2. `render` ran, and every slide was looked at at 1920 wide and on the phone,
   including the ones you did not change. A change of look was shown before it shipped.
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
