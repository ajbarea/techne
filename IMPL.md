# techne — Implementation scratchpad

The active TODO list for whatever's in flight **right now** — current
PR, open design question blocking me, immediate next pickup. Queued
specs, cross-skill themes, and "next up" ordering live in
[ROADMAP.md](./ROADMAP.md). Git history is the permanent record of
how each skill was designed.

If this file is more than ~50 lines, something queued or referential
has crept in — extract it back to ROADMAP.

## In flight

**`techne:slides`** (branch `feat/slides-skill`).

- **Why:** a talk deck rebuilt for a student audience surfaced the same checks by hand
  every time: real slide titles, contrast, fonts that survive Google Slides, numbers the
  room does not need, and rendering through the app that will present it.
- **Decisions:** Typst + Touying for decks presented as PDF, pptxgenjs when a `.pptx` is
  required. The checker parses OOXML with the stdlib and needs no Office install; render
  prefers PowerPoint over COM (reached from WSL) because LibreOffice substitutes fonts.
  `# research(2026-09)`: WCAG 1.4.6 thresholds (7:1, large 4.5:1 at 18pt / 14pt bold);
  pptxgenjs table margins are inches since v3.8.0 (read in `pptxgen.cjs.js`, docs say points).
- **Scope:** `SKILL.md`, `scripts/slides.py` (`check`, `render`), unit tests, every listing.
- **Out of scope:** a Touying template; the pptx API itself (the Anthropic `pptx` skill).
- **Done when:** `make validate` green, independent review clean, CI green, merged.

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
