# Skills

The included skills, grouped by what they do.

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
| [`techne:research-grounded`](research-grounded.md) | Flags design decisions in `IMPL.md` / `ROADMAP.md` that lack `# research(YYYY-MM):` provenance, then web-searches to ground them. |

## Site and cross-repo

| Skill | Purpose |
|---|---|
| [`techne:docs-site`](docs-site.md) | Maintains the Zensical-powered docs site: config, deploy pipeline, theming, link integrity. |
| [`techne:sisters`](sisters.md) | Cross-repo drift audit across the sister repos listed in `~/.claude/techne.toml`. |

## Live session

| Skill | Purpose |
|---|---|
| [`techne:theoros`](theoros.md) | Starts an observed live dev session: Claude drives the REPL in a named tmux session; you spectate read-only via `tmux attach -r`. |
