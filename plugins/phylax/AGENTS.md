# phylax setup runbook

This is the setup guide for phylax, written for an agent guiding a user. Every phylax option is off until the user switches it on. Run the doctor first; it prints each option's value and checks only what the options that are on need. The setup skill gives the doctor command.

## Rules

- The doctor only reads. Run it again after each change.
- The user switches options on and off in `/config`, under the phylax plugin's options. Do not edit settings files for them.
- The user runs every fix line that contains `sudo`, `xcode-select --install` or a Homebrew cask (a cask install asks for the admin password). In Claude Code they type it after `!`, for example `!sudo apt install tmux`.
- You may run any other fix line after the user approves, such as the Claude Code installer, `claude update`, `rm` and `chmod`.
- Report only what the doctor printed.

## 1. Run the doctor

The first lines are the options, one per option. `ok` means on; `n/a` means off, or not set, which is off. The lines after them check what the options need. A `missing` or `optional` line is followed by `fix:` lines. The last line is `result: ready`, or `result: missing` with the names of the required checks that failed. The doctor exits 0 when nothing required is missing.

If the shell says `python3` is not found, the doctor cannot start. The user installs it with `sudo apt install python3` on Debian or Ubuntu, or `xcode-select --install` on macOS.

## 2. Choose the options

Explain each option, and ask which the user wants:

- `block_attribution_trailers` refuses a commit or PR whose message or body carries a Claude-Session link, a Co-Authored-By: Claude trailer, or a Generated with Claude Code line.
- `block_commits_md` refuses staging or committing a `COMMITS.md` scratchpad.
- `warn_main_checkout_commit` warns when a commit runs in a repo's main checkout while linked worktrees exist.
- `require_subagent_model` refuses an Agent call to a built-in agent type that runs on the session's model (`general-purpose`, `claude`, `Explore`, `Plan`) when it names no model. A managed, project or user agent that reuses one of those names replaces the built-in, so its own model decides (a model it names allows the call, `inherit` refuses it, and none falls through to `CLAUDE_CODE_SUBAGENT_MODEL` as for `general-purpose`). Other agents are left to their own definitions, and it stands down while `CLAUDE_CODE_SUBAGENT_MODEL_FORCE` or coordinator mode overrides the call's model. It needs python3 only, not git or the mod.
- `restart_on_update` moves an idle session onto a newly installed Claude Code in a new tmux window or Windows Terminal tab, keeping the conversation. It works on Linux and WSL only.
- `budget_mode` tells each session to route work to Sonnet and Haiku while the 5-hour or 7-day usage runs ahead of the time gone, and in frugal runs an Agent call naming Opus on Sonnet unless its description says "final review". It routes only sessions launched with `PHYLAX_BUDGET_ROLE=background`, or interactive ones that opt in with `PHYLAX_BUDGET=on`; `/phylax:budget off` pauses the opted-in ones. It reads the usage the status line saves, so the status line needs the snapshot step the doctor prints.

The user switches them on in `/config`. Then they run `/reload-plugins`, and you run the setup skill again so the doctor sees the new values.

## 3. Fix each missing line

| Check | When it matters | What to do |
| --- | --- | --- |
| `mod` | a guard is on | Claude Code 2.1.287 or later runs the guards from a mod, and 2.1.288 fixed that mod breaking Bash in worktree subagents. An older version still runs them from the command hook, so this line is optional. Run the fix line after the user approves; `claude update` moves to the newest version, and the mod loads after the user restarts Claude Code. |
| `python3` | any option is on | The hooks run on the system python3, 3.9 or newer. The user runs a `sudo` or `xcode-select --install` line with `!`. Run the `uv python install --default 3.12 && uv python update-shell` line after the user approves. |
| `git` | a guard is on | The user runs the fix line with `!`. |
| `proc` | restart_on_update is on | macOS and native Windows have no `/proc`. The user switches the option off there. |
| `launcher` | restart_on_update is on | The restart works only in a session running inside tmux, or inside Windows Terminal under WSL. If tmux is missing, the user runs the install line with `!`. Then the user starts Claude Code inside tmux with `tmux new-session claude`, or under WSL opens it in Windows Terminal. |
| `claude` | restart_on_update is on | The restart starts the `claude` on PATH. Run the fix line after the user approves. |
| `budget` | budget_mode is on | `optional` until a snapshot exists: show the user the `fix:` line, which puts the snapshot in front of their status line command in `settings.json`, and edit it in only after they approve. `ok` names the level and the file read. |
| `state-dir` | restart_on_update is on | Run the fix line it prints after the user approves. A folder owned by another user has no fix line; the user sets `XDG_RUNTIME_DIR` to a private folder. |

For `restart_on_update` under Windows Terminal, the old tab closes itself only with the shell snippet in [Restart on update](https://ajbarea.github.io/techne/configuration/#restart-on-update). Offer to show it.

## 4. Check the result

Run the doctor again until it prints `result: ready`.
