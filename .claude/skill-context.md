# skill-context — techne

Repo-specific facts for canonical techne skills. Injected into each skill at
invocation via `!cat .claude/skill-context.md`. This is the meta-repo — the
skills shipped here run against sister repos; running them inside this repo
audits the skill collection itself.

## repo

- name: techne
- package_root: `plugins/techne/skills/` (9 skills as `SKILL.md` + supporting markdown), `plugins/techne/_shared/` (canonical glossaries shared across skills), `superpowers/` (plans + specs), `scripts/` (validation helpers)
- language: Markdown (skill bodies) + Python (validation snippets in workflows) + Bash (structural-check scripts)
- cli_entrypoint: none — skills are invoked from the consumer's Claude Code via `/plugin install techne@techne` then `/techne:<skill>`. The repo itself is `package = false` in `pyproject.toml`.
- runner_module: no Python runner; CI gates run inline in `.github/workflows/validate.yml`.
- default_branch: `main`
- has: 9 skills (`audit`, `auto-commit`, `ci-audit`, `deslop`, `docs-site`, `docsync`, `reslop`, `sisters`, `theoros`), plugin manifest at `plugins/techne/.claude-plugin/plugin.json`, marketplace manifest at `.claude-plugin/marketplace.json`, Zensical-powered docs site, no docker, no frontend

## audit

No `make` wrapper — validation runs as inline workflow steps. Mirrors the structure of `validate.yml` for hand-reproduction:

### Phase 1 — Setup

1. `uv sync` — pulls the `[dependency-groups.dev]` set (`ruff>=0.9` + `zensical>=0.0.24`).

### Phase 2 — Manifest validation

2. `jq empty .claude-plugin/marketplace.json` — marketplace JSON parses.
3. `jq empty plugins/techne/.claude-plugin/plugin.json` — plugin JSON parses.

### Phase 3 — Skill structural validation

4. `uv run python scripts/validate_skill_frontmatter.py` — every `plugins/techne/skills/*/SKILL.md` has well-formed frontmatter with `name:` and `description:`. (Previously inline in `validate.yml`; extracted so the check is testable and reusable.)
5. `bash scripts/check_theoros_skill.sh` — theoros-specific structural check (the only skill with bespoke validation today; the script doubles as a template for adding bespoke checks for future skills).

### Phase 4 — Lint

6. `uv run ruff check scripts/` + `uv run ruff format --check scripts/` — narrow scope today (just the validator script). Extend selection as more Python lands.
7. `shellcheck scripts/*.sh` — catches real bugs in `dev-runner.sh` + `check_theoros_skill.sh`. `ubuntu-latest` ships shellcheck so no install step.

### Phase 5 — Docs site smoke

8. `uv run zensical build --strict --clean` — strict-mode build catches broken internal links + missing nav targets.

Fast audit = `uv sync → jq manifests → validate_skill_frontmatter.py → ruff → shellcheck → zensical build --strict`. Six steps.

Stop-early phase: any manifest parse failure or missing frontmatter blocks the rest — the plugin won't install at the consumer side.

Do-not-run targets: none specific to this repo. (`uv run zensical serve` is interactive and out of scope for automated audit.)

## ci_audit

Referenced configs a CI failure can trace to:

- `pyproject.toml` (`requires-python`, `[tool.ruff]`, dev-deps)
- `.claude-plugin/marketplace.json`, `plugins/techne/.claude-plugin/plugin.json`
- `plugins/techne/skills/*/SKILL.md` frontmatter (every skill)
- `scripts/validate_skill_frontmatter.py` (the frontmatter validator)
- `.github/workflows/validate.yml` (structural CI)
- `.github/workflows/docs.yml` (docs deploy)
- `zensical.toml` (docs site config + nav)

Tool error markers (extend the default grep set):

- `jq` (manifest JSON parse errors)
- `missing frontmatter`, `missing name:`, `missing description:` (from `validate_skill_frontmatter.py`)
- `ruff` (Python lint failures in `scripts/`)
- `shellcheck` (bash script issues in `scripts/`)
- `zensical` (docs build errors — usually broken internal links from the strict mode)

Expected external PR checks: none beyond `validate` + `docs` (no codecov, no GitGuardian configured today). Worth filing whether to add GitGuardian for parity with the other sisters.

## slop_ground_truth

Source of truth for skill-level claims:

- **Skill descriptions:** `plugins/techne/skills/<name>/SKILL.md` frontmatter `description:` field is the canonical one-line summary surfaced in the plugin registry; README and `docs/skills/*.md` cross-references must match.
- **Marketplace metadata:** `.claude-plugin/marketplace.json` lists each skill; the descriptions there must align with the SKILL.md frontmatter.
- **Skill count:** `find plugins/techne/skills -mindepth 1 -maxdepth 1 -type d | wc -l` is the canonical count. README + docs claims about "9 skills" or similar must trace here.

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
