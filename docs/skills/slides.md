# `graphe:slides`

Get a talk deck ready to present: start from the starter web deck, write it for someone who has never heard the terms, build the figures in steps, write the script to read aloud on each slide, gate it, render it on a desktop and a phone, publish it on GitHub Pages, and brief the presenter.

## When to use

- "Make a deck for Friday's talk," or "turn this paper into a talk."
- An animated deck to present from a browser, with the link as the handout.
- Showing how the work differs from related work, as a map and a timeline drawn from data.
- "Is this deck ready?" before it goes to a room, a recording, or a teammate.
- A recorded talk or video that needs a script to read from, slide by slide.
- Checking an existing `.pptx` or a Typst or Beamer PDF deck.

## Usage

Invoke by name in Claude Code:

```
/graphe:slides
```

Or run the checks directly from a techne checkout:

```
B="uv run --no-project --quiet --with playwright==1.63.0 --with axe-playwright-python==0.1.8 --with pillow"
$B python plugins/graphe/skills/slides/scripts/slides.py check <deck/index.html|deck.pptx|deck.pdf> [--jargon "term,term"] [--backup-from N] [--level {AAA,AA}] [--min-pt N] [--dense-words N] [--title-words N]
$B python plugins/graphe/skills/slides/scripts/slides.py render <deck/index.html|deck.pptx|deck.pdf> <out-dir> [--renderer {auto,powerpoint,libreoffice}] [--dpi N]
$B python plugins/graphe/skills/slides/scripts/slides.py script <deck/index.html|deck.pptx> [--wpm N] > script.md
```

A web deck is checked and rendered in Chromium through Playwright; install it once with `uv run --no-project --with playwright==1.63.0 playwright install chromium`. `script` reads a web deck in the same browser; a `.pptx` or PDF needs none.

`check` takes `--level` (default `AAA`), `--min-pt` (14), `--dense-words` (60) and `--title-words` (14). `render` takes `--renderer` (default `auto`) and `--dpi` (80) for a `.pptx` or PDF. `script` takes `--wpm` (140).

`check` exits 0 when every gate passed, 1 when the file is not a readable deck, and 2 on a blocker. On a web deck, `render` writes one PNG per slide at 1920x1080 with every fragment shown, one per slide on a 390px-wide phone, contact sheets of both, and the print PDF; `--renderer` and `--dpi` apply to a `.pptx` or PDF only. A `.pptx` is exported through PowerPoint when it is installed and LibreOffice otherwise. Give `render` a folder of its own: it refuses a non-empty folder it did not create. `script` prints the speaker notes as one Markdown script with the talk length; backup slides come after the talk and are left out of the length.

## What it checks

| Severity | Gate | Catches |
|---|---|---|
| BLOCK | `no-title` | A slide with no heading (web) or no title placeholder (`.pptx`). |
| BLOCK | `contrast` | Text below 7:1, or 4.5:1 for large text (`--level AA` relaxes both). Web decks are measured with axe-core against each slide's own background. |
| BLOCK | `alt-text` | An image or figure with no text alternative. |
| BLOCK | `em-dash` | An em-dash in slide text. |
| BLOCK | `asset`, `script` | A web deck that cannot load a file it asks for, or logs a console error, including a value with no data behind it. |
| WARN | `small-text`, `overflow`, `nested-section`, `phone`, `motion`, `offline` | Text under 14pt; anything drawn past the slide's edge; a `<section>` inside slide content, which reveal.js shows as separate slides; text under 12px or content off the slide on a phone; animation that ignores reduced-motion settings; a deck that needs the network to present. |
| WARN | `font`, `no-notes`, `duplicate-title` | A font that will be substituted in PowerPoint or Google Slides (`.pptx`), talk slides with no script, titles a screen reader cannot tell apart. |
| REVIEW | `jargon` | A term from `--jargon` on a talk slide. |
| REVIEW | `figures`, `dense`, `long-title` | Numbers and walls of text on talk slides (slide 1 and everything after a `Backup` divider are exempt), and headlines that stopped being headlines. |

A PDF deck gets the gates its text can answer, read with `pdftotext`. A figure that reads wrong is invisible to `check`. That is what `render` is for.

## The starter deck

`plugins/graphe/skills/slides/templates/web/` is a reveal.js 6.0.2 deck that passes `check` with nothing to review: title, agenda, a claim whose figure builds step by step, a concrete case, a quick bet answered with dots, method steps, a related-work map and timeline, a discussion stop, limits, Thank you, and backup slides. Copy the folder and open `index.html` in a browser; `S` opens the speaker view. Figures and related work are read from `data/deck-data.js`, so a repo can generate them from its results. A chapter rail and the agenda come from each slide's `data-chapter`. On a phone the deck switches to a portrait scroll view.

`plugins/graphe/skills/slides/templates/pages.yml` publishes the deck folder to GitHub Pages. Its actions are pinned to the same commit SHAs as techne's own workflows, and `make guards` fails when they drift. A repository has one Pages site, so a repo that already publishes a docs site needs the deck in its own repo or inside that site's build.

## Testing it

`make test-unit` covers the `.pptx` gates against decks built in-test as minimal OOXML packages, and the web gates against copies of the starter deck in a real Chromium, each broken in one way: a missing heading, faint text, an image with no alt text, a missing file, a value with no data, an em-dash, a network font, a line wider than the slide, small text, motion that ignores reduced-motion settings, and a slide with no script. It also renders the starter and counts the slides, phone views and PDF pages. A machine without Chromium sets `TECHNE_NO_BROWSER=1` to say so; otherwise the suite fails rather than skipping those cases.
