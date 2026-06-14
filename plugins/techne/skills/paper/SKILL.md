---
name: paper
description: Use when starting or scaffolding a new research paper in a papers-style monorepo (a repo of LaTeX paper directories that share one bibliography). Triggers include "scaffold a paper", "start a new paper", "set up a paper dir", "new paper from <repo>", "add a paper to papers/".
---

# Paper Scaffold

## Overview

Papers in a research monorepo follow one shape: a per-paper LaTeX directory that shares the
repo's `references.bib`, harvests its results from a sibling code repo, and is tracked in a
portfolio record. This skill scaffolds that shape so a new paper builds on day one and you
only write prose.

**Core principle:** a paper is a *harvest of the code* — result numbers come from a script
that reads the source repo's corpus, never hand-typed.

## When to use

- Starting a new first-author paper in a `papers/`-style repo.
- "Scaffold a paper called X", "new paper from `<sister>`".
- NOT for editing an existing paper's prose, or for one-off non-repo documents.

## Inputs

- `<name>` — kebab-case paper / directory name (e.g. `kourai`, `velocity-fl-systems`).
- `--from <repo>` (optional) — sibling code repo the results harvest from.
- `--venue <venue>` (optional) — target venue, recorded in the header and portfolio.

## Config

Read the `## paper` section of `<repo>/.claude/skill-context.md` for: `author`,
`affiliation`, `email`, `bib` (default `../references`), `engine` (default `tectonic`, else
`pdflatex`), and `portfolio` (default `LINEAGE.md`). Use sensible defaults if absent.

## Procedure

1. Refuse if `papers/<name>/` already exists — never overwrite a paper.
2. Copy `templates/main.tex.tmpl` → `papers/<name>/main.tex`, filling `__TITLE__` (title-cased
   from `<name>`; confirm with the user), `__AUTHOR__`, `__AFFIL__`, `__EMAIL__`, `__VENUE__`,
   `__BIB__`, `__NAME__`, `__ENGINE__`.
3. Copy `templates/harvest.py.tmpl` → `papers/<name>/harvest.py`, filling `__SISTER__`
   (`--from`, else `TODO`). Create `papers/<name>/figures/.gitkeep`.
4. Append a row to the portfolio file's first-author table:
   `| <name> | <repo> | (contribution -- fill in) | scaffolded |`.
5. Build-verify: run the configured engine in `papers/<name>/`. On success, report the PDF
   path + size. If no engine is installed, print an Overleaf note instead of failing.
6. Report the directory, the build status, and: "write prose into the `% HARVEST:` blocks;
   run `python harvest.py` once `--from` is wired."

## Common mistakes

- Hand-typing result numbers — they belong in `harvest.py` output (`\input`-ed) so they
  regenerate. The template's `\nocite{*}` line is only a build-enabler; delete it once real
  `\cite{}` commands exist (an empty bibliography errors under many classes).
- Overwriting an existing paper dir — step 1 guards this.

The exact `main.tex` and `harvest.py` scaffolds live in `templates/`.
