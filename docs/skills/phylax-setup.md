---
description: "phylax:setup shows which phylax options are on and checks what each needs: the Claude Code version for the guard mod, python3, git, and for the restart, tmux or Windows Terminal and its state folder."
---

# `phylax:setup`

Show which phylax options are on and check what each one needs.

Part of [phylax](../plugins/phylax.md): `/plugin install phylax@techne`, then switch options on in `/config`.

## When to use

After installing phylax, when a guard or a restart does not seem to fire, or to learn how to switch an option on.

## Usage

```text
/phylax:setup
```

The skill runs a doctor script that only reads, then follows the [setup runbook](https://github.com/ajbarea/techne/blob/main/plugins/phylax/AGENTS.md). Options are switched in `/config`, not by Claude. After you change one, run `/reload-plugins` and the skill again.

## What it checks

The first lines are the options, one per option: `ok` is on, `n/a` is off or not set, which is off. The lines after them check only what the options that are on need.

| Check | Matters when |
|---|---|
| `mod` | A guard is on. Claude Code 2.1.287 or later runs the guards from a mod, and 2.1.288 fixed that mod breaking Bash in worktree subagents. Older versions run them from the command hook, so this line is optional. |
| `python3` | Any option is on. 3.9 or newer. |
| `git` | A guard is on. |
| `proc`, `launcher`, `claude`, `state-dir` | `restart_on_update` is on: `/proc`, tmux or Windows Terminal, the `claude` on PATH, and a private state folder. |
| `budget` | `budget_mode` is on: the level it reads now and the usage file, or the status line step to add when no snapshot exists yet. |

## Output

Each line starts with `ok`, `missing`, `optional` or `n/a`, then the check's name and a detail. A `missing` or `optional` line is followed by one or more `fix:` lines. The last line is `result: ready`, or `result: missing` with the names of the required checks that failed. The doctor exits 0 when nothing required is missing, and only reads.

## See also

- [phylax plugin](../plugins/phylax.md): options, install and troubleshooting.
- [Configuration](../configuration.md#guards): what each guard reads.

## Full instructions

[`SKILL.md` on GitHub](https://github.com/ajbarea/techne/blob/main/plugins/phylax/skills/setup/SKILL.md) holds the full instructions Claude follows for this skill.
