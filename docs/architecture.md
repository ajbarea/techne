---
description: "How the techne skills fit together: categories, typical workflows, design philosophy, how skills are tested and how the repo stays current."
---

# Architecture

Techne is a collection of independent, composable skills that share conventions but don't hard-depend on each other. This page maps the skill ecosystem, names the typical workflows, and states the design philosophy.

## Skill categories

**Build and toolchain.** `techne:audit` validates that your local build is clean (lint, test, end-to-end) by walking your Makefile dependency graph and diffing terminal output against per-invocation log archives. `techne:ci-audit` does the same for GitHub Actions runs; flags warnings, deprecations, and noise; fixes what's fixable in-repo (workflow YAML, action pins, dependency versions).

**Documentation and prose.** `techne:docs-site` maintains the Zensical-built Pages workflow, link integrity, and asset hygiene. `techne:docsync` verifies prose claims (CLI commands, paths, signatures, config keys) against the actual codebase. `techne:deslop` flags AI-generated slop in comments and docstrings; `techne:reslop` rewrites docstrings grounded in the implementation rather than deleting them outright.

**Planning and provenance.** `techne:research-grounded` audits design decisions in `IMPL.md` / `ROADMAP.md` for missing `# research(YYYY-MM):` provenance, then web-searches to ground each choice against current best practice before it hardens into code.

**Versioning and observability.** `techne:auto-commit` groups working-tree changes into a structured commit plan at `COMMITS.md` for staged review before anything lands. `techne:theoros` starts an observed live dev session in a tmux pane; Claude drives the REPL, the human spectates read-only via `tmux attach -r`.

**Review and collaboration.** `techne:board` keeps one GitHub Projects board of every repo's work by stage (Idea, Issue, In PR, Merged, Live), and a hook files each issue or PR a `gh` command opens. `techne:catchup` reads every comment, review and state change on a repo since you last participated and reports who is blocked on whom; read-only. `techne:elenchus` is adversarial pre-merge review: an independent reviewer sized to the change's risk (plus `/code-review` for risky changes) reproduces the load-bearing claim, traces every consumer across the repo, and walks a bug-class rubric.

**Setup.** `techne:setup`, `graphe:setup`, `heuresis:setup` and `phylax:setup` each run a read-only doctor for their plugin and print the install command for anything missing; `epistole:setup` guides the Google sign-in and `schole:setup` the course-site sign-in.

**Mail.** `epistole` runs a local Gmail MCP server that searches, reads and drafts in each configured account and sends a draft only after you approve it; `epistole:setup` guides the one-time Google sign-in. See [epistole](plugins/epistole.md).

**Bibliographies.** `dokimasia:check` lints any `.bib` or hand-written `thebibliography`, resolves its identifiers against arXiv and Crossref, and checks that every cited key rendered in the built document; a failed lookup is reported apart from a wrong entry.

**Ideas.** `heuresis` is a Python package with a command-line interface that the skills call. `heuresis:idea` dispatches four scout agents (papers, patents, products, your own work) and a judge agent, and the package pools their records, verifies every quote and enforces the verdict rules in code. Its search code is the shared `_shared/scholarly.py`, and every request goes through `_shared/polite_http.py` (per-host pacing across processes, `Retry-After`, an identifying User-Agent, robots.txt for page fetches); both are copied from techne and kept identical by `make guards`; `heuresis:setup` checks the tools and creates the ideas repository. See [`heuresis:idea`](skills/idea.md).

**Documents and research.** `graphe:latex` builds a LaTeX document and gates it on its log, its PDF and the assignment it answers. `graphe:pdf` renders markdown to print-quality PDFs through Typst and verifies the words survived. `graphe:slides` starts a talk from an animated reveal.js web deck, gates it on titles, contrast, alt text, missing files and phone fit in a real browser, renders it, and publishes it on GitHub Pages; existing `.pptx` and PDF decks get the same text gates. `graphe:paper` scaffolds a paper directory in a papers-style monorepo, and `graphe:paper-review` runs a novelty and reviewer pass grounded in retrieved prior work.

**Cross-repo consistency.** `techne:sisters` audits drift across the repos listed in `~/.claude/techne.toml`: CI action pins, toolchain pins, skill-context structural parity, GitHub merge settings, open PRs, branch hygiene. Its report is read-only and leaves fixes to follow-up work; its clean mode removes finished branches and worktrees after you approve the list.

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

## How the skills are tested

Two layers, for two kinds of failure.

**Scripts** (`make test-unit`). Every script a skill ships has pytest coverage: the LaTeX log gates, the markdown-to-Typst renderer, the bibliography checker, the catch-up sweep, the slide-deck checker, auto-commit's staleness fingerprint, and the theoros session lifecycle, which drives real tmux sessions. These run in CI. A test that needs a tool fails when the tool is missing, so a skipped case is never silent: set `TECHNE_NO_TMUX`, `TECHNE_NO_TEX`, `TECHNE_NO_TYPST` or `TECHNE_NO_BROWSER` to `1` to opt out on purpose on a machine without tmux, TeX Live, Typst or Chromium. `make test-sandboxed` runs the same suite inside Anthropic's [sandbox-runtime](https://github.com/anthropics/sandbox-runtime), pinned in `scripts/srt`, on Linux. It has no network, writes only to the repo and a private temp folder, cannot read credential folders, `/tmp`, the session D-Bus, WSL interop or `/mnt`, and gets a cleaned environment and its own uv cache and venv, so a test that reaches outside the repo fails instead of touching real repositories, credentials or tmux sessions. It still reads the rest of the home folder, and Unix sockets stay open because tmux and Chromium need them. `make install-probe` is the other check: it installs the marketplace from GitHub into Claude Code, Codex and Copilot CLI in a clean container.

**Routing** (`make evals`). A skill that never fires does nothing, and a skill that fires on someone else's request does harm. `claude plugin eval` sends natural-language prompts to fresh sessions and records which skill Claude chose. Each skill has a case that must fire it, and collision cases must not: merging a PDF is not `graphe:pdf`, an email catch-up is not `techne:catchup`, editing a slide's title is not `graphe:slides`. Every case also loads every sibling plugin's skills and stand-ins for the general PDF, PPTX and BibTeX-formatting skills; an email catch-up must reach epistole's `catch-me-up`, which every case loads as a sibling, so a description that overlaps any of them fails a case instead of shipping. Evals run on your own credential and are not part of CI.

## Staying current

Claude Code, its plugin system and the Agent Skills spec change weekly, and a skill written against last month's docs can quietly fall behind. Every Monday the `freshness` workflow has Claude read the Claude Code changelog and releases, the plugin and skill docs, the Agent Skills spec and `claude-code-action` releases, compare each change with techne's files, and, when something affects techne, open one issue labelled `freshness` listing what to change, with a link and a file for each item. The job that reads the web has read-only permissions, fetches only from the source domains, and returns the issue as structured output; a second job with no model in it files the issue. The changes go through ordinary pull requests. The instructions are [.github/freshness.md](https://github.com/ajbarea/techne/blob/main/.github/freshness.md), and `make freshness` runs the same check on your own login and prints the issue instead of opening it. The workflow needs an `ANTHROPIC_API_KEY` or `CLAUDE_CODE_OAUTH_TOKEN` repository secret and skips with a notice without one.

## See also

- [Conventions](conventions.md): the standard file locations and adoption path
- [Examples](examples.md): concrete workflows using the skills together
- [Skills reference](skills/index.md): per-skill detail pages
