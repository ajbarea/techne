---
description: "The conventions techne skills assume: Makefile targets, the dev-runner log archive, skill-context.md sections, COMMITS.md, the docs workflow and SHA-pinned actions."
---

# Conventions

Techne is opinionated. The skills assume a few conventions about how your repo is wired. This guide names them and shows the minimum each skill needs to work.

Each section flags which skill(s) depend on it. A repo can adopt only what it uses.

## The Makefile pattern

Techne's skills invoke your toolchain through `make` targets, not through raw tool commands. Wrap your build, lint, test, and check pipelines behind one-word targets so the same skill works against any stack (uv, npm, cargo, just, raw shell).

### Canonical target vocabulary

`techne:audit` runs whichever targets your `## audit` section lists under `phases`. The skill-context template starts with `setup`, `lint`, `test` and `ci`. Repos that have adopted techne in production share this wider set; lean on these names when they fit so cross-repo audits see one shape:

| Target      | Purpose                                                       |
| ----------- | ------------------------------------------------------------- |
| `setup`     | Install dependencies (uv sync / npm ci / cargo fetch / ...)   |
| `fix`       | Run every auto-fixer; one-way door, no check pass             |
| `lint`      | Format + lint check (no auto-fix)                             |
| `test-unit` | Unit tests only (fast feedback)                               |
| `test`      | Full test suite                                               |
| `build`     | Produce the deployable artifact                               |
| `validate`  | Fast pre-push gate (typically `lint test-unit build`)         |
| `ci`        | Mirror CI end-to-end                                          |
| `audit`     | Security audit (pip-audit / npm audit / cargo audit)          |
| `clean`     | Remove build artifacts and caches                             |
| `docs`      | Serve docs site locally (mark `do_not_run` for `techne:audit`)|
| `dev`       | Start dev server (mark `do_not_run` for `techne:audit`)       |
| `help`      | Show available targets                                        |

### Self-documenting help

Add a `## description` comment after each target name. A single grep+awk help target then renders the list at runtime, so every Makefile is its own README:

```makefile
help:                   ## Show this help
	@grep -hE '^[a-zA-Z][a-zA-Z0-9_-]*:.*?##' $(MAKEFILE_LIST) \
		| sort \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'
```

Set `.DEFAULT_GOAL := help` so a bare `make` invocation surfaces the menu.

### Starter template

Techne ships a polyglot starter at `templates/Makefile.example`. Pull it into a new repo:

```bash
curl -fsSL https://raw.githubusercontent.com/ajbarea/techne/main/templates/Makefile.example \
  -o Makefile
```

Each command target (all but `validate`, `ci` and `help`) is a `TODO` stub that exits 1 until replaced. `validate` and `ci` only depend on other targets. Copy the matching invocation from the inline cheat-sheet (uv / npm / cargo / pnpm) and delete the targets that don't apply.

For archived runs that `techne:audit` reconciles, wrap `make` from outside via `./scripts/dev-runner.sh <target>`. Do not call `dev-runner.sh` from inside a Makefile recipe; it invokes `make` and would recurse.

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

Techne ships `scripts/dev-runner.sh` as a reference implementation. Each run also points `logs/dev-latest.log` at the newest output; the runner truncates it every run, and `techne:audit` never reads it and its glob skips it. Pull the script into your repo:

```bash
mkdir -p scripts
curl -fsSL https://raw.githubusercontent.com/ajbarea/techne/main/scripts/dev-runner.sh \
  -o scripts/dev-runner.sh
chmod +x scripts/dev-runner.sh
```

Then invoke it from the shell, never from a Makefile recipe (it runs `make` itself, so the recipe would recurse):

```bash
./scripts/dev-runner.sh lint
```

Above the `SUMMARY` block, each output line is tagged `[<time>] [OUT  ] [<target>] <line>`, and a failing run adds `[<time>] [ERROR] [<target>] exit <rc>`. That is the same shape a Python `scripts/dev.py` runner writes, so `techne:audit` reads either.

**Required for:** `techne:audit`.

## `.claude/skill-context.md` (per-repo skill config)

