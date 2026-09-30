# techne — Implementation scratchpad

The active TODO list for whatever's in flight **right now** — current
PR, open design question blocking me, immediate next pickup. Queued
specs, cross-skill themes, and "next up" ordering live in
[ROADMAP.md](./ROADMAP.md). Git history is the permanent record of
how each skill was designed.

If this file is more than ~50 lines, something queued or referential
has crept in — extract it back to ROADMAP.

## In flight

**Plain prose at write time** (branch `feat/plain-prose`).

- **Why:** two documents (a course proposal, a course manuscript) were drafted ornate and needed a
  second concision pass, although a concise-prose preference was already recorded. The writing
  skills gated the build, never the prose.
- **Decisions:** `# research(2026-09)`: Vale is the standard prose linter, but it is a separate
  binary and its rule packs target generic wordiness, not restating lines; a stdlib check that
  reads its patterns from the rubric keeps one source and no dependency.
- **Scope:** `_shared/plain-prose.md` (rubric + `prose-patterns`), `_shared/prose_check.py`,
  `REVIEW prose` in the latex and pdf gates, rubric read before drafting in latex/pdf/paper/slides,
  claims + structure checks and `.tex` paths in paper-review.
- **Out of scope:** Word documents (not a techne skill; pointed at from global CLAUDE.md).
- **Done when:** `make validate` green, reviewed, CI green, merged.

## Skill collection state

Shipped skills by catalog dimension (the directory listing of `plugins/techne/skills/` is the source of truth):

| Dimension | Skills |
| --- | --- |
| **Audit** | `audit`, `ci-audit` |
| **Drift** | `docsync`, `docs-site`, `research-grounded`, `sisters` |
| **Hygiene** | `auto-commit`, `deslop`, `reslop` |
| **Review** | `catchup`, `elenchus` |
| **Observation** | `theoros` |
| **Document build** | `latex`, `pdf`, `paper`, `paper-review`, `slides` |

When picking up the next session, replace the "In flight" block above
with a full session plan (Why / Decisions / Scope / Out of scope /
Definition of done) following the same template every other sister
uses.
