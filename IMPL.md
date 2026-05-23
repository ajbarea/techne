# techne — Implementation scratchpad

The active TODO list for whatever's in flight **right now** — current
PR, open design question blocking me, immediate next pickup. Queued
specs, cross-skill themes, and "next up" ordering live in
[ROADMAP.md](./ROADMAP.md). Historical design specs archived under
[`superpowers/specs/`](./superpowers/specs/). Git history is the
permanent record.

If this file is more than ~50 lines, something queued or referential
has crept in — extract it back to ROADMAP.

## In flight

Nothing currently open. The 2026-05-23 audit-checks expansion (system-dep
drop in Makefile + 4 new sister-audit checks: `allow_auto_merge`,
`codecov.yml` / `comment: false`, branch protection on `main`, and
`make clean` log-retention policy) shipped as [#16], [#17], [#18], [#19],
[#21] — see ROADMAP `## Shipped`.

Next natural pickup: any of the queued skills from ROADMAP
`## Queued / unprioritized` (`narrative-coherence`, `positioning`,
`research-grounded`, `workspace-orphans`) once their n≥2 trigger fires.

## Skill collection state

Nine skills shipped as of 2026-05-23, four catalog dimensions:

| Dimension | Skills |
| --- | --- |
| **Audit** | `audit`, `ci-audit` |
| **Drift** | `docsync`, `docs-site`, `sisters` |
| **Hygiene** | `auto-commit`, `deslop`, `reslop` |
| **Observation** | `theoros` |

When picking up the next session, replace the "In flight" block above
with a full session plan (Why / Decisions / Scope / Out of scope /
Definition of done) following the same template every other sister
uses.
