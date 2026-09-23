# techne — Implementation scratchpad

The active TODO list for whatever's in flight **right now** — current
PR, open design question blocking me, immediate next pickup. Queued
specs, cross-skill themes, and "next up" ordering live in
[ROADMAP.md](./ROADMAP.md). Git history is the permanent record of
how each skill was designed.

If this file is more than ~50 lines, something queued or referential
has crept in — extract it back to ROADMAP.

## In flight

**Skill routing and prose pass** (branch `chore/skill-routing-and-prose`).

- **Why:** general document skills (PDF, PPTX, inbox catch-up) now share sessions with techne,
  and their descriptions claim any PDF or `.pptx` work. Nothing tested which skill fires.
- **Decisions:** `# research(2026-09)`: platform.claude.com skill-authoring best practices
  (what + when in the description, under 1,024 characters, SKILL.md under 500 lines,
  references one level deep, scripts for deterministic work) and code.claude.com plugin-evals
  (`tool_used: Skill` graders; a case's `plugins` list replaces the plugin under test, so
  techne and the rival stand-ins are assembled into one eval-only plugin).
- **Scope:** routing and scope lines in descriptions; `make evals` routing suite with
  must-fire and must-not-fire cases; `paper` builds through `techne:latex`; `sisters` split
  into a reference file with its pin-regex, team-exemption and non-Python fixes; theoros ships
  its lifecycle script and stops calling a repo's `make theoros`; auto-commit fingerprint
  covers untracked files; elenchus recommends `ultra` instead of launching it.
- **Out of scope:** behavioral evals of prose-only skills against fixture repos.
- **Done when:** `make validate` green, routing suite passing, reviewed, CI green, merged.

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
