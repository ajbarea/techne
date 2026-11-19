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
- `block_long_bodies` refuses a `gh` write of an issue, PR or comment body whose visible text (outside `<details>`) runs past about 150 words (PR, comment) or 300 (issue), or that carries a `budget:` marker; it warns on sentences over 25 words. Words count as graphe's `length_budget.markdown_words` counts a markdown page, with two differences: HTML tags and entities do not count, and a `## References` section does (tests/test_body_gate.py holds the two equal on the cases it lists). `gh pr create --fill` without a body is refused, since its body comes from commit messages.
- `block_background_loops` refuses a background Bash command, or any command with a `&`, whose `while` or `until` loop neither a nonzero `timeout` nor a `$SECONDS` test bounds, and names `timeout N bash -c '...'` and `gh pr checks N --watch --fail-fast`.
- `block_pkill_full` refuses `pkill -f` and `pgrep -f`, whose pattern also matches the calling shell's own command line, and names `kill` on the PID you started, or `pkill -x NAME`.
- `block_secrets` refuses a commit whose added lines hold a secret, and a push whose new commits do, using gitleaks 8.19 or newer (or ggshield for commits when `GITGUARDIAN_API_KEY` is set). It covers subagents too, and refuses every commit while no scanner is installed.
- `require_subagent_model` refuses an Agent call to a built-in agent type that runs on the session's model (`general-purpose`, `claude`, `Explore`, `Plan`) when it names no model. A managed, project or user agent that reuses one of those names replaces the built-in, so its own model decides (a model it names allows the call, `inherit` refuses it, and none falls through to `CLAUDE_CODE_SUBAGENT_MODEL` as for `general-purpose`). Other agents are left to their own definitions, and it stands down while `CLAUDE_CODE_SUBAGENT_MODEL_FORCE` or coordinator mode overrides the call's model. It needs python3 only, not git or the mod.
- `email_greeting` refuses an email draft or a Gmail connector send or reply whose body does not open with Good morning, Good afternoon or Good evening for the local time, or opens with Hi, Hello, Hey or Dear. `email_timezone` sets the clock; empty is this machine's. It needs python3 only.
- `restart_on_update` moves an idle session onto a newly installed Claude Code in a new tmux window or Windows Terminal tab, keeping the conversation. It works on Linux and WSL only.
- `budget_mode` tells routed sessions to route work to Sonnet and Haiku while the 5-hour or 7-day usage runs ahead of the time gone, and in frugal runs an Agent call naming Opus, Fable or `best` on Sonnet unless its description says "final review". It routes only sessions launched with `PHYLAX_BUDGET_ROLE=background`, or interactive ones that opt in with `PHYLAX_BUDGET=on`; `/phylax:budget off` pauses the opted-in ones. It reads the usage the status line saves, so the status line needs the snapshot step the doctor prints.

The user switches them on in `/config`. Then they run `/reload-plugins`, and you run the setup skill again so the doctor sees the new values.

## 3. Fix each missing line

| Check | When it matters | What to do |
| --- | --- | --- |
| `mod` | a guard is on | Claude Code 2.1.287 or later runs the guards from a mod, and 2.1.288 fixed that mod breaking Bash in worktree subagents. An older version still runs them from the command hook, so this line is optional. Run the fix line after the user approves; `claude update` moves to the newest version, and the mod loads after the user restarts Claude Code. |
| `fail-closed` | a refusing guard is on | Claude Code 2.1.295 or later honours the hooks' `onFailure`, so a guard that crashes or times out refuses the call. An older version lets that call run, so this line is optional. Run the fix line after the user approves; `claude update` moves to the newest version. |
| `python3` | any option is on | The hooks run on the system python3, 3.9 or newer. The user runs a `sudo` or `xcode-select --install` line with `!`. Run the `uv python install --default 3.12 && uv python update-shell` line after the user approves. |
| `git` | a guard is on | The user runs the fix line with `!`. |
| `proc` | restart_on_update is on | macOS and native Windows have no `/proc`. The user switches the option off there. |
| `launcher` | restart_on_update is on | The restart works only in a session running inside tmux, or inside Windows Terminal under WSL. If tmux is missing, the user runs the install line with `!`. Then the user starts Claude Code inside tmux with `tmux new-session claude`, or under WSL opens it in Windows Terminal. |
| `claude` | restart_on_update is on | The restart starts the `claude` on PATH. Run the fix line after the user approves. |
| `budget` | budget_mode is on | `optional` until a snapshot exists: show the user the `fix:` line, which puts the snapshot in front of their status line command in `settings.json`, and edit it in only after they approve. `ok` names the level and the file read. |
| `state-dir` | restart_on_update is on | Run the fix line it prints after the user approves. A folder owned by another user has no fix line; the user sets `XDG_RUNTIME_DIR` to a private folder. |

For `restart_on_update` under Windows Terminal, the old tab closes itself only with the shell snippet in [Restart on update](https://ajbarea.github.io/techne/configuration/#restart-on-update). Offer to show it.

## Failure behavior

Every refusing PreToolUse hook in `hooks/hooks.json` sets `"onFailure": "block"`, so the guards fail closed: a crash, an exit code other than 0 or 2, a hook that cannot start, or its timeout refuses the call. The git checks share a 50 s budget, so a slow repo is refused with phylax's own text before the timeout. A crash, a missing `python3` and a `python3` that fails (a macOS stub) print a refusal that names the guard, the error and the option to switch off. Without a working `python3`, a Bash call is refused when its command names `git` or `gh` while a blocking git guard is on, holds a shape word while a shape guard is on, or holds a `\u` escape while either is on; a `python3` that fails after reading the call refuses every call while such a guard is on, and without `grep` or a command field the whole hook input is checked. The warning guard alone refuses nothing short of the 75 s hook timeout; a crash with only it on reaches Claude as a warning. With a guard's options all off the hook exits 0 at once. Claude Code before 2.1.295 ignores the field and lets such a call through; the doctor's `fail-closed` line says which applies. Tell the user a refusal that names a hook failure means the hook broke, and `/phylax:setup` shows what.

## 4. Check the result

Run the doctor again until it prints `result: ready`.
