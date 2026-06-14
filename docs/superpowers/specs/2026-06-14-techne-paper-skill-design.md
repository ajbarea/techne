# techne:paper — skill design

**Date:** 2026-06-14 · **Status:** accepted (autonomy-granted) · **Author:** AJ Barea

## Context

This session applied a scaffold+harvest pattern for research papers **four times** by hand
(velocity, kourai, ariadne, techne papers in `ajbarea/papers`). The `papers/README` flagged a
`techne:paper` skill as "deferred until the pattern proves itself (n>=2)". The bar is cleared;
this extracts the proven pattern into a techne skill.

## What it does

One core action: **scaffold a new first-author paper** in a papers-style monorepo. Given a
paper `<name>` (+ optional `--from <sister>`, `--venue`), create:

- `papers/<name>/main.tex` — title/author + abstract slot + `\input` sections +
  `\bibliography{../references}` + the `\nocite{*}` build-enabler (with a remove-me note).
- `papers/<name>/sections/*.tex` — stubs carrying `% HARVEST:` pointers (default set:
  intro+related, design, evaluation, conclusion).
- `papers/<name>/harvest.py` — regenerates a data/eval table from the source sister's corpus
  into `figures/`, with an editable, documented category map (no hand-typed numbers).
- `papers/<name>/figures/.gitkeep`.

Then: wire the shared bib, add a row to `papers/LINEAGE.md`, and build-verify with the available
LaTeX engine (tectonic if present; else print the Overleaf note).

## Config contract

Reads `## paper` from `<repo>/.claude/skill-context.md`: default author/affiliation, bib path
(default `../references.bib`), section set, LaTeX engine, and a sister->source map. Falls back
to sensible defaults if absent. Building this also adds a minimal `papers/.claude/skill-context.md`
`## paper` section (papers-specific config + a partial fix for the audit's skill-context-absent gap).

## Structure (progressive disclosure)

- `plugins/techne/skills/paper/SKILL.md` — lean instructions (<5k tokens); third-person
  description with explicit triggers ("scaffold a paper", "start a new paper", "new paper dir
  from <repo>").
- `plugins/techne/skills/paper/templates/{main.tex,section.tex,harvest.py}.tmpl` — canonical
  template files (kept out of SKILL.md per progressive-disclosure practice; placeholders like
  `__NAME__`, `__TITLE__`, `__AUTHOR__` filled at scaffold time).

## ADR — instruction-skill + template files (Approach A)

- **Decision:** lean SKILL.md + `templates/` files; the skill copies and fills them.
- **Rejected:** (B) everything inline in SKILL.md — bloats it past the lean target, worse
  discovery. (C) a bundled generator script — over-engineered; techne skills are
  instruction-based (YAGNI).
- **Consequence:** techne gains its first `templates/`-bearing skill (justified by best practice).

## Registration + verification

- Add `docs/skills/paper.md`, a row in `docs/skills/index.md` and the README skill table, and
  the entry in `.claude-plugin/marketplace.json`.
- **Verify:** dry-run scaffold a throwaway paper, build it with tectonic, confirm the PDF + the
  `LINEAGE.md` row, then delete the throwaway.
