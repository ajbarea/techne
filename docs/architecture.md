# Architecture

Techne is a collection of independent, composable skills that share conventions but don't hard-depend on each other. This page maps the skill ecosystem, names the typical workflows, and states the design philosophy.

## Skill categories

**Build and toolchain.** `techne:audit` validates that your local build is clean (lint, test, end-to-end) by walking your Makefile dependency graph and diffing terminal output against per-invocation log archives. `techne:ci-audit` does the same for GitHub Actions runs; flags warnings, deprecations, and noise; fixes what's fixable in-repo (workflow YAML, action pins, dependency versions).

**Documentation and prose.** `techne:docs-site` maintains the Zensical-built Pages workflow, link integrity, and asset hygiene. `techne:docsync` verifies prose claims (CLI commands, paths, signatures, config keys) against the actual codebase. `techne:deslop` flags AI-generated slop in comments and docstrings; `techne:reslop` rewrites docstrings grounded in the implementation rather than deleting them outright.

**Planning and provenance.** `techne:research-grounded` audits design decisions in `IMPL.md` / `ROADMAP.md` for missing `# research(YYYY-MM):` provenance, then web-searches to ground each choice against current best practice before it hardens into code.

**Versioning and observability.** `techne:auto-commit` groups working-tree changes into a structured commit plan at `COMMITS.md` for staged review before anything lands. `techne:theoros` starts an observed live dev session in a tmux pane; Claude drives the REPL, the human spectates read-only via `tmux attach -r`.

**Review and collaboration.** `techne:catchup` reads every comment, review and state change on a repo since you last participated and reports who is blocked on whom; read-only. `techne:elenchus` is adversarial pre-merge review: it drives `/code-review`, then reproduces the load-bearing claim, traces every consumer across the repo, and walks a bug-class rubric.

**Documents and research.** `techne:latex` builds a LaTeX document and gates it on its log, its PDF and the assignment it answers. `techne:pdf` renders markdown to print-quality PDFs through Typst and verifies the words survived. `techne:slides` gates a talk deck on titles, contrast, alt text and stray figures, then renders it through the app that will present it. `techne:paper` scaffolds a paper directory in a papers-style monorepo, and `techne:paper-review` runs a novelty and reviewer pass grounded in retrieved prior work.

**Cross-repo consistency.** `techne:sisters` audits drift across the repos listed in `~/.claude/techne.toml`: CI action pins, toolchain pins, skill-context structural parity, GitHub merge settings, open PRs, branch hygiene. Read-only; reports findings, leaves fixes to follow-up work.

## Typical workflows

**Pre-push validation.** Group local changes with `techne:auto-commit`, validate the build with `techne:audit`, scan for prose slop with `techne:deslop`, push. When CI finishes, run `techne:ci-audit` against the run for warnings and deprecations.

**Documentation accuracy.** After a refactor, run `techne:docsync` to find stale claims. Review the drift report; rewrite affected docstrings with `techne:reslop` if rewrite is preferable to deletion. Run `techne:docs-site` to confirm link integrity hasn't regressed.

**Multi-repo release.** Run `techne:sisters` to surface CI/toolchain/branch drift across the linked repos. Fix the drift in each repo (action pins, Python versions, merge settings). Validate each with `techne:audit`. Coordinate merges in consistent order.

**Returning to a shared repo.** Run `techne:catchup` before touching a team repo. When it lists a PR that needs review, run `techne:elenchus` on it.

**Observed session.** For long-running tasks (multi-hour test suites, large refactors), spin up a tmux session with `techne:theoros`. Share the session name; collaborators attach read-only with `tmux attach -r -t <session>`. The transcript persists in tmux scrollback.

## Design philosophy

Skills are independent; each invocable without the others; but share conventions: `.claude/skill-context.md` for per-repo config, `~/.claude/techne.toml` for user-level config, the dev-runner log archive at `logs/dev-*.log`. Audits are read-only, and skills that edit show their plan, report or diff before changing anything, so every change to the repo has a human approval in front of it. See [Conventions](conventions.md) for the standard file locations and adoption path.

## Stale-assumption audit

Each skill encodes assumptions about the ecosystem it audits: `techne:audit` assumes the dev-runner archive convention, `techne:ci-audit` assumes a particular GitHub Actions failure shape, `techne:docs-site` assumes the Zensical strict-build target, `techne:auto-commit` assumes Conventional Commits. Those assumptions decay as upstream tools, action SHAs, model families, and platform features ship.

The maintenance invariant: whenever a Claude Code release, MCP spec revision, GitHub Actions schema change, or frontier-model capability shift lands, audit which skill in this repo exists to compensate for a gap that may now be closed, and which skill's structural assumption has just gone stale. Skills are not write-once; they are kept in sync with the moving substrate they audit. Treat any skill last touched more than a quarter ago as suspect until re-verified against current platform docs.

This invariant runs philosophically; there is no automated check, it's a stance the maintainer holds when reading release notes. The sibling sister repos apply the same audit to their own code (see `phalanx-fl`, `velocity-fl`, `kourai-khryseai` ROADMAPs); techne's variant is meta, it audits the audit tools themselves.

## See also

- [Conventions](conventions.md): the standard file locations and adoption path
- [Examples](examples.md): concrete workflows using the skills together
- [Skills reference](skills/index.md): per-skill detail pages
