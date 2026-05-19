# Conventions

Techne is opinionated. The skills assume a few conventions about how your repo is wired. This guide names them and shows the minimum each skill needs to work.

Each section flags which skill(s) depend on it. A repo can adopt only what it uses.

## The Makefile pattern

Techne's skills invoke your toolchain through `make` targets, not through raw tool commands. Wrap your build, lint, test, and check pipelines behind one-word targets:

```makefile
.PHONY: setup lint test ci

setup:
	uv sync --group dev

lint:
	uv run ruff check .
	uv run ruff format --check .

test:
	uv run pytest

ci: lint test
```

The interface is stable across heterogeneous tools (uv, npm, cargo, just, raw shell), CI-friendly, and self-documenting via `make help` if you adopt one of the standard help patterns.

**Required for:** `techne:audit`.
**Recommended for:** `techne:ci-audit`, `techne:theoros`.

## The dev-runner archive

`techne:audit` doesn't run `make` directly; it diffs your terminal exit code against a per-invocation log archive. Each `make <target>` produces `logs/dev-<UTC-timestamp>-<target>.log` ending with a `SUMMARY` block:

```
==============================================================================
SUMMARY
==============================================================================
total elapsed : 3.96s
steps run     : 1
steps failed  : 0
overall rc    : 0

per-step:
  PASS  rc=0     3.93s  lint
==============================================================================
```

Techne ships `scripts/dev-runner.sh` as a reference implementation. Pull it into your repo:

```bash
mkdir -p scripts
curl -fsSL https://raw.githubusercontent.com/ajbarea/techne/main/scripts/dev-runner.sh \
  -o scripts/dev-runner.sh
chmod +x scripts/dev-runner.sh
```

Then call it from your Makefile targets (or invoke directly):

```makefile
lint:
	@./scripts/dev-runner.sh lint
```

**Required for:** `techne:audit`.

## `.claude/skill-context.md` (per-repo skill config)

Several skills read a single per-repo file at `.claude/skill-context.md`. This is the copy-pasteable skeleton:

````markdown
# Skill context

## repo
<one-paragraph description of what this repo is and who uses it>

## audit (techne:audit)
phases:
  - setup
  - lint
  - test
  - ci
fast_subset: [lint, test]
stop_early: [setup]
log_archive_glob: "logs/dev-*-{phase}.log"
do_not_run: []

## ci_audit (techne:ci-audit)
workflows_path: ".github/workflows"
ignore_warnings: []

## slop_ground_truth (techne:deslop / techne:reslop / techne:docsync)
authoritative_sources:
  - "src/"
  - "tests/"
test_locations:
  - "tests/"

## scan_scope (techne:deslop / techne:reslop)
include:
  - "src/"
  - "docs/"
exclude:
  - "site/"
  - ".venv/"

## docs_site (techne:docs-site)
config: "zensical.toml"
deploy_workflow: ".github/workflows/docs.yml"
build_command: "uv run --group dev zensical build --clean"

## theoros (techne:theoros)
```yaml
repl_command: <your repo's REPL command>
session_name: <your-repo-slug>-theoros
```
````

Each `##` section maps to one skill family. Adopt only the sections for the skills you intend to use; absent sections trigger a "skill needs scaffolding" message instead of a silent failure.

**Required for:** `techne:audit`, `techne:theoros`.
**Recommended for:** `techne:sisters` (used for cross-repo skill-context parity checks), `techne:deslop`, `techne:reslop`, `techne:docsync`, `techne:docs-site`, `techne:ci-audit`.

## `~/.claude/techne.toml` (user-level sister config)

`techne:sisters` reads a user-level config file at `~/.claude/techne.toml` that lists the repos to audit drift across. See the **Configuration** section of the README for the worked example.

**Required for:** `techne:sisters`.

## `COMMITS.md` (local commit draft)

`techne:auto-commit` writes a draft commit plan to `COMMITS.md` in your repo root. Gitignore it:

```
# techne:auto-commit local scratchpad
COMMITS.md
```

The file is intentionally local-only and is rewritten on every run.

**Required for:** `techne:auto-commit`.

## The docs-site workflow

`techne:docs-site` manages a Zensical-built GitHub Pages workflow. Techne ships a reference workflow at `.github-template/workflows/docs.yml`. Pull it into your repo:

```bash
mkdir -p .github/workflows
curl -fsSL https://raw.githubusercontent.com/ajbarea/techne/main/.github-template/workflows/docs.yml \
  -o .github/workflows/docs.yml
```

Then enable Pages in your GitHub repo settings (Settings -> Pages -> Source: GitHub Actions). The workflow runs on every push to `main` and on manual dispatch.

**Required for:** `techne:docs-site`.

## Adopting incrementally

You don't need all conventions at once. Common starting points:

- **Just want commit drafting?** Adopt the `COMMITS.md` gitignore line. That's it.
- **Want the audit pipeline?** Adopt the Makefile pattern + `scripts/dev-runner.sh` + the `## audit` section of skill-context.md.
- **Want cross-repo drift checks?** Adopt `~/.claude/techne.toml`. Sisters works without skill-context.md.
- **Want the full kit?** Adopt all conventions and the docs site workflow.
