---
description: "Build a talk deck and gate it before it is presented: titles, contrast, alt text, missing files and phone fit."
---

# `graphe:slides`

Get a talk deck ready to present: start from the starter web deck, write it for someone who has never heard the terms, build the figures in steps, write the script to read aloud on each slide, gate it, render it on a desktop and a phone, publish it on GitHub Pages, and brief the presenter.

Part of [graphe](../plugins/graphe.md): `/plugin install graphe@techne`, then `/graphe:setup`.

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
B="uv run --no-project --quiet --with playwright==1.63.0 --with axe-playwright-python==0.1.8 --with pillow --with python-pptx==1.0.2"
$B python plugins/graphe/skills/slides/scripts/slides.py check <deck/index.html|deck.pptx|deck.pdf> [--jargon "term,term"] [--backup-from N] [--level {AAA,AA}] [--min-pt N] [--dense-words N] [--title-words N]
$B python plugins/graphe/skills/slides/scripts/slides.py render <deck/index.html|deck.pptx|deck.pdf> <out-dir> [--renderer {auto,powerpoint,libreoffice}] [--dpi N]
$B python plugins/graphe/skills/slides/scripts/slides.py script <deck/index.html|deck.pptx> [--wpm N] > script.md
$B python plugins/graphe/skills/slides/scripts/slides.py pptx <deck/index.html> <out.pptx> [--images <dir>]
$B python plugins/graphe/skills/slides/scripts/slides.py pdf <deck/index.html> <out.pdf>
```

A web deck is checked and rendered in Chromium through Playwright; install it once with `uv run --no-project --with playwright==1.63.0 playwright install chromium`. `script` reads a web deck in the same browser; a `.pptx` or PDF needs none. `script` exits 1 for a `--wpm` of zero or less, and prints `No script on this slide.` for a slide with no notes. Run the script it writes through `_shared/prose_check.py` (exit 0 clean, 1 when skipped); the slide text and the script follow `_shared/plain-prose.md`.

`check` takes `--level` (default `AAA`), `--min-pt` (14), `--dense-words` (60) and `--title-words` (14). `render` takes `--renderer` (default `auto`) and `--dpi` (80) for a `.pptx` or PDF. `script` takes `--wpm` (140).

`check` exits 0 when every gate passed, 1 when the file is not a readable deck, and 2 on a blocker. On a web deck, `render` writes one PNG per slide at 1920x1080 with every fragment shown, one per slide on a 390px-wide phone, contact sheets of both, and the print PDF; `--renderer` and `--dpi` apply to a `.pptx` or PDF only. A `.pptx` is exported through PowerPoint when it is installed and LibreOffice otherwise. Give `render` a folder of its own: it refuses a non-empty folder it did not create. `script` prints the speaker notes as one Markdown script with the talk length; backup slides come after the talk and are left out of the length. `pptx` exports a web deck for PowerPoint: one 1920x1080 picture per slide with every fragment shown, the script in the speaker notes, and the slide's title kept in the title placeholder just above the slide for the outline and screen readers; `--images` also writes the PNGs. `pdf` exports a web deck as a vector PDF: one page per slide with every fragment shown, selectable text and working links, from reveal.js's print layout printed by Chromium; `web-only` text is left out.

## What it checks

| Severity | Gate | Catches |
|---|---|---|
| BLOCK | `phone-clip` | Content drawn past the slide's edge on a 390px or 360px-wide phone. |
| BLOCK | `no-title` | A slide with no heading (web) or no title placeholder (`.pptx`). |
| BLOCK | `contrast` | Text below 7:1, or 4.5:1 for large text (`--level AA` relaxes both). Web decks are measured with axe-core against each slide's own background. |
| BLOCK | `alt-text` | An image or figure with no text alternative. |
| BLOCK | `em-dash` | An em-dash in slide text. |
| BLOCK | `asset`, `script` | A web deck that cannot load a file it asks for, or logs a console error, including a value with no data behind it. |
| BLOCK | `contribution` | A web deck with no slide marked `data-contribution`, more than one, the marked slide after slide 5, or no script on it. Every talk states what was done and why this audience should care on that slide; `check` verifies where it is, and the agent checks the wording by hand. |
| WARN | `small-text`, `overflow`, `nested-section`, `phone`, `motion`, `offline` | Text under 14pt; anything drawn past the slide's edge; a `<section>` inside slide content, which reveal.js shows as separate slides; text under 12px on a phone; animation that ignores reduced-motion settings; a deck that needs the network to present. |
| WARN | `unbound-data` | A value in the deck's data file that no slide or script binds; the file is published with the deck, so cut what no slide shows. |
| WARN | `font`, `no-notes`, `duplicate-title` | A font that will be substituted in PowerPoint or Google Slides (`.pptx`), talk slides with no script, titles a screen reader cannot tell apart. |
| REVIEW | `jargon` | A term from `--jargon` on a talk slide. |
| REVIEW | `figures`, `dense`, `long-title` | Numbers and walls of text on talk slides (slide 1 and everything after a divider titled `Backup`, `Backup slides` or `Appendix`, or from `--backup-from`, are exempt), and headlines that stopped being headlines. |

A PDF deck gets the gates its text can answer, read with `pdftotext`. A figure that reads wrong is invisible to `check`. That is what `render` is for.

## The starter deck

`plugins/graphe/skills/slides/templates/web/` is a reveal.js 6.0.2 deck that passes `check` with nothing to review: title, agenda, what we did and why this audience should care, a claim whose figure builds step by step, a concrete case, a quick bet answered with dots, method steps, a related-work map and timeline, a discussion stop, limits, Thank you, and backup slides. Copy the folder and open `index.html` in a browser; `S` opens the speaker view. Figures and related work are read from `data/deck-data.js`, so a repo can generate them from its results. A chapter rail and the agenda come from each slide's `data-chapter`. A slide binds a value with `data-value="results.failShare"` (add `data-format="pct"` for a share), draws a share as dots with `data-dots`, builds the related-work map from `data-source="related"`, and shows wording only when a result holds with `data-if` and `data-unless`. `data-notes` or an `<aside class="notes">` carries the script, `class="fragment"` builds a figure step by step, and `class="web-only"` text is hidden from a `.pptx` export. A key with no data behind it is a console error, which `check` blocks. On a phone the deck switches to a portrait scroll view.

`plugins/graphe/skills/slides/templates/pages.yml` publishes the deck folder to GitHub Pages. Its actions are pinned to the same commit SHAs as techne's own workflows, and `make guards` fails when they drift. A repository has one Pages site, but the site serves folders, so the skill recommends one public talks repo with a folder per talk, each at its own address; [ajbarea/talks](https://github.com/ajbarea/talks) is the worked example. The template is for a deck that must stay in a repo of its own.

## Testing it

`make test-unit` covers the `.pptx` gates against decks built in-test as minimal OOXML packages, and the web gates against copies of the starter deck in a real Chromium, each broken in one way: a missing heading, faint text, an image with no alt text, a missing file, a value with no data, an em-dash, a network font, a line wider than the slide, small text, motion that ignores reduced-motion settings, and a slide with no script. It also renders the starter and counts the slides, phone views and PDF pages. A machine without Chromium sets `TECHNE_NO_BROWSER=1` to say so; otherwise the suite fails rather than skipping those cases.

## Full instructions

[`SKILL.md` on GitHub](https://github.com/ajbarea/techne/blob/main/plugins/graphe/skills/slides/SKILL.md) holds the full instructions Claude follows for this skill.
