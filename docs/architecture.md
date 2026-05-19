# Architecture

Techne is a collection of independent, composable skills that share conventions but don't hard-depend on each other. This page maps the skill ecosystem, names the typical workflows, and states the design philosophy.

## Skill categories

**Build and toolchain.** `techne:audit` validates that your local build is clean (lint, test, end-to-end) by walking your Makefile dependency graph and diffing terminal output against per-invocation log archives. `techne:ci-audit` does the same for GitHub Actions runs; flags warnings, deprecations, and noise; fixes what's fixable in-repo (workflow YAML, action pins, dependency versions).

**Documentation and prose.** `techne:docs-site` maintains the Zensical-built Pages workflow, link integrity, and asset hygiene. `techne:docsync` verifies prose claims (CLI commands, paths, signatures, config keys) against the actual codebase. `techne:deslop` flags AI-generated slop in comments and docstrings; `techne:reslop` rewrites docstrings grounded in the implementation rather than deleting them outright.

**Versioning and observability.** `techne:auto-commit` groups working-tree changes into a structured commit plan at `COMMITS.md` for staged review before anything lands. `techne:theoros` starts an observed live dev session in a tmux pane; Claude drives the REPL, the human spectates read-only via `tmux attach -r`.

**Cross-repo consistency.** `techne:sisters` audits drift across the repos listed in `~/.claude/techne.toml`: CI action pins, toolchain pins, skill-context structural parity, GitHub merge settings, open PRs, branch hygiene. Read-only; reports findings, leaves fixes to follow-up work.

## Typical workflows

**Pre-push validation.** Group local changes with `techne:auto-commit`, validate the build with `techne:audit`, scan for prose slop with `techne:deslop`, push. When CI finishes, run `techne:ci-audit` against the run for warnings and deprecations.

**Documentation accuracy.** After a refactor, run `techne:docsync` to find stale claims. Review the drift report; rewrite affected docstrings with `techne:reslop` if rewrite is preferable to deletion. Run `techne:docs-site` to confirm link integrity hasn't regressed.

**Multi-repo release.** Run `techne:sisters` to surface CI/toolchain/branch drift across the linked repos. Fix the drift in each repo (action pins, Python versions, merge settings). Validate each with `techne:audit`. Coordinate merges in consistent order.

**Observed session.** For long-running tasks (multi-hour test suites, large refactors), spin up a tmux session with `techne:theoros`. Share the session name; collaborators attach read-only with `tmux attach -r -t <session>`. The transcript persists in tmux scrollback.

## Design philosophy

Skills are independent; each invocable without the others; but share conventions: `.claude/skill-context.md` for per-repo config, `~/.claude/techne.toml` for user-level config, the dev-runner log archive at `logs/dev-*.log`. Every skill writes a plan, report, or diff to disk first, then waits for human review before mutating the repo. Read-only audits plus explicit human approval; never silent edits. See [Conventions](conventions.md) for the standard file locations and adoption path.

## See also

- [Conventions](conventions.md): the standard file locations and adoption path
- [Examples](examples.md): concrete workflows using the skills together
- [Skills reference](skills/index.md): per-skill detail pages
