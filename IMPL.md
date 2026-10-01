# techne — Implementation scratchpad

The active TODO list for whatever's in flight **right now** — current
PR, open design question blocking me, immediate next pickup. Queued
specs, cross-skill themes, and "next up" ordering live in
[ROADMAP.md](./ROADMAP.md). Git history is the permanent record of
how each skill was designed.

If this file is more than ~50 lines, something queued or referential
has crept in — extract it back to ROADMAP.

## In flight

**Opt-in guard hooks** (branch `feat/opt-in-hooks`, issue #89).

- **Why:** the commit and staging rules were prose a session had to remember, and a system
  reminder could contradict them. Nothing enforced them.
- **Decisions:** `# research(2026-10)`: plugin `userConfig` booleans reach hooks as
  `CLAUDE_PLUGIN_OPTION_<KEY>=true`, so each guard defaults off and only the user who switches it
  on gets it. Plugin hook denies hold in `bypassPermissions` (verified live). One stdlib script
  per tool family (`git`, `gh`) so a compound command is checked once. `claude plugin validate`
  allows only the missing-`version` warning, since techne is unversioned on purpose.
- **Scope:** `plugins/techne/hooks/`, `userConfig` in `plugin.json`, `tests/test_git_guards.py`,
  `scripts/check_plugin_manifest.sh` + `make plugin-validate` in CI, Guards section in
  `docs/configuration.md`.
- **Out of scope:** the poll-loop blocker, which stays in claude-prefs.
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
