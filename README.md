# techne

AJ's personal Claude Code skill collection, distributed as a plugin.

## Skills

- `techne:audit` — runs the repo's make targets in dependency order; reconciles terminal output against `logs/dev-*.log` archives.
- `techne:auto-commit` — groups working-tree changes into a structured `COMMITS.md` plan for staged review.
- `techne:ci-audit` — audits GitHub Actions runs on the current branch/PR for warnings, failures, and noise; fixes what's fixable in-repo.
- `techne:deslop` — scans for AI-generated slop in comments and docstrings; proposes tightened rewrites.
- `techne:docs-site` — maintains the Zensical-powered docs site (config, deploy pipeline, theming, link integrity).
- `techne:docsync` — verifies documentation claims (CLI commands, paths, config keys, signatures) against the actual code.
- `techne:reslop` — rewrites docstrings grounded in the implementation rather than deleting them outright.
- `techne:sisters` — cross-repo drift audit across the sister repos listed in `~/.claude/techne.toml`.

## Install

```
/plugin marketplace add ajbarea/techne
/plugin install techne@techne
```

## Configuration

`techne:sisters` reads `~/.claude/techne.toml` at runtime — user-controlled config that lists active sister repos. Example:

```toml
github_user = "ajbarea"
workspace_root = "/home/ajbar/ajsoftworks"

[[sisters]]
name = "phalanx-fl"
status = "active"

[[sisters]]
name = "vFL"
status = "active"

[[sisters]]
name = "kourai-khryseai"
status = "active"
```

Set `status = "backburner"` to skip a repo without removing it.

## License

MIT.
