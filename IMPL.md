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

### 2026-05-23 — Sisters audit: `allow_auto_merge` drift detection

**Why.** A cross-sister auto-merge audit run on 2026-05-23 found that 5 of 6
sisters had `allow_auto_merge=false`. The setting is required for
`gh pr merge --auto` to queue PRs for hands-off merge on green CI; without
it every PR has to be hand-merged after the last check flips. The
`techne:sisters` audit didn't surface this drift because the merge-settings
check only looked at squash / merge_commit / rebase / delete_branch.

**Decisions.**
- Add `allow_auto_merge: true` to the canonical merge-settings pin.
- Extend the audit query to surface the new field.
- Update the sample report format so the recommended remediation is
  visible inline (one-liner `gh api -X PATCH ... -f allow_auto_merge=true`).
- All 5 drifted sisters were auto-fixed in the same audit run (out-of-band,
  before this PR was opened).

**Definition of done.**
- SKILL.md canonical-settings list includes `allow_auto_merge`. ✓
- Audit query extracts the field. ✓
- Sample output illustrates the drift case + remediation. ✓
- `make ci` green. ✓

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
