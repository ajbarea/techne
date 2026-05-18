# `techne:sisters`

Cross-repo drift audit across the sister repos listed in `~/.claude/techne.toml`. Read-only inspection of CI action pins, toolchain pins, skill-context structural parity, GitHub merge settings, open PRs, and branch hygiene.

## When to use

- "Audit the sisters."
- "Are the sisters in sync?"
- "Check cross-repo drift."
- Whenever multiple sister repos are mentioned together for a consistency check.
- Before coordinating a multi-repo release or refactor.

## What it audits

- **CI action pins**: same SHA / version across repos? (e.g., `actions/checkout@v4.1.0` consistent)
- **Toolchain pins**: `pyproject.toml` Python, ruff, uv versions consistent?
- **Skill-context parity**: same structural shape in `.claude/skill-context.md`?
- **GitHub merge settings**: squash, branch protection, required checks aligned?
- **Open PRs**: anything stale or stuck? (open > 7 days without activity)
- **Branch hygiene**: orphaned branches, drift from `main`?

## Usage

```bash
# Full audit across all sisters
techne:sisters

# Audit specific aspect
techne:sisters --toolchain-only
techne:sisters --branch-hygiene-only

# Report mode (no fixes)
techne:sisters --report-only
```

## Configuration

The skill reads `~/.claude/techne.toml` for the list of active sister repos. Example:

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

## What it does NOT do

- Doesn't sweep, prune, or modify the team repo (read-only by policy).
- Doesn't auto-fix without review; surfaces drift, you decide.
- Doesn't force repos into lockstep; highlights where they've drifted.

## Troubleshooting

**"Sister repo not found"**: Check that `~/.claude/techne.toml` exists and lists the repo. Verify the repo path is correct.

**"GitHub API rate limit"**: Wait 1 hour, or authenticate with `gh auth login` to increase your quota.

**"Drift is intentional"**: The skill flags all differences. Some are expected (e.g., phalanx-fl uses teal, vFL uses purple). Review and dismiss if intentional.

## See also

- [`techne:audit`](audit.md) — audit a single repo's make targets.
- [`techne:docsync`](docsync.md) — verify individual repo docs.

## Reads

- `~/.claude/techne.toml`
- Each sister repo's `.github/workflows/`, `pyproject.toml`, `.claude/`, via `gh` API
