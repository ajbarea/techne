---
description: Audit the linked repos listed in ~/.claude/techne.toml for drift in CI pins, settings, branches and conventions.
---

# `techne:sisters`

Cross-repo drift audit across the sister repos listed in `~/.claude/techne.toml`. Read-only inspection: CI action pins, toolchain pins in `pyproject.toml`, skill-context structural parity, GitHub merge settings + branch protection, Codecov config, `make clean` log-retention, Dependabot config coverage, README header convention, worktree ignore, shared docs-site files and nav coverage, open PRs, and branch, worktree and stash hygiene. A clean mode removes finished branches and worktrees once you approve the list.

Part of [techne](../plugins/techne.md): `/plugin install techne@techne`, then `/techne:setup`.

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

The skill reads the active sister list from `~/.claude/techne.toml`, runs all fourteen checks in order, and outputs a single audit block grouped by category: merge settings, skill-context parity, action-pin drift, toolchain-pin drift, branch protection, Codecov config, log-retention policy, Dependabot coverage, README header convention, worktree ignore, docs-site shared files, open PRs, branch and worktree hygiene, and local main sync.

The audit report is read-only. It surfaces findings; it does not edit files, push branches, or change GitHub settings. Clean mode, below, is the only part that removes anything.

## Clean mode

Squash merges leave every merged branch "ahead of main", so ahead counts can't tell finished work from unfinished. The hygiene check judges each branch by its PR instead: finished when the PR merged at that tip. Clean mode shows you the finished branches and worktrees, and removes them after you say yes. It never removes:

- a branch with commits nobody merged, or commits added after the merge
- a worktree that is dirty, locked, recently active, in use by a running process (another session's), or holding ignored files that are not build output, such as `COMMITS.md`, `.env` or a nested worktree
- a remote branch with no PR, or someone else's
- a stash

The audit itself is `hygiene.py`: `--json` prints the full survey as JSON, `--env` prints the shell variables `$SISTERS`, `$TEAM_SISTERS`, `$WORKSPACE` and `$GITHUB_USER` (one line and exit 1 when the config is missing, invalid or lists no active sister), and `--repo NAME`, which may repeat, narrows it to named sisters. One broken repo never stops the others. Open PRs older than 14 days are flagged, and log retention is a 30-day prune.

Clean mode runs `hygiene.py` in two steps. The first writes the plan, and `--repo NAME` narrows it to one sister:

```
python3 plugins/techne/skills/sisters/scripts/hygiene.py --plan-out PLAN
python3 plugins/techne/skills/sisters/scripts/hygiene.py --apply PLAN
```

Before removing anything it surveys again, and it keeps anything that changed since you approved.

## Prerequisites

`~/.claude/techne.toml` must exist and list at least one active sister repo. If the file is missing, is invalid TOML, lacks a required key, or yields zero active sisters, the skill reports the one-line cause and stops, pointing you at `/techne:setup`.

See [Configuration](../configuration.md) for the `techne.toml` format.

## See also

- [`techne:ci-audit`](ci-audit.md): drill into a specific PR's failing checks after the sisters audit names it.
- [`techne:audit`](audit.md): audit a single repo's local `make` targets.
- [Configuration](../configuration.md): `techne.toml` reference.

## Full instructions

[`SKILL.md` on GitHub](https://github.com/ajbarea/techne/blob/main/plugins/techne/skills/sisters/SKILL.md) holds the full instructions Claude follows for this skill.
