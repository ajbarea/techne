# `techne:sisters`

Cross-repo drift audit across the sister repos listed in `~/.claude/techne.toml`. Read-only inspection: CI action pins, toolchain pins in `pyproject.toml`, skill-context structural parity, GitHub merge settings + branch protection, Codecov config, `make clean` log-retention, Dependabot config coverage, README header convention, worktree ignore, shared docs-site files and nav coverage, open PRs, and branch, worktree and stash hygiene. A clean mode removes finished branches and worktrees once you approve the list.

## When to use

- "Audit the sisters." / "Are the sisters in sync?" / "Check cross-repo drift."
- Before a coordinated multi-repo refactor or release.
- Spotting inconsistencies in action version pins, Python version envelopes, or merge settings across repos.
- "Comb the sisters." / "Clean up the branches and worktrees." Leftovers from merged PRs and finished sessions, removed after you approve the list.

## Usage

Invoke by name in Claude Code:

```
/techne:sisters
```

The skill reads the active sister list from `~/.claude/techne.toml`, runs all checks in parallel, and outputs a single audit block grouped by category: merge settings, skill-context parity, action-pin drift, toolchain-pin drift, branch protection, Codecov config, log-retention policy, Dependabot coverage, README header convention, worktree ignore, docs-site shared files, open PRs, branch and worktree hygiene, and local main sync.

The audit is read-only. It surfaces findings; it does not edit files, push branches, or change GitHub settings.

## Clean mode

Squash merges leave every merged branch "ahead of main", so ahead counts can't tell finished work from unfinished. The hygiene check judges each branch by its PR instead: finished when the PR merged at that tip. Clean mode shows you the finished branches and worktrees, and removes them after you say yes. It never removes:

- a branch with commits nobody merged, or commits added after the merge
- a worktree that is dirty, locked, recently active, in use by a running process (another session's), or holding ignored files that are not build output, such as `COMMITS.md`, `.env` or a nested worktree
- a remote branch with no PR, or someone else's
- a stash

Before removing anything it surveys again, and it keeps anything that changed since you approved.

## Prerequisites

`~/.claude/techne.toml` must exist and list at least one active sister repo. If the file is missing or yields zero active sisters, the skill stops and explains.

See [Configuration](../configuration.md) for the `techne.toml` format.

## See also

- [`techne:ci-audit`](ci-audit.md): drill into a specific PR's failing checks after the sisters audit names it.
- [`techne:audit`](audit.md): audit a single repo's local `make` targets.
- [Configuration](../configuration.md): `techne.toml` reference.
