# `techne:sisters`

Cross-repo drift audit across the sister repos listed in `~/.claude/techne.toml`. Read-only inspection of CI action pins, toolchain pins, skill-context structural parity, GitHub merge settings, open PRs, and branch hygiene.

## When to use

- "Audit the sisters."
- "Are the sisters in sync?"
- "Check cross-repo drift."
- Whenever multiple sister repos are mentioned together for a consistency check.

## What it audits

- **CI action pins** — same SHA / version across repos?
- **Toolchain pins** — `pyproject.toml` Python, ruff, uv versions consistent?
- **Skill-context parity** — same structural shape in `.claude/skill-context.md`?
- **GitHub merge settings** — squash, branch protection, required checks aligned?
- **Open PRs** — anything stale or stuck?
- **Branch hygiene** — orphaned branches, drift from `main`?

## What it does NOT do

- Doesn't sweep, prune, or modify the team repo (read-only by policy).
- Doesn't auto-fix without review — surfaces drift, you decide.

## Configuration

Reads `~/.claude/techne.toml` for the list of active sister repos. See [Configuration](../configuration.md) for the schema.

## Reads

- `~/.claude/techne.toml`
- Each sister repo's `.github/workflows/`, `pyproject.toml`, `.claude/`, `gh` API.
