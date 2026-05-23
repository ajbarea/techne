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

### 2026-05-23 — Sisters audit: branch-protection drift detection

**Why.** Today's audit found ldqis was the only sister without branch
protection on `main`. The sisters skill currently checks merge settings
+ auto-merge but never inspects branch protection — the wrong PR could
slip through unguarded. Out-of-band fix applied (5 required checks
enabled on ldqis matching the CI workflow names).

**Decisions.**
- Add check 8 (new section) before the existing codecov check (renumbered
  to 9). Don't pin a specific number of required contexts — that varies
  by repo's CI shape — just verify ≥1 wired and that `allow_force_pushes`
  / `allow_deletions` are blocked.
- `enforce_admins` stays optional. AJ intentionally leaves admin override
  on so audit fixes can ship the same session.
- Sample report block updated to show the new section after Local main sync.

**Definition of done.**
- New check 8 wired with the bash recipe + python parser. ✓
- Existing codecov check renumbers to 9. ✓
- Output-format example shows pass + drift cases inline. ✓
- Smoke-tested across all 6 sisters: all now pass (ldqis was the
  drifted one; out-of-band fix already applied). ✓
- `make ci` green.

### 2026-05-23 — Sisters audit: codecov.yml drift detection

**Why.** Today's audit + PR #10 (ldqis codecov upload) surfaced that ldqis
was the only codecov-using sister without a `codecov.yml`. Without the
config, the Codecov bot posts an inline PR comment on every push — pure
noise once the patch-coverage status check is visible. The merge-settings
+ skill-context checks didn't catch this because codecov config sits
*outside* the GitHub-API-discoverable surface.

**Decisions.**
- Add audit check 8: any sister whose `.github/workflows/` invokes
  `codecov/codecov-action` should carry a `codecov.yml` or `.codecov.yml`
  at the repo root with `comment: false`.
- Conditional check: sisters not using codecov-action are silently
  skipped. No false positives for ajbarea.github.io / techne (no
  codecov-action).
- Sample report block updated to show the success and drift cases inline.

**Definition of done.**
- SKILL.md gains check 8 with the bash recipe. ✓
- Output-format example shows the conditional-pass + drift case. ✓
- Smoke-tested across all 6 sisters: 4 codecov-users pass, 2 non-users
  skip cleanly. ✓
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
