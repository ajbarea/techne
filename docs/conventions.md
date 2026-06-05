# Conventions

Techne is opinionated. The skills assume a few conventions about how your repo is wired. This guide names them and shows the minimum each skill needs to work.

Each section flags which skill(s) depend on it. A repo can adopt only what it uses.

## The Makefile pattern

Techne's skills invoke your toolchain through `make` targets, not through raw tool commands. Wrap your build, lint, test, and check pipelines behind one-word targets so the same skill works against any stack (uv, npm, cargo, just, raw shell).

### Canonical target vocabulary

The four required targets are `setup`, `lint`, `test`, `ci`. Repos that have adopted techne in production also share this richer set; lean on these names when they fit so cross-repo audits see one shape:

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

Each target body is a `TODO` stub that exits 1 until replaced. Copy the matching invocation from the inline cheat-sheet (uv / npm / cargo / pnpm) and delete the targets that don't apply.

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

## audit
phases:
  - setup
  - lint
  - test
  - ci
fast_subset: [lint, test]
stop_early: [setup]
log_archive_glob: "logs/dev-*-{phase}.log"
do_not_run: []

## ci_audit
workflows_path: ".github/workflows"
ignore_warnings: []

## slop_ground_truth
authoritative_sources:
  - "src/"
  - "tests/"
test_locations:
  - "tests/"

## scan_scope
include:
  - "src/"
  - "docs/"
exclude:
  - "site/"
  - ".venv/"

## docs_site
config: "zensical.toml"
deploy_workflow: ".github/workflows/docs.yml"
build_command: "uv run --group dev zensical build --clean"

## theoros
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

## Pinning GitHub Actions to commit SHAs

Every remote `uses:` reference in `.github/workflows/` is pinned to a full
40-character commit SHA, with the human-readable tag kept as a trailing comment:

```yaml
- uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd # v6.0.2
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
  `docker://…` refs are exempt.

**Enforced by:** `make guards` (techne dogfoods this in its own `validate.yml`).
**Audited by:** `techne:sisters` (action-pin consistency across the fleet).

## Adopting incrementally

You don't need all conventions at once. Common starting points:

- **Just want commit drafting?** Adopt the `COMMITS.md` gitignore line. That's it.
- **Want the audit pipeline?** Adopt the Makefile pattern + `scripts/dev-runner.sh` + the `## audit` section of skill-context.md.
- **Want cross-repo drift checks?** Adopt `~/.claude/techne.toml`. Sisters works without skill-context.md.
- **Want the full kit?** Adopt all conventions and the docs site workflow.
