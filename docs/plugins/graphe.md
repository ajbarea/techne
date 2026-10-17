---
description: graphe plugin, the document skills for Claude Code. Build and gate LaTeX papers, render markdown to PDF, make talk decks, scaffold a paper and review it before submission.
---

# graphe

graphe builds and checks documents: LaTeX papers, markdown rendered to PDF, and talk decks. It also scaffolds a research paper and runs a pre-submission novelty review.

## Use it when

- A `.tex` file needs a build that checks the log, the PDF and the assignment.
- Markdown should become a print-quality PDF.
- You are making or revising a talk deck.
- You are starting a paper in a papers-style monorepo, or want a novelty and reviewer pass on a draft.

## Install

```text
/plugin marketplace add ajbarea/techne
/plugin install graphe@techne
```

## Needs

uv, TeX Live (latexmk and pdflatex; biber for biblatex documents), poppler (`pdftotext`, `pdfinfo`, `pdffonts`, `pdftoppm`), `strings` from binutils, Playwright's Chromium, and python3 3.9 or newer to run the doctor. LibreOffice or PowerPoint, Node and pptxgenjs are optional and only for `.pptx` decks.

## Set up

Run `/graphe:setup`. It only reads, and prints the install command (a `fix:` line) for anything missing. The last line is `result: ready`, or `result: missing` with the names of the required checks that failed, and the doctor exits 1 in that case. Chromium is a required check, so a LaTeX-only user still sees `result: missing chromium` until it is installed. It also reports which search keys are saved. Claude follows the [setup runbook](https://github.com/ajbarea/techne/blob/main/plugins/graphe/AGENTS.md).

## Search keys

paper-review runs without keys. An OpenAlex key raises its daily search budget, and a Semantic Scholar key adds Semantic Scholar. Run `/plugin configure graphe@techne`, paste each key into its masked field, and restart Claude Code. The keys sit in Claude Code's secure storage. At session start graphe writes them to a private (0600) per-process file in its plugin data folder that Bash commands load, and deletes the file when the session ends. To import them from a `.env` file instead, `/graphe:setup` prints a template and saves the filled-in file with a store script; the file is yours to delete afterwards. A key already in the Bash environment, such as one exported in your shell profile, wins. If heuresis and graphe both save the same key, keep the two values the same: either plugin's value may be the one a session uses.

## Skills

| Skill | Use it to |
|---|---|
| [`graphe:latex`](../skills/latex.md) | Build a LaTeX document and gate it on its log and PDF. |
| [`graphe:paper`](../skills/paper.md) | Scaffold a paper directory in a papers-style monorepo. |
| [`graphe:paper-review`](../skills/paper-review.md) | Run a novelty and reviewer pass on a draft. |
| [`graphe:pdf`](../skills/pdf.md) | Render markdown to PDF and verify fonts and content. |
| [`graphe:setup`](../skills/graphe-setup.md) | Check what graphe needs on this machine. |
| [`graphe:slides`](../skills/slides.md) | Build and gate a talk deck. |

First runs:

- `/graphe:latex paper/main.tex` builds the paper and checks the log and the PDF.
- `/graphe:pdf notes.md` renders markdown to a PDF.
- `/graphe:slides` starts a web talk deck from the starter.
- `/graphe:paper` scaffolds a new paper; `/graphe:paper-review` reviews a draft before submission.

## Configuration

`graphe:latex`, `graphe:paper` and `graphe:paper-review` read the `## latex`, `## paper` and `## paper-review` sections of the repo's `.claude/skill-context.md`; each skill page lists its keys. [Conventions](../conventions.md) describes the file.

## Troubleshooting

- **A script says `latexmk` is not on PATH.** It prints the install command for your system. On Debian or Ubuntu that is `sudo apt install texlive-latex-extra latexmk`; on macOS, `brew install --cask mactex-no-gui`, then a new terminal.
- **`pdftotext` or `pdftoppm` is missing.** Install poppler: `sudo apt install poppler-utils`, or `brew install poppler`.
- **Chromium does not start on Linux.** Run `uv run --no-project --with playwright==1.63.0 playwright install-deps chromium`, which installs its system libraries with `sudo apt`.
- **graphe on claude.ai.** The skills install there, and their build steps run shell commands that need Claude Code.
