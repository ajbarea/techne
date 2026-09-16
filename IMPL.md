# techne — Implementation scratchpad

The active TODO list for whatever's in flight **right now** — current
PR, open design question blocking me, immediate next pickup. Queued
specs, cross-skill themes, and "next up" ordering live in
[ROADMAP.md](./ROADMAP.md). Git history is the permanent record of
how each skill was designed.

If this file is more than ~50 lines, something queued or referential
has crept in — extract it back to ROADMAP.

## In flight

Nothing currently open. Shipped this session: `/techne:latex`
(ROADMAP `## Shipped`), the build-and-gate sibling of `/techne:pdf`,
the repo's first pytest suite, which it brought with it, and coverage
for `render.py` and `sweep.py` under the same harness (114 tests).
Every skill-shipped Python file now has tests.

Known gap, not yet covered: the event-cap logic in `sweep.py`'s `main()`,
which decides what survives when a busy repo overflows `--max-events`.
It is a closure over local state, so covering it means lifting it out
the way `collapse_cascade` was.

Next natural pickup: any of the queued skills from ROADMAP
`## Queued / unprioritized` (`narrative-coherence`, `positioning`,
`workspace-orphans`) once their n≥2 trigger fires.

## Skill collection state

Sixteen skills shipped as of 2026-09-16, five catalog dimensions:

| Dimension | Skills |
| --- | --- |
| **Audit** | `audit`, `ci-audit` |
| **Drift** | `docsync`, `docs-site`, `research-grounded`, `sisters` |
| **Hygiene** | `auto-commit`, `deslop`, `reslop` |
| **Observation** | `theoros` |
| **Document build** | `latex`, `pdf`, `paper`, `paper-review` |

When picking up the next session, replace the "In flight" block above
with a full session plan (Why / Decisions / Scope / Out of scope /
Definition of done) following the same template every other sister
uses.
