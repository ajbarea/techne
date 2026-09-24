# techne — Implementation scratchpad

The active TODO list for whatever's in flight **right now** — current
PR, open design question blocking me, immediate next pickup. Queued
specs, cross-skill themes, and "next up" ordering live in
[ROADMAP.md](./ROADMAP.md). Git history is the permanent record of
how each skill was designed.

If this file is more than ~50 lines, something queued or referential
has crept in — extract it back to ROADMAP.

## In flight

**`techne:slides` from its gold-standard deck** (branch `feat/slides-newcomer`).

- **Why:** the makesense talk v2 (2026-09-23) is the deck AJ wants every future deck to match;
  the skill had its gates but not the writing moves or the look that made it work.
- **Decisions:** `# research(2026-09)`: plain-language and three-to-five-point guidance for
  general audiences, concreteness fading, 130-150 words a minute, PowerPoint's recording
  teleprompter reads the notes. pptxgenjs 4.0.1 is current.
- **Scope:** newcomer writing guidance; notes as a read-aloud script plus a `script`
  subcommand; `no-notes` exempts backup slides; `templates/deck.js` starter; routing case for
  "make me a PowerPoint".
- **Out of scope:** a Touying starter; checking the script's wording.
- **Done when:** `make validate` green, the starter passes `check` and renders cleanly through
  PowerPoint, the new routing case passes, reviewed, CI green, merged.

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
