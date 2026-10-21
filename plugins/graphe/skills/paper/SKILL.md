---
name: paper
description: Scaffold a new research paper in a papers-style monorepo (a repo of LaTeX paper directories that share one bibliography): the LaTeX skeleton, a results-harvest script, the shared-bib wiring, and a portfolio row, built once so it compiles on day one. Use when starting a new paper: "scaffold a paper", "start a new paper", "set up a paper dir", "new paper from a sister repo", "add a paper to papers/". Not for editing an existing paper's prose or for one-off documents outside such a repo.
disable-model-invocation: false
allowed-tools: Bash Glob Grep Read Edit Write
---

# Paper Scaffold

`<plugin-root>` is the plugin's root directory, two levels above the directory holding this SKILL.md.

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

Read the `## paper` section of `<repo>/.claude/skill-context.md` (`bash "<plugin-root>/_shared/skill_context.sh" <target>` prints it) for: `author`,
`affiliation`, `email`, `bib` (default `../references`), and `portfolio` (default
`LINEAGE.md`). Use sensible defaults if absent.

Builds go through `graphe:latex` (latexmk on TeX Live), the same runner the paper will build
with until submission. An `engine` key in the config is ignored: tectonic ships its own
biblatex, which skews against a system biber the moment a paper moves off classic BibTeX.

## Procedure

1. Refuse if `papers/<name>/` already exists — never overwrite a paper.
2. Copy `templates/main.tex.tmpl` → `papers/<name>/main.tex`, filling `__TITLE__` (title-cased
   from `<name>`; confirm with the user), `__AUTHOR__`, `__AFFIL__`, `__EMAIL__`, `__VENUE__`,
   `__BIB__`, `__NAME__`, and `__BUDGET__` from the venue's page limit (`8 pages`, or
   `8 pages before references` when the venue excludes the references; ask when no venue is
   set; `none` only when the user says the paper has no limit). Confirm no `__` placeholder
   survives.
3. Copy `templates/harvest.py.tmpl` → `papers/<name>/harvest.py`, filling `__SISTER__`
   (`--from`, else `TODO`). Create `papers/<name>/figures/.gitkeep`.
4. Append a row to the portfolio file's first-author table:
   `| <name> | <repo> | (contribution -- fill in) | scaffolded |`.
5. Build-verify with the `graphe:latex` runner:
   `uv run --no-project --quiet python <plugin-root>/skills/latex/scripts/latex.py papers/<name>/main.tex`.
   A fresh scaffold exits 2 with exactly one blocker, `draft-marker` for the template's
   `TODO` placeholders; that is the expected result. Any other finding is a real failure.
   Report the PDF path and size. Without TeX Live, say so and point at Overleaf instead.
6. Quality setup. Copy `templates/conventions.md.tmpl` and `templates/CUTS.md.tmpl` into
   `papers/<name>/`. With `--venue`, fill the conventions sheet from the venue's accepted
   papers per `_shared/paper-quality.md` (structure and counts, titles only). Read that file
   before any drafting: it sets the bar, voice, integrity guards and registered-report tense.
7. Report the directory, the build status, and: "write prose into the `% HARVEST:` blocks
   following `_shared/plain-prose.md`; run `python harvest.py` once `--from` is wired."
   Read `<plugin-root>/_shared/plain-prose.md` yourself before writing any of the prose.
   The author writes the claim-bearing sentences; you do structure, editing and evidence tracing.

## Common mistakes

- Hand-typing result numbers — they belong in `harvest.py` output (`\input`-ed) so they
  regenerate. The template's `\nocite{*}` line is only a build-enabler; delete it once real
  `\cite{}` commands exist (an empty bibliography errors under many classes).
- Drafting claim sentences for the author, or copying prose from accepted papers.
- Stating an ethics or IRB determination the author has no written record of.
- Overwriting an existing paper dir — step 1 guards this.

The exact `main.tex`, `harvest.py`, `conventions.md` and `CUTS.md` scaffolds live in `templates/`.
