# graphe setup runbook

This is the setup guide for graphe, written for an agent guiding a user. Run the doctor first, then work through only the lines it marks `missing` or `optional`. The setup skill gives the doctor command.

## Rules

- The doctor only reads. Run it again after each fix to confirm.
- The user runs every fix line that contains `sudo`, `xcode-select --install` or a Homebrew cask (a cask install asks for the admin password). In Claude Code they type it after `!`, for example `!sudo apt install poppler-utils`.
- The Chromium library install needs `sudo` inside it, so the user runs that one too.
- You may run any other fix line after the user approves, such as the uv installer, a Homebrew formula install without `sudo`, the Chromium install and the pptxgenjs install.
- Report only what the doctor printed.

## 1. Run the doctor

Each line starts with `ok`, `missing`, `optional` or `n/a`, then the check's name and a detail. A `missing` or `optional` line is followed by one or more `fix:` lines. The last line is `result: ready`, or `result: missing` with the names of the required checks that failed. The doctor exits 0 when nothing required is missing.

If the shell says `python3` is not found, the doctor cannot start. The user installs it with `sudo apt install python3` on Debian or Ubuntu, or `xcode-select --install` on macOS.

## 2. Fix each missing line

| Check | Used by | What to do |
| --- | --- | --- |
| `uv` | every graphe script | Run the fix line after the user approves, then open a new terminal so `uv` is on PATH. |
| `latexmk`, `pdflatex` | graphe:latex, graphe:paper | The user runs the fix line with `!`. One install covers both. After a macOS install, open a new terminal. |
| `biber` | documents that use biblatex | Optional. On Debian or Ubuntu the user runs the fix line with `!`. On macOS you may run it after the user approves. |
| `pdftotext`, `pdfinfo`, `pdffonts`, `pdftoppm` | graphe:latex gates, graphe:slides | On Debian or Ubuntu the user runs the fix line with `!`. On macOS you may run it after the user approves. One poppler install covers all four. |
| `strings` | graphe:pdf font report | The user runs the fix line with `!`. It is part of binutils on Linux and of the Xcode command line tools on macOS. |
| `chromium` | graphe:slides web decks | Run the fix line after the user approves; it downloads the Chromium build that Playwright 1.63.0 uses. If the doctor says it does not run on Linux, a system library is missing: the user types `uv run --no-project --with playwright==1.63.0 playwright install-deps chromium` after `!`, and it calls `sudo apt` itself. |
| `pptx-renderer` | rendering a `.pptx` deck | Optional. The user runs the fix line with `!`. PowerPoint on Windows, or under WSL, also counts. |
| `node` | building a `.pptx` deck | Optional. On Debian or Ubuntu the user runs the fix line with `!`. On macOS you may run it after the user approves. |
| `pptxgenjs` | building a `.pptx` deck | Optional. Run the fix line in the folder that will hold the deck, after the user approves. It installs into that folder's `node_modules`, so it needs no `sudo`. |

## 3. Check the result

Run the doctor again. When it prints `result: ready`, suggest `/graphe:latex` on a `.tex` file or `/graphe:slides` to start a talk.
