# phylax

phylax adds four opt-in Claude Code hooks: block attribution lines in commits and PRs, block staging `COMMITS.md`, warn on commits in a main checkout, and restart an idle session onto an updated Claude Code. Each is off until you switch it on. [Configuration](../configuration.md#guards) describes the guards, and [Restart on update](../configuration.md#restart-on-update) the restart.

## Install

```bash
/plugin marketplace add ajbarea/techne
/plugin install phylax@techne
```

Switch the options you want on in `/config`, under the phylax plugin's options. Then run `/reload-plugins` and `/phylax:setup`. It prints each option's value and checks what the options that are on need: the Claude Code version for the guard mod, python3, git, and for the restart, tmux or Windows Terminal and its state folder. Claude follows the [setup runbook](https://github.com/ajbarea/techne/blob/main/plugins/phylax/AGENTS.md).

## Troubleshooting

- **A guard does not fire.** Run `/phylax:setup`. An option shown as `not set, so off` is off; switch it on in `/config`. On Claude Code older than 2.1.287 the guards run from the command hook instead of the mod; 2.1.287 runs the mod but needs 2.1.288 for Bash in worktree subagents. Either way they run `git_guards.py` on the system python3, which `/phylax:setup` checks.
- **The restart never happens.** It needs Linux or WSL, tmux or Windows Terminal, and the `claude` on PATH. The hook's log, `$XDG_RUNTIME_DIR/phylax-restart-<uid>/log`, says why a session has not moved.
- **The new tab shows `Wsl/Service/0x8007274c` and `Could not access starting directory`.** WSL did not answer the new tab in time (Windows Terminal's `wsl.exe` timed out), so the handoff never ran and the old session was never stopped: keep using its tab. The log ends at `handoff launched via wt` with no `stopped` line, and `dmesg` usually shows `UtilAcceptVsock` waits from the same minutes. After 10 minutes the next idle prompt tries again. If it keeps happening, the WSL VM is short of memory or running many sessions.
