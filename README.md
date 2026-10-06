<div align="center">

<img src="docs/assets/hero.png" width="420" alt="techne Hero Image">

# techne

*A Claude Code plugin marketplace: skills for code repos and for documents, opt-in git guards, and a spoken Claude Code.*

[![Validate](https://github.com/ajbarea/techne/actions/workflows/validate.yml/badge.svg)](https://github.com/ajbarea/techne/actions/workflows/validate.yml)
[![Docs](https://github.com/ajbarea/techne/actions/workflows/docs.yml/badge.svg)](https://github.com/ajbarea/techne/actions/workflows/docs.yml)
[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![uv](https://img.shields.io/badge/uv-package_manager-DE5FE9?style=flat-square)](https://docs.astral.sh/uv/)
[![Claude Code](https://img.shields.io/badge/Claude_Code-plugin-D97757?style=flat-square)](https://code.claude.com/docs)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](LICENSE)

</div>

---

## Plugins

| Plugin | For | Runs in |
| --- | --- | --- |
| `techne` | Work in a code repo: audits, CI review, pre-merge review, commit plans, GitHub catch-up, cross-repo drift, slop and doc drift | Claude Code |
| `graphe` | Documents: LaTeX papers, markdown-to-PDF, talk decks, paper scaffolds and novelty review | Claude Code |
| `phylax` | Opt-in git and PR guards (a mod), restart onto an updated Claude Code | Claude Code |
| [`keryx`](https://github.com/ajbarea/keryx) | Speaks a short gist of each reply in a local voice (WSL2) | Claude Code |

Install only the ones you use: every enabled plugin's skill list sits in Claude's context on every turn. graphe holds skills only, so claude.ai and Cowork can install it too, but its build and check steps run shell commands (`uv`, TeX Live, Typst) that need Claude Code.

### techne

| Skill | What it does |
| --- | --- |
| `techne:audit` | Runs the repo's `make` targets in dependency order and reconciles terminal output against `logs/dev-*.log` archives. |
| `techne:auto-commit` | Groups working-tree changes into a structured `COMMITS.md` plan for staged review before anything lands. |
| `techne:catchup` | Reads every comment, review, and state change on a repo's issues and PRs since you last participated, then reports who is blocked on whom. |
| `techne:ci-audit` | Audits GitHub Actions runs on the current branch/PR: surfaces warnings, failures, and noise; fixes what's fixable in-repo. |
| `techne:deslop` | Scans comments and docstrings for AI-generated slop and proposes tightened rewrites. |
| `techne:docs-site` | Maintains the Zensical-powered docs site: config, deploy pipeline, theming, link integrity. |
| `techne:docsync` | Verifies documentation claims (CLI commands, paths, config keys, signatures) against the actual code. |
| `techne:elenchus` | Adversarial pre-merge review: drives `/code-review`, then reproduces the load-bearing claim, traces every consumer across the whole repo, and walks a bug-class rubric for reachable destructive ops, unmirrored parallel-path guards, migration crashes, and dead-but-green features. |
| `techne:research-grounded` | Flags design decisions in IMPL/ROADMAP that lack `# research(YYYY-MM):` provenance, then web-searches to ground them. |
| `techne:reslop` | Rewrites docstrings grounded in the implementation rather than deleting them outright. |
| `techne:sisters` | Cross-repo drift audit across the sister repos listed in `~/.claude/techne.toml`. |
| `techne:theoros` | Starts an observed live dev session: Claude drives the REPL in a named `tmux` session; you spectate read-only via `tmux attach -r`. |

### graphe

| Skill | What it does |
| --- | --- |
| `graphe:latex` | Builds a LaTeX document and gates it on its log, its PDF, and the assignment it answers; a clean `latexmk` exit is not the signal. |
| `graphe:paper` | Scaffolds a new paper dir (LaTeX + results-harvest + shared bib + portfolio row) in a papers-style monorepo so it builds on day one. |
| `graphe:paper-review` | Pre-submission novelty + reviewer pass for a draft paper: grounds every novelty/claim verdict in retrieved prior work, flags related-work gaps, and surfaces lab-overlap for disclosure. |
| `graphe:pdf` | Renders markdown to print-quality PDFs through a Typst template, then verifies fonts and content against the source. |
| `graphe:slides` | Gates a talk deck before it is presented: real slide titles, contrast, alt text, stray figures; renders it through the app that will show it. |

### phylax

Three opt-in guards on `git commit`, `git add` and `gh pr`, run by a [mod](https://code.claude.com/docs/en/plugins/mods/overview) (Claude Code 2.1.287 or later): block attribution lines, from the text Claude Code composes through to the command Claude runs; block staging `COMMITS.md`; and warn on commits in the main checkout. A check that fails refuses the command instead of letting it through. A fourth option, `restart_on_update`, moves an idle session onto an updated Claude Code in a new tmux window or Windows Terminal tab and keeps the conversation. Each is off until you switch it on in `/config`. See [Configuration](docs/configuration.md#guards) and [Restart on update](docs/configuration.md#restart-on-update).

## Install

From inside Claude Code:

```bash
/plugin marketplace add ajbarea/techne
/plugin install techne@techne
/plugin install graphe@techne
/plugin install phylax@techne
```

Invoke a skill as `/techne:<name>` or `/graphe:<name>`, or describe the task and Claude picks the matching skill. Run `/skills` to confirm they loaded. On claude.ai, add `ajbarea/techne` under **Customize > Plugins > Add > Add marketplace**, then add `graphe`.

> **First-time setup:** the techne skills are opinionated about a few conventions (Makefile pattern, dev-runner archive, `.claude/skill-context.md`). See [Conventions](docs/conventions.md) for the minimum each skill needs.

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
techne (marketplace: ajbarea/techne)
├── techne (plugin, plugins/techne)
│   ├── audit             ── verifies build targets vs. logs/
│   ├── auto-commit       ── groups diffs into COMMITS.md
│   ├── catchup           ── who is blocked on whom since you last looked
│   ├── ci-audit          ── reads gh runs, fixes warnings in-repo
│   ├── deslop            ── flags AI-slop prose
│   ├── docs-site         ── manages Zensical site + deploy
│   ├── docsync           ── doc claims ↔ implementation
│   ├── elenchus          ── adversarial pre-merge review (reproduce + trace + rubric)
│   ├── research-grounded ── flags un-grounded design decisions
│   ├── reslop            ── rewrites docstrings from code
│   ├── sisters           ── cross-repo drift across sisters
│   └── theoros           ── observed tmux REPL session
├── graphe (plugin, plugins/graphe)
│   ├── latex             ── builds LaTeX and gates the PDF on its log
│   ├── paper             ── scaffolds a new paper dir (LaTeX + harvest)
│   ├── paper-review      ── grounded novelty + reviewer pass for a draft
│   ├── pdf               ── markdown to print PDF via Typst, verified
│   └── slides            ── talk deck gated and rendered, presenter briefed
├── phylax (plugin, plugins/phylax) ── opt-in git guards + restart on update
└── keryx (plugin, ajbarea/keryx)    ── spoken gist of each reply
```

Each skill is self-contained. Invoke one without pulling in the others. They share a convention of writing intermediate artifacts (plans, audit reports) to disk for human review before mutating the repo.

## Why "techne"

Greek τέχνη: craft, the practical knowledge of how to make a thing well. The plugins keep the Greek: γραφή (graphe) is writing, φύλαξ (phylax) a guard, κῆρυξ (keryx) a herald.

## License

MIT.

---

<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/brand-white.png">
  <img src="docs/assets/brand.png" alt="" height="16" />
</picture>&nbsp;&nbsp;2026 <a href="https://ajbarea.github.io/">AJ Barea</a>

</div>
