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

### 2026-05-23 — Drop system tool deps in Makefile + CI

**Why.** `make test` failed in clean WSL because `manifests` required `jq`
and `shellcheck` was a separate system install. AJ's environment has
neither. The sister-template Makefile inherited the same brittleness, so
every consumer sister hit the same wall.

**Decisions.**
- Replace `jq empty` with `python3 -m json.tool` — Python stdlib, already
  required by `uv`-driven targets; zero new deps.
- Replace system `shellcheck` with the `shellcheck-py` PyPI package — ships
  a vendored binary, installable via `uv sync`, identical CLI surface.
- CI workflow drops inline `jq`/`shellcheck` steps and dogfoods `make`
  targets instead — eliminates local-vs-CI drift, makes the Makefile the
  single source of truth for what "validate" means.

**Definition of done.**
- `make ci` runs end-to-end in WSL without any apt-installed deps. ✓
- `validate.yml` calls `make setup` / `make lint` / `make shellcheck` /
  `make test` instead of inline scripts. ✓
- `check-env` no longer enforces `jq` / system `shellcheck`. ✓
- No other sister Makefile uses `jq` (audited 2026-05-23); template
  (`templates/Makefile.example`) is placeholder-only, no fix needed.

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
