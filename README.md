# techne

Nine Claude Code skills that audit builds, tame CI noise, hunt doc/code drift, and keep sister repos in lockstep, installable as a single `/plugin`.

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

## Configuration

`techne:sisters` reads `~/.claude/techne.toml` at runtime (user-controlled config that lists the active sister repos to compare against).

```toml
github_user   = "ajbarea"
workspace_root = "/home/ajbar/ajsoftworks"

[[sisters]]
name   = "phalanx-fl"
status = "active"

[[sisters]]
name   = "vFL"
status = "active"

[[sisters]]
name   = "kourai-khryseai"
status = "active"
```

Set `status = "backburner"` to skip a repo without removing it.

## How it fits together

```
~/.claude/techne.toml      ← user-controlled sister-repo registry
        │
        ▼
techne (plugin)
├── audit         ── verifies build targets vs. logs/
├── auto-commit   ── groups diffs into COMMITS.md
├── ci-audit      ── reads gh runs, fixes warnings in-repo
├── deslop        ── flags AI-slop prose
├── docs-site     ── manages Zensical site + deploy
├── docsync       ── doc claims ↔ implementation
├── reslop        ── rewrites docstrings from code
├── sisters       ── cross-repo drift across sisters
└── theoros       ── observed tmux REPL session
```

Each skill is self-contained. Invoke one without pulling in the others. They share a convention of writing intermediate artifacts (plans, audit reports) to disk for human review before mutating the repo.

## Why "techne"

Greek τέχνη: craft, the practical knowledge of how to make a thing well. Sister project to [kourai-khryseai](https://github.com/ajbarea/kourai-khryseai), where Techne is the coder agent.

## License

MIT.
