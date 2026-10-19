---
description: Every skill, grouped by what it does, with a link to its page. Each page says when to use the skill, how to run it and what it changes.
---

# Skills

Skills ship as plugins: `techne` for work in a code repo, `graphe` for documents, `dokimasia` for bibliographies, `heuresis` for ideas, `phylax` for git guards, `epistole` for Gmail, and `schole` for Brightspace course sites. keryx, from `ajbarea/keryx`, adds `keryx:pronounce`, documented on the [keryx page](../plugins/keryx.md). Grouped by what they do.

## Build hygiene

| Skill | Purpose |
|---|---|
| [`techne:audit`](audit.md) | Runs the repo's `make` targets in dependency order and reconciles terminal output against `logs/dev-*.log` archives. |
| [`techne:ci-audit`](ci-audit.md) | Audits GitHub Actions runs on the current branch/PR. Surfaces warnings, failures, and noise; fixes what's fixable in-repo. |

## Code and doc maintenance

| Skill | Purpose |
|---|---|
| [`techne:auto-commit`](auto-commit.md) | Groups working-tree changes into a structured `COMMITS.md` plan for staged review before anything lands. |
| [`techne:deslop`](deslop.md) | Scans comments and docstrings for AI-generated slop and proposes tightened rewrites. |
| [`techne:reslop`](reslop.md) | Rewrites docstrings grounded in the implementation rather than deleting them outright. |
| [`techne:docsync`](docsync.md) | Verifies documentation claims (CLI commands, paths, config keys, signatures) against the actual code. |
| [`techne:research-grounded`](research-grounded.md) | Flags decisions (technology, data release, study design, access rules, claim wording) in `IMPL.md`, `ROADMAP.md` and decision records that lack `# research(YYYY-MM):` provenance, then web-searches to ground them. |

## Review and collaboration

| Skill | Purpose |
|---|---|
| [`techne:catchup`](catchup.md) | Reads every comment, review, and state change on one repo since you last participated, then reports who is blocked on whom. |
| [`techne:elenchus`](elenchus.md) | Adversarial pre-merge review: drives `/code-review`, then reproduces the load-bearing claim, traces every consumer, and applies a fixed bug-class rubric. |

## Site and cross-repo

| Skill | Purpose |
|---|---|
| [`techne:docs-site`](docs-site.md) | Maintains the Zensical-powered docs site: config, deploy pipeline, theming, link integrity. |
| [`techne:sisters`](sisters.md) | Cross-repo drift audit across the sister repos listed in `~/.claude/techne.toml`. |

## Live session

| Skill | Purpose |
|---|---|
| [`techne:theoros`](theoros.md) | Starts an observed live dev session: Claude drives the REPL in a named tmux session; you spectate read-only via `tmux attach -r`. |

## Documents (graphe)

| Skill | Purpose |
|---|---|
| [`graphe:paper`](paper.md) | Scaffolds a new paper dir (LaTeX + results-harvest + shared bib + portfolio row) in a papers-style monorepo so it builds on day one. |
| [`graphe:paper-review`](paper-review.md) | Pre-submission novelty + reviewer pass: grounds every novelty/claim verdict in retrieved prior work, flags related-work gaps, and surfaces lab-overlap for disclosure. |
| [`graphe:latex`](latex.md) | Builds a LaTeX document and gates it on its log, its PDF, and the assignment it answers; a clean `latexmk` exit is not the signal. |
| [`graphe:pdf`](pdf.md) | Renders markdown to print-quality PDFs through a Typst template, then verifies fonts and content against the source. |
| [`graphe:slides`](slides.md) | Builds and gates a talk deck: an animated web deck on GitHub Pages from a starter, checked for titles, contrast, alt text, missing files and phone fit, then rendered and published. |

## Bibliographies (dokimasia)

| Skill | Purpose |
|---|---|
| [`dokimasia:check`](check.md) | Lints any `.bib` or hand-written `thebibliography` offline, verifies it against arXiv and Crossref telling a failed lookup from a wrong entry, and checks every cited key rendered. |

## Ideas (heuresis)

| Skill | Purpose |
|---|---|
| [`heuresis:idea`](idea.md) | Captures an idea and triages it against papers, patents, products and your own work, naming the closest existing work and filing it as trash, later, do or merged with checked evidence. |

## Mail (epistole)

| Skill | Purpose |
|---|---|
| [`epistole:catch-me-up`](catch-me-up.md) | Sweeps every Gmail account for mail since the last sweep, plus the course site when schole is installed, and reports what needs you. |
| [`epistole:setup`](epistole-setup.md) | Guides creating a Google OAuth client and signing each Gmail account in. The Gmail tools are covered on the [epistole](../plugins/epistole.md) page. |

## Courses (schole)

| Skill | Purpose |
|---|---|
| [`schole:courses`](courses.md) | New announcements and content, what is due, and what came due unsubmitted on a Brightspace (D2L) course site. Read-only. |
| [`schole:setup`](schole-setup.md) | Installs the browser and signs you in to the course site once. |

## Setup

| Skill | Purpose |
|---|---|
| [`techne:setup`](techne-setup.md) | Checks what the techne skills need on this machine and prints each fix. |
| [`graphe:setup`](graphe-setup.md) | Checks TeX Live, poppler, Chromium and the other document tools. |
| [`heuresis:setup`](heuresis-setup.md) | Checks uv, git and the optional `gh`, creates the ideas repository, and lists the search keys that are set. |
| [`phylax:setup`](phylax-setup.md) | Shows which phylax options are on and checks what they need. |
| [`epistole:setup`](epistole-setup.md) | Creates the Google OAuth client and signs each Gmail account in. |
| [`schole:setup`](schole-setup.md) | Installs the browser and signs you in to the course site once. |
