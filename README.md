<div align="center">

<img src="docs/assets/hero.png" width="420" alt="techne Hero Image">

# techne

*Opinionated Claude Code skills for repo hygiene: audit builds, tame CI noise, hunt doc/code drift, keep linked repos in lockstep.*

[![Validate](https://github.com/ajbarea/techne/actions/workflows/validate.yml/badge.svg)](https://github.com/ajbarea/techne/actions/workflows/validate.yml)
[![Docs](https://github.com/ajbarea/techne/actions/workflows/docs.yml/badge.svg)](https://github.com/ajbarea/techne/actions/workflows/docs.yml)
[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![uv](https://img.shields.io/badge/uv-package_manager-DE5FE9?style=flat-square)](https://docs.astral.sh/uv/)
[![Claude Code](https://img.shields.io/badge/Claude_Code-plugin-D97757?style=flat-square)](https://code.claude.com/docs)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](LICENSE)

</div>

---

Installable as a single `/plugin`:

```bash
/plugin marketplace add ajbarea/techne
/plugin install techne@techne
```

## What's in the box

| Skill | What it does |
| --- | --- |
| `techne:audit` | Runs the repo's `make` targets in dependency order and reconciles terminal output against `logs/dev-*.log` archives. |
| `techne:auto-commit` | Groups working-tree changes into a structured `COMMITS.md` plan for staged review before anything lands. |
| `techne:ci-audit` | Audits GitHub Actions runs on the current branch/PR: surfaces warnings, failures, and noise; fixes what's fixable in-repo. |
| `techne:deslop` | Scans comments and docstrings for AI-generated slop and proposes tightened rewrites. |
| `techne:docs-site` | Maintains the Zensical-powered docs site: config, deploy pipeline, theming, link integrity. |
| `techne:docsync` | Verifies documentation claims (CLI commands, paths, config keys, signatures) against the actual code. |
| `techne:elenchus` | Adversarial pre-merge review: drives `/code-review`, then reproduces the load-bearing claim, traces every consumer across the whole repo, and walks a bug-class rubric for reachable destructive ops, unmirrored parallel-path guards, migration crashes, and dead-but-green features. |
| `techne:paper` | Scaffolds a new paper dir (LaTeX + results-harvest + shared bib + portfolio row) in a papers-style monorepo so it builds on day one. |
| `techne:paper-review` | Pre-submission novelty + reviewer pass for a draft paper: grounds every novelty/claim verdict in retrieved prior work, flags related-work gaps, and surfaces lab-overlap for disclosure. |
| `techne:research-grounded` | Flags design decisions in IMPL/ROADMAP that lack `# research(YYYY-MM):` provenance, then web-searches to ground them. |
| `techne:reslop` | Rewrites docstrings grounded in the implementation rather than deleting them outright. |
| `techne:sisters` | Cross-repo drift audit across the sister repos listed in `~/.claude/techne.toml`. |
| `techne:theoros` | Starts an observed live dev session: Claude drives the REPL in a named `tmux` session; you spectate read-only via `tmux attach -r`. |

## Install

Add the marketplace and install the plugin from inside Claude Code:

```bash
/plugin marketplace add ajbarea/techne
/plugin install techne@techne
```

Skills become available as `techne:<name>` and can be invoked the same way as any other Claude Code skill.

> **First-time setup:** techne is opinionated about a few conventions (Makefile pattern, dev-runner archive, `.claude/skill-context.md`). See [Conventions](docs/conventions.md) for the minimum each skill needs.

## Configuration

`techne:sisters` reads `~/.claude/techne.toml` at runtime (user-controlled config that lists the active sister repos to compare against).

```toml
github_user   = "your-github-username"
workspace_root = "/path/to/your/workspace"

[[sisters]]
name   = "repo-one"
status = "active"

[[sisters]]
name   = "repo-two"
status = "active"

[[sisters]]
name   = "repo-three"
status = "active"
```

Set `status = "backburner"` to skip a repo without removing it.

## How it fits together

```
~/.claude/techne.toml      ← user-controlled sister-repo registry
        │
        ▼
techne (plugin)
├── audit             ── verifies build targets vs. logs/
├── auto-commit       ── groups diffs into COMMITS.md
├── ci-audit          ── reads gh runs, fixes warnings in-repo
├── deslop            ── flags AI-slop prose
├── docs-site         ── manages Zensical site + deploy
├── docsync           ── doc claims ↔ implementation
├── elenchus          ── adversarial pre-merge review (reproduce + trace + rubric)
├── paper             ── scaffolds a new paper dir (LaTeX + harvest)
├── paper-review      ── grounded novelty + reviewer pass for a draft
├── research-grounded ── flags un-grounded design decisions
├── reslop            ── rewrites docstrings from code
├── sisters           ── cross-repo drift across sisters
└── theoros           ── observed tmux REPL session
```

Each skill is self-contained. Invoke one without pulling in the others. They share a convention of writing intermediate artifacts (plans, audit reports) to disk for human review before mutating the repo.

## Why "techne"

Greek τέχνη: craft, the practical knowledge of how to make a thing well. That's what these skills are for — the craft of keeping a repo honest: audits, drift checks, clean commits, clean prose.

## License

MIT.

---

<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/brand-white.png">
  <img src="docs/assets/brand.png" alt="" height="16" />
</picture>&nbsp;&nbsp;2026 <a href="https://ajbarea.github.io/">AJ Barea</a>

</div>
