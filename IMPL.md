# techne — Implementation scratchpad

The active TODO list for whatever's in flight **right now** — current
PR, open design question blocking me, immediate next pickup. Queued
specs, cross-skill themes, and "next up" ordering live in
[ROADMAP.md](./ROADMAP.md). Git history is the permanent record of
how each skill was designed.

If this file is more than ~50 lines, something queued or referential
has crept in — extract it back to ROADMAP.

## In flight

**v1.0.0 release polish** (branch `docs/release-polish`).

- **Why:** a file-by-file pass before the first release found the docs underselling the
  skill set and several skill texts contradicting the fleet's own conventions.
- **Decisions:** the plugin stays unversioned, so installs follow the commit SHA and every
  push reaches users. `# research(2026-09)`: code.claude.com plugin-marketplaces, "if you
  omit `version`, Claude Code uses the source's resolved commit SHA"; setting `version`
  pins users until a bump. Releases are plain `vX.Y.Z` git tags plus a GitHub release,
  for citation. `{name}--vX.Y.Z` tags exist for dependency ranges, which techne has none of.
  Bundled scripts are addressed as `${CLAUDE_SKILL_DIR}/scripts/…` (the documented
  variable; confirmed substituted in Claude Code 2.1.274).
- **Scope:** every skill listed everywhere; `dev-runner.sh` writes the `[OUT  ]` / `[ERROR]`
  lines `techne:audit` reads; starter docs workflow SHA-pinned and guarded against the live
  pins; skill-context facts; `CITATION.cff` version and date.
- **Out of scope:** a Zenodo DOI (needs the Zenodo GitHub integration switched on first).
- **Done when:** `make validate` green, CI green, merged, `v1.0.0` tagged and released.

## Skill collection state

Shipped skills by catalog dimension (the directory listing of `plugins/techne/skills/` is the source of truth):

| Dimension | Skills |
| --- | --- |
| **Audit** | `audit`, `ci-audit` |
| **Drift** | `docsync`, `docs-site`, `research-grounded`, `sisters` |
| **Hygiene** | `auto-commit`, `deslop`, `reslop` |
| **Review** | `catchup`, `elenchus` |
| **Observation** | `theoros` |
| **Document build** | `latex`, `pdf`, `paper`, `paper-review` |

When picking up the next session, replace the "In flight" block above
with a full session plan (Why / Decisions / Scope / Out of scope /
Definition of done) following the same template every other sister
uses.
