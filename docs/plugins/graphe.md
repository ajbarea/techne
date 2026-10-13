# graphe

graphe builds and checks documents: LaTeX papers, markdown rendered to PDF, and talk decks. It also scaffolds a research paper and runs a pre-submission novelty review. The [skill pages](../skills/index.md) describe each skill.

## Install

```bash
/plugin marketplace add ajbarea/techne
/plugin install graphe@techne
```

Then run `/graphe:setup`. It checks uv, TeX Live (latexmk, pdflatex, biber), poppler, `strings`, Playwright's Chromium, and the optional tools for `.pptx` decks. It only reads, and prints the install command for anything missing. Claude follows the [setup runbook](https://github.com/ajbarea/techne/blob/main/plugins/graphe/AGENTS.md).

## First use

- `/graphe:latex paper/main.tex` builds the paper and checks the log and the PDF.
- `/graphe:pdf notes.md` renders markdown to a PDF.
- `/graphe:slides` starts a web talk deck from the starter.

## Troubleshooting

- **A script says `latexmk` is not on PATH.** It prints the install command for your system. On Debian or Ubuntu that is `sudo apt install texlive-latex-extra latexmk`; on macOS, `brew install --cask mactex-no-gui`, then a new terminal.
- **`pdftotext` or `pdftoppm` is missing.** Install poppler: `sudo apt install poppler-utils`, or `brew install poppler`.
- **Chromium does not start on Linux.** Run `uv run --no-project --with playwright==1.63.0 playwright install-deps chromium`, which installs its system libraries with `sudo apt`.
- **graphe on claude.ai.** The skills install there, and their build steps run shell commands that need Claude Code.
