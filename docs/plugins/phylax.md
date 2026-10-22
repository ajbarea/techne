---
description: phylax plugin, opt-in Claude Code hooks. Block attribution lines in commits and PRs, block staging COMMITS.md, warn on main-checkout commits, refuse subagent calls that would silently inherit the session's model, and restart an idle session onto an updated Claude Code.
---

# phylax

phylax adds opt-in Claude Code hooks. Each is off until you switch it on in `/config`.

## Use it when

- A repo or an employer bans attribution lines in commit messages and PR bodies.
- A `COMMITS.md` scratchpad must never be committed.
- You work with several Claude sessions and want a warning before committing in a main checkout that has linked worktrees.
- A subagent should never silently inherit the session's model.
- You leave sessions open and want them moved onto an updated Claude Code without losing the conversation.

## Install

```text
/plugin marketplace add ajbarea/techne
/plugin install phylax@techne
```

## Needs

Claude Code 2.1.288 or later for the guard mod. On 2.1.287 the mod runs but breaks Bash in worktree subagents, and on an older version the guards run from the command hook instead. Any option that is on needs python3 3.9 or newer; the git guards also need git. `restart_on_update` needs Linux or WSL, plus tmux or Windows Terminal, and the `claude` command on PATH.

## Set up

Switch the options you want on in `/config`, under the phylax plugin's options. Then run `/reload-plugins` and `/phylax:setup`. It prints each option's value and checks what the options that are on need. `ok` means on; `n/a` means off, or not set, which is off. The last line is `result: ready`, or `result: missing` with the names of the required checks that failed. Claude follows the [setup runbook](https://github.com/ajbarea/techne/blob/main/plugins/phylax/AGENTS.md).

## Skills

| Skill | Use it to |
|---|---|
| [`phylax:setup`](../skills/phylax-setup.md) | Show which options are on and check what they need. |

## Configuration

| Option | What it does |
|---|---|
| `block_attribution_trailers` | Refuses `git commit` and `gh pr create`, `gh pr edit` or `gh pr merge` when the message, title or body has a `Claude-Session`, `claude.ai/code/session`, `Co-Authored-By: Claude` or `Generated with Claude Code` line, and blanks the trailer and footer Claude Code asks Claude to write. |
| `block_commits_md` | Refuses `git add` of a file named `COMMITS.md`, and `git commit` when the commit would include one. |
| `warn_main_checkout_commit` | Warns, without blocking, when `git commit` runs in a repo's main checkout while linked worktrees exist. |
| `require_subagent_model` | Refuses an `Agent` call to a built-in agent type with no model of its own (`general-purpose`, `claude`, `Explore` or `Plan`, or no type) when it names no `model`. Other agent types are left to their own definitions, since a model named in the call would override one the definition pins. While `CLAUDE_CODE_SUBAGENT_MODEL`, `CLAUDE_CODE_SUBAGENT_MODEL_FORCE` or `CLAUDE_CODE_COORDINATOR_FORCE_WORKER_INHERIT_MODEL` is set, the guard stands down, since those settings choose subagent models themselves and some make Claude Code ignore the call's model. |
| `restart_on_update` | Moves an idle session onto an updated Claude Code in a new tmux window or Windows Terminal tab, keeping the conversation. Any key during the 15 second countdown cancels it. |

[Configuration](../configuration.md#guards) describes what each guard reads and its limits, and [Restart on update](../configuration.md#restart-on-update) the restart. To turn a git guard off in one repo, set its camelCase git config key, such as `git config phylax.blockCommitsMd false`.

## Troubleshooting

- **`this command runs in <folder>, which is not an existing folder`.** The session's folder was removed, usually a worktree deleted while the session stood in it. Run `cd` to an existing folder, alone or as `cd <repo> && git ...`; a command with `git -C <repo>` is checked as usual. A subagent's commands go through the command hook, which Claude Code starts in the session's folder, so they can still fail with `posix_spawn` and `ENOENT` until the session moves.
- **A guard does not fire.** Run `/phylax:setup`. An option shown as `n/a` is off; switch it on in `/config`. On Claude Code older than 2.1.287 the guards run from the command hook instead of the mod; 2.1.287 runs the mod but needs 2.1.288 for Bash in worktree subagents. Either way they run `git_guards.py` on the system python3, which `/phylax:setup` checks.
- **The restart never happens.** It needs Linux or WSL, tmux or Windows Terminal, and the `claude` on PATH. The hook's log, `$XDG_RUNTIME_DIR/phylax-restart-<uid>/log`, says why a session has not moved.
- **The new tab shows `Wsl/Service/0x8007274c` and `Could not access starting directory`.** WSL did not answer the new tab in time (Windows Terminal's `wsl.exe` timed out), so the handoff never ran and the old session was never stopped: keep using its tab. The log ends at `handoff launched via wt` with no `stopped` line, and `dmesg` usually shows `UtilAcceptVsock` waits from the same minutes. After 10 minutes the next idle prompt tries again. If it keeps happening, the WSL VM is short of memory or running many sessions.
