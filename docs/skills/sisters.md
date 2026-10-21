---
description: Audit the linked repos listed in ~/.claude/techne.toml for drift in CI pins, settings, branches and conventions.
---

# `techne:sisters`

Cross-repo drift audit across the sister repos listed in `~/.claude/techne.toml`. Read-only inspection: CI action pins, toolchain pins in `pyproject.toml`, skill-context structural parity, GitHub merge settings + branch protection, Codecov config, `make clean` log-retention, Dependabot config coverage, README header convention, worktree ignore, shared docs-site files and nav coverage, open PRs, and branch, worktree and stash hygiene. A clean mode removes finished branches and worktrees once you approve the list, and an auto mode does it for you.

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

The skill reads the active sister list from `~/.claude/techne.toml`, runs every check in order, and outputs a single audit block grouped by category: merge settings, skill-context parity, action-pin drift, toolchain-pin drift, branch protection, Codecov config, log-retention policy, Dependabot coverage, README header convention, worktree ignore, docs-site shared files, agent instruction file, open PRs, branch and worktree hygiene, and local main sync.

The audit report is read-only. It surfaces findings; it does not edit files, push branches, or change GitHub settings. Clean mode, below, is the only part that removes anything.

## Clean mode

Squash merges leave every merged branch "ahead of main", so ahead counts can't tell finished work from unfinished. The hygiene check judges each branch by its PR instead: finished when the PR merged at that tip. Clean mode shows you the finished branches and worktrees, and removes them after you say yes. It never removes:

- a branch with commits nobody merged, or commits added after the merge
- a worktree that is dirty, locked, recently active, in use by a running process (another session's), or holding ignored files that are not build output, such as `COMMITS.md`, `.env` or a nested worktree
- a remote branch with no PR, or someone else's
- a stash

The report marks a dirty, idle worktree whose `IMPL.md` is unchanged since its branch left the default branch as not resumable: a session that starts there after a restart has only the diff to go on. See [working docs](../conventions.md#implmd-and-roadmapmd-working-docs).

Branch, worktree and stash hygiene, and clean mode, run from `hygiene.py`; the other checks run from the skill's instructions. `hygiene.py --json` prints its survey as JSON, `--env` prints the shell variables `$SISTERS`, `$TEAM_SISTERS`, `$WORKSPACE` and `$GITHUB_USER` (one line and exit 1 when the config is missing, invalid or lists no active sister), and `--repo NAME`, which may repeat, narrows it to named sisters. One broken repo never stops the others. The audit flags open PRs older than 14 days and checks that logs are pruned after 30 days.

Clean mode runs `hygiene.py` in two steps. The first writes the plan, and `--repo NAME` narrows it to one sister:

```
python3 plugins/techne/skills/sisters/scripts/hygiene.py --plan-out PLAN
python3 plugins/techne/skills/sisters/scripts/hygiene.py --apply PLAN
```

Before removing anything it surveys again, and it keeps anything that changed since you approved.

## Auto mode

`hygiene.py --auto` removes, without asking, only what a merged PR finished: its PR merged into the default branch at the branch's tip, or a worktree whose directory is gone. A branch that merely sits inside the default branch, such as a fresh `worktree add -b x origin/main`, is left for clean mode. The survey covers the active sisters plus each `--path DIR` (repeatable) whose GitHub owner is your `github_user` or which is a sister. Each removal is logged to `~/.cache/techne/hygiene-auto.log` first, and the report names that file.

A worktree is held while a process has its working directory or an open file inside it, or while anything in it, ignored logs and caches included, changed in the last two hours.

It prints one line per removal, then:

- **Held after merge**: a worktree or branch whose PR merged but which uncommitted changes, ignored files that are not build output, later commits, a different tip, a nested worktree or a lock keep in place.
- **Closed without merging**: a branch or worktree whose PR closed unmerged.

Holds that clear by themselves (a running process, recent activity) are left out, and it prints nothing when there is nothing to say. It never fails: no `gh`, no network, an old python3 or one broken repo ends it quietly. git runs without prompts, and ssh in batch mode unless you chose its command (`GIT_SSH_COMMAND`, `GIT_SSH` or the repo's `core.sshCommand`), which it uses as is. A lock stops two runs at once, it gives up after 240 seconds, and the roster is swept at most once per 30 minutes (`--min-interval SECONDS`); the session's own repo is always processed.

Two kinds are reported and never acted on, here and under **Needs a look** in the normal report, for your own PRs only. An `issue` is an open issue that a merged PR in the same repo was linked to close, where the merge is a day old and nobody has commented or reopened it since; a PR that only mentions an issue does not count. A `pr` is an open PR whose changes the default branch already has (git 2.38 or newer).

To run it at the start of every session, turn on the `clean_finished_work` option of the techne plugin in `/config`. See [the techne plugin page](../plugins/techne.md#options).

## Prerequisites

`~/.claude/techne.toml` must exist and list at least one active sister repo. If the file is missing, is invalid TOML, lacks a required key, or yields zero active sisters, the skill reports the one-line cause and stops, pointing you at `/techne:setup`.

See [Configuration](../configuration.md) for the `techne.toml` format.

## See also

- [`techne:ci-audit`](ci-audit.md): drill into a specific PR's failing checks after the sisters audit names it.
- [`techne:audit`](audit.md): audit a single repo's local `make` targets.
- [Configuration](../configuration.md): `techne.toml` reference.

## Full instructions

[`SKILL.md` on GitHub](https://github.com/ajbarea/techne/blob/main/plugins/techne/skills/sisters/SKILL.md) holds the full instructions Claude follows for this skill.