Several skills read a single per-repo file at `.claude/skill-context.md`. They read it from the current directory's git root when they load, headed by that root's path. A skill pointed at a path in another repo re-reads it from that repo with `_shared/skill_context.sh <target>`. The skeleton ships with the techne plugin as [`skill-context.template.md`](https://github.com/ajbarea/techne/blob/main/plugins/techne/skills/setup/skill-context.template.md). `/techne:setup` offers to copy it into a repo that has none. Keep the sections for the skills you use and delete the rest.

Each `##` section maps to one skill family. Adopt only the sections for the skills you intend to use. A skill whose section is absent either stops and points you to `/techne:setup` (`audit`, `theoros`) or falls back to generic defaults (`docs-site`, `deslop`, `reslop`, `elenchus`, `latex`, `paper-review`).

### Section reference

The [template](https://github.com/ajbarea/techne/blob/main/plugins/techne/skills/setup/skill-context.template.md) shows every key with a placeholder.

| Section | Read by | Keys |
|---|---|---|
| `## repo` | `docsync` | One paragraph on what the repo is, its CLI entrypoint and runner module. |
| `## audit` | `audit` | `phases` (targets in dependency order), `fast_subset`, `stop_early`, `log_archive_glob`, `do_not_run`. |
| `## ci_audit` | `ci-audit` | `referenced_configs` (files whose edit changes CI output), `tool_error_markers`. |
| `## slop_ground_truth` | `deslop`, `reslop`, `docsync` | `authoritative_sources`, `test_locations`: what a claim is checked against. |
| `## scan_scope` | `deslop` | `skip` paths and `areas` (how a wide scan is split). |
| `## docs_site` | `docs-site` | `config`, `workflow`, `css_files`, `js_files`, `build_command`, `site_url`, `action_pins`. |
| `## theoros` | `theoros` | `repl_command`, `session_name`, optional `ops_command` for a log pane. |
| `## paper` | `paper` | `author`, `affiliation`, `email`, `bib`, `portfolio`. |
| `## paper-review` | `paper-review` | `lab_line`, `retrieval`, `mailto`, `report`. |
| `## latex` | `latex` | `markers`, `overfull_pt`, `engine`. |
| `## elenchus` | `elenchus` | `test_command`, `run_command`, `destructive_ops`, `load_bearing_surfaces`, `feature_works_means`; each is optional and sharpens one phase. |

**Required for:** `techne:audit`, `techne:theoros`.
**Recommended for:** `techne:sisters` (used for cross-repo skill-context parity checks), `techne:deslop`, `techne:reslop`, `techne:docsync`, `techne:docs-site`, `techne:ci-audit`, `graphe:paper` and `graphe:paper-review` (defaults work; the `## paper` and `## paper-review` blocks set author, bibliography and lab-overlap details), `graphe:latex` (defaults work with no config; the `## latex` block sets per-repo draft markers and thresholds), `techne:elenchus` (tier-0 works with no config; the `## elenchus` block sharpens each phase).

## `~/.claude/techne.toml` (user-level sister config)

`techne:sisters` reads a user-level config file at `~/.claude/techne.toml` that lists the repos to audit drift across. See [Configuration](configuration.md) for the schema and a worked example.

**Required for:** `techne:sisters`.

## `COMMITS.md` (local commit draft)

`techne:auto-commit` writes a draft commit plan to `COMMITS.md` in your repo root. Gitignore it:

```
# techne:auto-commit local scratchpad
COMMITS.md
```

The file is intentionally local-only. The skill regenerates it when the tree has changed since the plan and leaves it alone while it is still current, keeps a `## Notes` section, and deletes it after the PR is opened.

**Required for:** `techne:auto-commit`.

## The docs-site workflow

`techne:docs-site` manages a Zensical-built GitHub Pages workflow. Techne ships a reference workflow at `.github-template/workflows/docs.yml`. Pull it into your repo:

```bash
mkdir -p .github/workflows
curl -fsSL https://raw.githubusercontent.com/ajbarea/techne/main/.github-template/workflows/docs.yml \
  -o .github/workflows/docs.yml
```

Then enable Pages in your GitHub repo settings (Settings -> Pages -> Source: GitHub Actions). The workflow runs on pushes to `main` that touch the docs, its config or the workflow itself, and on manual dispatch.

Its actions are pinned to the same commit SHAs as techne's own `docs.yml`, and `make guards` fails if the two drift apart. Dependabot only watches `.github/workflows/`, so after copying, your repo's Dependabot keeps the pins fresh.

**Required for:** `techne:docs-site`.

## Dependabot

Techne ships `templates/dependabot.yml.example`, the canonical Dependabot config that `techne:sisters` checks every repo against (check 11). Copy it to `.github/dependabot.yml` and keep the ecosystems your repo uses.

## Pinning GitHub Actions to commit SHAs

Every remote `uses:` reference in `.github/workflows/` is pinned to a full
40-character commit SHA, with the human-readable tag kept as a trailing comment:

```yaml
- uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
```

Git tags are mutable; anyone with write access to an action's repo can repoint a
tag at a malicious commit. The tj-actions/changed-files compromise (2025-03, ~23k
repos) rewrote every tag to exfiltrate CI secrets. A commit SHA is immutable, so a
SHA-pinned workflow runs exactly the code you reviewed.

- **Generate the pins** with [`pinact run`](https://github.com/suzuki-shunsuke/pinact).
  It resolves each tag to its SHA and appends the `# tag` comment.
- **Stay fresh** with Dependabot's `github-actions` *version* updates, which bump
  both the SHA and the comment. GitHub emits Dependabot *security alerts* only for
  semver-pinned actions, so SHA-pinning trades the (rarely-firing) actions-CVE alert
  for tag-mutation immunity (the version-update PRs are GitHub's recommended
  companion). A `cooldown` (e.g. `default-days: 7`) holds a freshly-published release
  before the bump PR lands. research(2026-05): GitHub Docs "Secure use reference";
  CNCF "Securing GitHub Actions CI dependencies" recipe (2026-05-04).
- **Keep it pinned** with `make guards` (`scripts/check_action_pins.sh`), which fails
  the build if any remote `uses:` ref is not a full SHA. Local (`./…`) and
  `docker://…` refs are exempt. A workflow a skill ships as a template (under
  `plugins/*/skills/*/templates/`) must also pin each action at a SHA a live workflow
  uses. Dependabot updates both when the template's folder is listed in
  `.github/dependabot.yml`; the guard fails when the two drift apart.

**Enforced by:** `make guards` (techne dogfoods this in its own `validate.yml`).
**Audited by:** `techne:sisters` (action-pin consistency across the fleet).

## Adopting incrementally

You don't need all conventions at once. Common starting points:

- **Just want commit drafting?** Adopt the `COMMITS.md` gitignore line. That's it.
- **Want the audit pipeline?** Adopt the Makefile pattern + `scripts/dev-runner.sh` + the `## audit` section of skill-context.md.
- **Want cross-repo drift checks?** Adopt `~/.claude/techne.toml`. Sisters works without skill-context.md.
- **Want the full kit?** Adopt all conventions and the docs site workflow.
