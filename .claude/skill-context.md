# skill-context — techne

Repo-specific facts for canonical techne skills. Most skills load this via a
load-time `` !`cat .claude/skill-context.md` `` injection; docsync reads it from
the target doc's repo root instead (it audits docs in other repos). This is the meta-repo — the
skills shipped here run against sister repos; running them inside this repo
audits the skill collection itself.

## repo

- name: techne
- package_root: `plugins/techne/skills/` (10 skills as `SKILL.md` + supporting markdown), `plugins/techne/_shared/` (canonical glossaries shared across skills), `superpowers/` (plans + specs), `scripts/` (validation helpers)
- language: Markdown (skill bodies) + Python (validation snippets in workflows) + Bash (structural-check scripts)
- cli_entrypoint: none — skills are invoked from the consumer's Claude Code via `/plugin install techne@techne` then `/techne:<skill>`. The repo itself is `package = false` in `pyproject.toml`.
- runner_module: no Python runner; CI gates run inline in `.github/workflows/validate.yml`.
- default_branch: `main`
- has: 10 skills (`audit`, `auto-commit`, `ci-audit`, `deslop`, `docs-site`, `docsync`, `research-grounded`, `reslop`, `sisters`, `theoros`), plugin manifest at `plugins/techne/.claude-plugin/plugin.json`, marketplace manifest at `.claude-plugin/marketplace.json`, Zensical-powered docs site, no docker, no frontend

## audit

Audit drives the wrapper `make` targets, which mirror `.github/workflows/validate.yml` + `docs.yml`:

### Phase 1 — Setup

1. `make check-env` — confirm `uv` + `jq` + `shellcheck` are on PATH (hard prereqs).
2. `make setup` — `uv sync` pulls the `[dependency-groups.dev]` set (`ruff>=0.9` + `zensical>=0.0.24`).

### Phase 2 — Manifest validation

3. `make manifests` — `jq empty` on `.claude-plugin/marketplace.json` + `plugins/techne/.claude-plugin/plugin.json`.

### Phase 3 — Skill structural validation

4. `make frontmatter` — `validate_skill_frontmatter.py` (every `plugins/techne/skills/*/SKILL.md` has well-formed `name:` + `description:`) + `check_theoros_skill.sh` (theoros-specific section + README cross-reference checks).

### Phase 4 — Lint

5. `make lint` — `ruff check scripts/` + `ruff format --check scripts/`. Narrow scope today; the validator script is the only tracked Python.
6. `make shellcheck` — `shellcheck --severity=warning scripts/*.sh`. Catches real bugs in `dev-runner.sh` + `check_theoros_skill.sh`. ubuntu-latest ships shellcheck.
7. `make guards` — grep guards: no `.claude/skills/_shared` references, no legacy `aj-*` skill names.

### Phase 5 — Docs site smoke

8. `make build` — `zensical build --strict --clean`. Strict-mode catches broken internal links + missing nav targets; mirrors `docs.yml`'s deploy job.

### End-to-end rollups

9. `make validate` — `lint + shellcheck + test` (where `test` = manifests + frontmatter + guards). Fast pre-push gate.
10. `make ci` — `setup + validate + build`. Mirrors validate.yml + docs.yml in one shot.

Fast audit = `make setup → make validate`. Stop-early phase: `check-env` / `setup` — any missing tool or sync failure blocks the rest.

Do-not-run targets:

- `make docs` — `zensical serve` (interactive local docs server)

Log archives: techne's Makefile does not call `scripts/dev-runner.sh` from inside its own recipes (per the "wrap from outside" rule the convention itself documents). For archived runs of any target, invoke `./scripts/dev-runner.sh <target>` externally.

## ci_audit

Referenced configs a CI failure can trace to:

