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

Each `##` section maps to one skill family. Adopt only the sections for the skills you intend to use. A skill whose section is absent either stops and points you to `/techne:setup` (`audit`, `theoros`) or falls back to generic defaults (`docs-site`, `deslop`, `reslop`, `elenchus`, `research-grounded`, `latex`, `paper-review`).

### Section reference

The [template](https://github.com/ajbarea/techne/blob/main/plugins/techne/skills/setup/skill-context.template.md) shows every key with a placeholder.

| Section | Read by | Keys |
|---|---|---|
| `## repo` | `docsync`, `audit`, `research-grounded`, `ci-audit` | One paragraph on what the repo is, its CLI entrypoint and runner module. Optional line `- owner: team`, in exactly that form, to make skills ask before acting (see [Solo and team repos](#solo-and-team-repos)). |
| `## audit` | `audit`, `elenchus` (its test command) | `phases` (targets in dependency order), `fast_subset`, `stop_early`, `log_archive_glob`, `do_not_run`. |
| `## ci_audit` | `ci-audit` | `referenced_configs` (files whose edit changes CI output), `tool_error_markers`. |
| `## slop_ground_truth` | `deslop`, `reslop`, `docsync` | `authoritative_sources`, `test_locations`: what a claim is checked against. |
| `## scan_scope` | `deslop` | `skip` paths, `areas` (how a wide scan is split), `pattern_sources` (files that quote slop on purpose). |
| `## docs_site` | `docs-site`, `sisters` | `config`, `workflow`, `css_files`, `js_files`, `build_command`, `site_url`, `action_pins`. |
| `## theoros` | `theoros`, `elenchus` (its run command) | `repl_command`, `session_name`, optional `ops_command` for a log pane. |
| `## paper` | `paper` | `author`, `affiliation`, `email`, `bib`, `portfolio`. |
| `## paper-review` | `paper-review` | `lab_line`, `retrieval`, `mailto`, `report`. |
| `## latex` | `latex` | `markers`, `overfull_pt`, `engine`. |
| `## research_grounded` | `research-grounded` | `decision_docs`: files, directories or globs audited in addition to `IMPL.md` and `ROADMAP.md`. |
| `## elenchus` | `elenchus` | `test_command`, `run_command`, `destructive_ops`, `load_bearing_surfaces`, `feature_works_means`; each is optional and sharpens one phase. |

**Required for:** `techne:audit`, `techne:theoros`.
**Recommended for:** `techne:sisters` (used for cross-repo skill-context parity checks), `techne:deslop`, `techne:reslop`, `techne:docsync`, `techne:docs-site`, `techne:ci-audit`, `graphe:paper` and `graphe:paper-review` (defaults work; the `## paper` and `## paper-review` blocks set author, bibliography and lab-overlap details), `graphe:latex` (defaults work with no config; the `## latex` block sets per-repo draft markers and thresholds), `techne:elenchus` (tier-0 works with no config; the `## elenchus` block sharpens each phase).

## `~/.claude/techne.toml` (user-level sister config)

`techne:sisters` reads a user-level config file at `~/.claude/techne.toml` that lists the repos to audit drift across. See [Configuration](configuration.md) for the schema and a worked example.

**Required for:** `techne:sisters`.

## Solo and team repos

`docsync` and `ci-audit` act on a solo repo and ask on a team repo. A solo repo is yours alone: nobody else can push to it or is invited to. People who send pull requests from their forks do not make it team, since their changes arrive through a PR you review. A fix the evidence settles is applied without a question there. A team repo has other people working in it, so the skill proposes and you choose. `_shared/repo_kind.py` decides, and only GitHub facts about you can make a repo solo: it is not in an organization, you administer it, nobody else can push, and it is not a fork of a live upstream unless its sister entry says `kind = "solo"`. Two signals can only make it team, and are checked first:

1. the line `- owner: team` under the `## repo` heading of the repo's `.claude/skill-context.md`, written exactly that way, in the working copy, the current commit or the default branch on GitHub, so a committed line reaches every collaborator. Any other line that could be an attempt at it also reads as team: `owner`, `owners` or `ownership` and `team` or `teams` on one line in another form or place (`**Owner:** team`, a commented-out marker, a sentence of prose), or an `owner:` key with nothing after it. The reason names the line number: write it as `- owner: team` to mark the repo team, or reword it so it is not taken for the marker;
2. `kind = "team"` (any case) on a `[[sisters]]` entry in `~/.claude/techne.toml` that matches the repo: by its path under `workspace_root`; for another clone, by an origin of `<github_user>/<name>`; or, when neither matches, by a team entry whose checkout under `workspace_root` has the same origin (a clone whose folder and GitHub names differ).

An `- owner: solo` line is not trusted on its own, since it is true only for its author. Anything unsettled, such as no GitHub origin, `gh` failing, a `techne.toml` that cannot be read, or a `skill-context.md` that is not a regular file or is over 1 MiB, is treated as team, so a skill never edits someone else's repo without asking. To see the answer and the reason for any repo or file, run `python3 <plugin-root>/_shared/repo_kind.py <path>`, where `<plugin-root>` is the installed techne plugin (`~/.claude/plugins/cache/techne/techne/<version>/`) or `plugins/techne` in a techne checkout. A fork you work on as your own line, never sending its changes upstream, needs `kind = "solo"` on its sister entry to count as solo. `techne:sisters` reads the roster `kind` on its own, for conventions only a solo repo follows (the README masthead); acting without asking always goes through these facts.

## `IMPL.md` and `ROADMAP.md` (working docs)

Both sit at the repo root and are committed. `ROADMAP.md` holds the long view and a dated log of what shipped. `IMPL.md` holds the work in flight: the current slice, what is done, what is next and how to verify it.

On a branch, `IMPL.md` is that branch's resume state. A session that starts in the worktree after a restart, `/clear` or compaction should be able to pick up from `IMPL.md`, `git log` and the working tree alone, without the conversation or Claude's memory, which is one file per project shared by every worktree and kept on one machine. So:

- Rewrite the branch's `IMPL.md` and push after each finished task, not only at the end.
- A session starting in a worktree reads `IMPL.md`, the commits past the default branch and the uncommitted diff before it acts.
- A branch whose `IMPL.md` is unchanged since it left the default branch has not said what it is for. Write it before the work grows.

`IMPL.md` on the default branch describes the last slice merged. research(2026-10): Anthropic, "Effective harnesses for long-running agents" (a progress file and the git log are what a fresh context window resumes from).

**Read by:** the techne plugin's `resume_brief` option, which adds this state as context at session start ([options](plugins/techne.md#options)).
**Audited by:** `techne:sisters`, which marks a dirty, idle worktree whose `IMPL.md` is unchanged since its branch left the default branch as not resumable.

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
- **Want sessions to pick up where the last one stopped?** Keep `IMPL.md` per branch and turn on `resume_brief`.
- **Want cross-repo drift checks?** Adopt `~/.claude/techne.toml`. Sisters works without skill-context.md.
- **Want the full kit?** Adopt all conventions and the docs site workflow.