- `pyproject.toml` (`requires-python`, `[tool.ruff]`, dev-deps)
- `Makefile` (wrapper-target canonical pipeline; mirrors validate.yml + docs.yml)
- `.claude-plugin/marketplace.json`, `plugins/techne/.claude-plugin/plugin.json`
- `plugins/techne/skills/*/SKILL.md` frontmatter (every skill)
- `scripts/validate_skill_frontmatter.py` (the frontmatter validator)
- `scripts/check_theoros_skill.sh` (theoros structural check)
- `.github/workflows/validate.yml` (structural CI)
- `.github/workflows/docs.yml` (docs deploy)
- `zensical.toml` (docs site config + nav)

Tool error markers (extend the default grep set):

- `jq` (manifest JSON parse errors)
- `missing frontmatter`, `missing name:`, `missing description:` (from `validate_skill_frontmatter.py`)
- `ruff` (Python lint failures in `scripts/`)
- `shellcheck` (bash script issues in `scripts/`)
- `zensical` (docs build errors — usually broken internal links from the strict mode)

Expected external PR checks: `validate` (in-repo) + `GitGuardian Security Checks` (org-level secret scanner, configured outside this repo's workflows). No codecov.

## slop_ground_truth

Source of truth for skill-level claims:

- **Skill descriptions:** `plugins/techne/skills/<name>/SKILL.md` frontmatter `description:` field is the canonical one-line summary surfaced in the plugin registry; README and `docs/skills/*.md` cross-references must match.
- **Marketplace metadata:** `.claude-plugin/marketplace.json` lists each skill; the descriptions there must align with the SKILL.md frontmatter.
- **Skill count:** `find plugins/techne/skills -mindepth 1 -maxdepth 1 -type d | wc -l` is the canonical count. Count + skill-list claims in README, ROADMAP, IMPL, **and this file** (e.g. "10 skills") must all trace here — adding a skill touches every one.

Any quantitative or list-shape claim not traceable to one of those is slop.

## scan_scope

Skip paths:

- `.venv/`, `node_modules/`, `dist/`, `build/`, `site/`, `out/`
- `__pycache__/`, `.ruff_cache/`, `.pytest_cache/`, `.cache/`
- `uv.lock`
- `superpowers/` (vendored upstream content — out of scope for slop / drift sweeps that target ajbarea's own prose)

Subagent scan-area split:

- Skills: `plugins/techne/skills/**/SKILL.md` + sibling markdown files (templates, references)
- Shared resources: `plugins/techne/_shared/**/*.md` (slop glossary, etc.)
- Scripts: `scripts/*.sh`
- Config / build: `pyproject.toml`, `.claude-plugin/marketplace.json`, `plugins/techne/.claude-plugin/plugin.json`, `.github/workflows/**`, `zensical.toml`
- Docs: `docs/**/*.md`, `README.md`

## docs_site

- config: `zensical.toml`
- workflow: `.github/workflows/docs.yml`
- css_files: `docs/stylesheets/`
- js_files: `docs/javascripts/`
- build_command: `uv run zensical build --clean`
- site_url: `https://ajbarea.github.io/techne/`
- action_pins (expected current, 2026-05): `actions/checkout@v6.0.2`, `astral-sh/setup-uv@v8.1.0`, `actions/setup-python@v6.2.0`, `actions/configure-pages@v6.0.0`, `actions/upload-pages-artifact@v5.0.0`, `actions/deploy-pages@v5.0.0`
- nav structure: per-skill docs under `docs/skills/`, plus top-level Getting Started / Configuration / Conventions / Examples / Architecture pages

## meta_repo_caveat

This repo is the **source** of the techne skills that ship to the other sisters. When `/techne:sisters` runs, it reads the consumer-side `.claude/skill-context.md` from each linked repo — including this one. The recursion is intentional: techne is a self-hosted sister so structural drift in its own skill collection (renamed SKILL.md frontmatter, deleted skill directories, stale marketplace.json) gets caught the same way it catches drift elsewhere.

When editing skills inside `plugins/techne/skills/`, remember the consumer-side cache lives at `~/.claude/plugins/cache/techne/techne/<sha>/skills/` — `/plugin update techne@techne` from inside Claude Code re-installs after a publish.
