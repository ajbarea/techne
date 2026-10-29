---
description: "Configuration reference: the techne.toml schema for sister repos, phylax guard and restart options, and per-skill config."
---

# Configuration

## `~/.claude/techne.toml`

`techne:sisters` and `techne:catchup` read `~/.claude/techne.toml` at runtime. User-controlled config that lists the active sister repos to compare against.

### Schema

```toml
github_user = "your-github-username"
workspace_root = "/path/to/your/workspace"

[[sisters]]
name = "repo-one"
status = "active"

[[sisters]]
name = "repo-two"
status = "active"

[[sisters]]
name = "repo-three"
status = "active"
```

### Fields

| Field | Type | Required | Notes |
|---|---|---|---|
| `github_user` | string | yes | Your GitHub username; used to construct repo URLs. |
| `workspace_root` | string | yes | Path to the parent directory containing your sister repos, absolute or starting with `~`; a relative path is an error. |
| `sisters[].name` | string | yes | Directory name under `workspace_root`. |
| `sisters[].status` | string | no | Defaults to `"active"`, in any case. Set to `"backburner"` to skip without removing. |
| `sisters[].kind` | string | no | `"team"` marks a repo other people work in: `techne:sisters` exempts it from solo-only conventions such as the README masthead, and `docsync` and `ci-audit` ask before acting on it. `"solo"` on a fork says the fork is your own line of work, so those skills may act on it ([Solo and team repos](conventions.md#solo-and-team-repos)). Any case. Omitted: no claim either way. |

### `[board]`

```toml
[board]
owner = "your-github-username"
number = 1
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `board.owner` | string | yes | The login that owns the GitHub Projects board. Only issues and PRs in this owner's repos are filed. |
| `board.number` | integer | yes | The project number, from the board's URL or from `/techne:board init`. |

Without the table, `techne:board` and its hook do nothing. With it, a `PostToolUse` hook adds each issue or PR that `gh issue create`, `gh pr create` or a `gh api` POST to `.../issues` or `.../pulls` opens to the board and sets its Status; an item already on the board keeps its Status. The table is read with Python's `tomllib`, so the hook needs python3 3.11 and does nothing below it or when the file cannot be read or is not valid TOML (`/techne:board show` names the error). The board's IDs are cached in `~/.cache/techne/board-<owner>-<number>.json`. See [`techne:board`](skills/board.md).

### Status semantics

- **`active`**: included in cross-repo audits, drift checks, sync sweeps.
- **`backburner`**: skipped but not deleted. Used for repos you want to remember without actively maintaining.

## Guards

phylax's guards run from a [mod](https://code.claude.com/docs/en/plugins/mods/overview): a hooks module, `hooks/register.ts`, that Claude Code 2.1.287 or later loads into the session (2.1.288 or later for Bash in worktree subagents) and that checks the main conversation's commands. A `PreToolUse` command hook checks subagents' commands, and every command when the module does not load (an older Claude Code, or an organization that allows only its own mods); it stands down for a command the module already checked. Each guard is off until you switch it on in `/config`, under the phylax plugin's options.

| Option | What it does |
|---|---|
| `block_attribution_trailers` | Blanks the commit trailer and pull request footer Claude Code asks Claude to write, so neither is composed. Also refuses `git commit` and `gh pr create`, `gh pr edit` or `gh pr merge` when the message, title or body has a line matching `Claude-Session`, `claude.ai/code/session`, `Co-Authored-By: Claude` or `Generated with Claude Code`. |
| `block_commits_md` | Refuses `git add` when it would stage a file named `COMMITS.md` (exact case, any directory), and `git commit` when the commit would include one. A commit that removes it passes. |
| `warn_main_checkout_commit` | Warns, without blocking, when `git commit` runs in a repo's main checkout while linked worktrees exist. |
| `block_long_bodies` | Refuses `gh pr create`, `gh pr edit`, `gh pr comment`, `gh pr review`, `gh issue create`, `gh issue edit`, `gh issue comment`, and `gh api` writes to an issue, a pull request or their comments, when the body's visible text runs past its budget: about 150 words for a PR or a comment, 300 for an issue (a tenth more passes). Visible means outside `<details>` blocks, HTML comments, code and link targets, counted as graphe counts a markdown page. The body is read from `--body`, `--body-file`, a heredoc, `-f body=`, `-F body=@file` or `--input`. A body carrying a `budget:` marker is refused too: GitHub shows the raw text in mail and notifications. Sentences over 25 words are reported without refusing. The fix is a short top (why, what in a small table, status) with the depth folded into `<details>`. |
| `block_secrets` | Refuses `git commit` when the lines it would add hold a secret, and `git push` when a commit it would send does. A commit any remote already holds is not scanned again: it is already on a server (and GitHub's push protection covers public repos). The commit scan stages what the command would commit (an earlier `git add` in the same command, `-a`, pathspecs) into a copy of the index, so your index is untouched. Pushes and, by default, commits are scanned by [gitleaks](https://github.com/gitleaks/gitleaks) 8.19 or newer; with `GITGUARDIAN_API_KEY` set and `ggshield` installed, commits use GitGuardian's detectors, the same as its pull request check. The refusal names the file, line and rule, never the value. Each refusal, and each scan that gave no verdict, is one JSON line in `~/.local/state/phylax/secret-gate.jsonl` (256 KB, then rotated). With no scanner installed it refuses every commit and push until you install one or switch it off. A false positive goes in `.gitleaksignore`. Test fixtures use values the scanners accept as placeholders or make one at runtime (`secrets.token_urlsafe()`), never a real-looking literal. |
| `require_subagent_model` | Refuses an `Agent` call to a built-in agent type that runs on the session's model (`general-purpose`, `claude`, `Explore` or `Plan`, or no type) when it names no `model`. Other agent types are left to their own definitions, since a model named in the call would override one the definition pins. A managed, project or user agent that reuses one of those names replaces the built-in, so its own `model` decides: a model it names allows the call, `inherit` refuses it, and none is treated like `general-purpose`'s. Definitions passed with `--agents` or found in an `--add-dir` folder are not visible to the hook. A `CLAUDE_CODE_SUBAGENT_MODEL` that names a model (not `inherit`) satisfies it for `general-purpose` and `claude`; `Explore` and `Plan` pin `inherit`, which wins over that variable. While `CLAUDE_CODE_SUBAGENT_MODEL_FORCE` or `CLAUDE_CODE_COORDINATOR_FORCE_WORKER_INHERIT_MODEL` is set, Claude Code drops or withholds the call's model, so the guard stands down. Runs from the `PreToolUse` command hook, needs `python3` only, and checks the `Agent` tool call only, so agents a Workflow script spawns are not covered. |
| `email_greeting` | Refuses an epistole `create_draft` or `update_draft`, or a Gmail connector `create_draft`, `update_draft`, `send_message` or `reply` (a second Gmail connector too), whose body does not open with `Good morning` before 12:00, `Good afternoon` from 12:00 to 17:00 or `Good evening` after, or opens with `Hi`, `Hello`, `Hey` or `Dear`. A first line in another language passes: one opening with a common Spanish, Portuguese, French, Italian or German greeting (`Hola`, `Bonjour`, `Guten Tag`), or holding a letter outside ASCII. Within 10 minutes of 12:00 or 17:00 either greeting passes. It checks both the plain-text body and the HTML body's visible text; an update that keeps the body passes. `email_timezone` sets the clock (an IANA name such as `America/New_York`; empty is this machine's local time), and a name the system does not know refuses every draft until it is fixed. Needs `python3` only. |

A refusal tells Claude the reason, so it can fix the command and retry. A warning reaches Claude after the command's output and shows as a dim line in the transcript. The guards run before the permission check, so they apply in `bypassPermissions` mode. When a blocking git guard is on and the check itself fails (it errors, git times out, or `python3` cannot start), the command is refused rather than run unchecked. `require_subagent_model` sets a default rather than protecting data, so when its check cannot run (`python3` cannot start, or the call's input is not an object) the call goes ahead and the reason goes to stderr. `email_greeting` enforces a house style, so it does the same.

What each guard reads:

- Messages from `-m`, `--message`, `--trailer`, `-F`/`--file`, `--title`, `--body` and `--body-file`, including heredocs and line continuations, the file in a `"$(cat FILE)"` or `"$(< FILE)"` value, and variables set earlier in the command. A message file is read from disk. When the same command may write it (stdin, a redirect or `tee`, or a file that does not exist yet), the arguments of `echo` and `printf` in that command are scanned too. A `grep -v` or `sed` that strips a line is not.
- The repo the command runs in. It follows `cd` (including `cd -`), `pushd`, `popd`, `git -C`, `env -C` and `sudo -D`, expanding variables from the environment or set earlier in the command, and drops a `cd` made inside `( ... )`. It looks through wrappers such as `time`, `sudo`, `nice`, `timeout` and `xargs`, and through `if`, `{ ... }`, `!` and loop keywords. `git stage` counts as `git add`, and `gh pr new` as `gh pr create`.
- For `COMMITS.md`, `git add --dry-run` with your arguments, so `.`, `-A`, globs and directories are covered and exclude pathspecs such as `':!COMMITS.md'` are respected. At commit time it checks the index, plus the working tree for `-a` and pathspec commits.

To turn an enabled git guard off in one repo, set the option's camelCase name in that repo's git config (`require_subagent_model` has no per-repo key):

```bash
git config phylax.blockAttributionTrailers false
git config phylax.blockCommitsMd false
git config phylax.warnMainCheckoutCommit false
git config phylax.blockSecrets false
```

These keys were `techne.*` before the guards moved to the phylax plugin; rename any you set.

The mod checks every Bash command that names `git` or `gh` anywhere, so `time git add` and `sudo git commit` are covered. With every option off it registers no Bash hook. Once one is on, it needs `python3` 3.9 or newer on `PATH`, runs read-only git commands in the target repo, and starts one `python3` process for each `git` or `gh` command the module checks. The command hook that backs it up also starts one `python3` per Bash call while a guard is on, and exits at once for a command without `git` or `gh`, so a git or gh command starts two processes and any other Bash command one. Parsing is best effort: a git command inside `$(...)` or `bash -c` is not checked, and neither are paths that `xargs` reads from stdin or that `$(...)` produces. A `COMMITS.md` staged that way in one Bash call is still refused by the next call's `git commit`, but not by a commit later in the same call. A command that creates `COMMITS.md` and then runs a broad `git add` (`.`, `-A`) is refused.

## Restart on update

Claude Code updates itself on disk, but an open session keeps running the old binary until you restart it. With `restart_on_update` switched on in `/config`, phylax restarts an idle session onto the installed version and keeps the conversation.

It runs on the `idle_prompt` notification, which Claude Code sends about a minute after a turn ends, and only when you appear to be away from that terminal and have not typed since. A session in the tab you are looking at is not restarted, and Claude Code does not send the notification again when you leave later, so that session moves after its next reply. The hook goes ahead only when all of these hold:

- The `claude` on `PATH` is a newer version than the session runs. A session on a newer build is never moved to an older one.
- The session's own `~/.claude/sessions/<pid>.json` reads `idle`, the session is interactive, and its pid still belongs to the process that wrote the file.
- The session's last turn, ended in this same process, finished with no background task or subagent running and no session cron (`/loop`, CronCreate) scheduled, as the `Stop` hook reports them. A session cron ends with the process, so a session that has one is not restarted. Submitting a prompt clears that record until the turn ends, so a turn you interrupt with Esc, which skips `Stop`, leaves nothing to go on, and the session waits for its next completed turn.

It then opens a new tmux window, when the session runs in tmux, or a new Windows Terminal tab, when it runs in WSL. That window counts down 15 seconds, and any key cancels. A cancel holds until the next update. When the countdown ends, the handoff checks every condition again, then:

1. Checks that the session's directory still exists, then sends SIGTERM to the old process and waits for it to exit. After 10 seconds it keeps waiting and says so, and any key stops the wait. A process that never exits is left running, and the window prints the command to resume it once it does. The handoff never sends SIGKILL.
2. Closes the old shell, or in tmux respawns the old pane in place. Either happens only when the old session was the pane's first process, or the only child of the tab's or pane's top shell. A shell with a job, an editor's terminal or a nested shell is left open, and in tmux the session resumes in the new window instead.
3. Runs `claude --resume <session id>` from the directory the session started in, with its launch flags `--model`, `--effort`, `--permission-mode`, `--agent`, `--agents`, `--settings`, `--setting-sources`, `--plugin-dir`, `--add-dir`, `--mcp-config`, `--strict-mcp-config`, `--allowedTools`, `--disallowedTools`, `--fallback-model`, the system-prompt flags, `--dangerously-skip-permissions`, `--allow-dangerously-skip-permissions`, `--chrome`, `--ide` and `--verbose`. Every other argument is dropped, including a positional prompt and the session flags (`--resume`, `--continue`, `--fork-session`, `--session-id`, `--worktree`, `--name`). Once the old process has exited, the session always resumes: when the old pane or tab cannot take it, or the directory has gone, it resumes in the new window instead.

The resumed session keeps the effort and permission mode its last turn ended with. Unless that turn ended in bypass mode, `--dangerously-skip-permissions` becomes `--allow-dangerously-skip-permissions`, so bypass stays one shift+tab away instead of switching back on. For the model, `/model` saves its choice as your default, so the resume normally starts on the same model and keeps aliases such as `opusplan` and a `[1m]` context window. An `ANTHROPIC_MODEL` set for the old process becomes `--model`, since the new window does not inherit it. Only when the model a resume would start on (the `--model` flag, else your settings) is a different family from the session's latest reply, as happens after another session changes the default, is that reply's exact model id passed.

When Claude exits in the new tab, you are left in a login shell, as before.

When a newer version is installed but the last turn holds the session (a background task, a subagent or a session cron still running, no completed turn recorded, or the turn recorded by another process), the hook writes the reason to its log, `$XDG_RUNTIME_DIR/phylax-restart-<uid>/log`. Each hold is logged once, and again when its reason changes or after it has lifted, so the log answers why a session has not moved.

A launcher that fails (tmux or `wt.exe` exiting non-zero) frees the next idle prompt to try again. A launch that reports success but whose handoff never runs, such as a Windows Terminal tab that timed out, holds that session for 10 minutes before the next attempt.

In any other terminal, the hook tells you once per session that it cannot restart there and does nothing else. Sessions started with `--bg` are never restarted.

### Closing the old Windows Terminal tab

Windows Terminal's default `closeOnExit` closes a tab only when its shell exits with code 0, and a shell ended by a signal exits with 129. To let the old tab close cleanly, add this to `~/.bashrc` (bash 5.1 or newer, which runs every entry of a `PROMPT_COMMAND` array):

```bash
# phylax restart_on_update: close this tab once its Claude session has moved to a new one
__phylax_restart_close() {
  local m="${XDG_RUNTIME_DIR:-/tmp}/phylax-restart-$UID/close-$$"
  if [ -e "$m" ] && [ -z "$(jobs -p)" ]; then rm -f "$m"; exit 0; fi
}
PROMPT_COMMAND+=(__phylax_restart_close)
```

A snippet from before the move to phylax checks `techne-restart-$UID`; replace it with this one.

In zsh, put the same function in `~/.zshrc` and register it with `precmd_functions+=(__phylax_restart_close)` instead of the last line.

Without it, the handoff sends the shell SIGHUP, and the tab stays open showing the exit code until you close it. A shell that has a job by then is left open either way. Tabs the handoff opens close themselves without the snippet.

### Limits

- The session file is undocumented Claude Code state. When a field is missing or changes meaning, the check fails and nothing restarts.
- Text typed into the prompt but not sent is lost on restart. The countdown takes focus, so a key pressed in the new tab cancels the restart.
- A session whose directory path contains `;` is not restarted under Windows Terminal, which reads `;` as a separator between its own commands.
- `restart_on_update` works on Linux and WSL only, since it reads `/proc`. It needs `python3` 3.9 or newer, and `tmux`, or `wt.exe` under WSL. It keeps its state and a log in `$XDG_RUNTIME_DIR/phylax-restart-<uid>/`, or under `/tmp` when that is unset, and does nothing unless that directory is yours and private.

## Budget mode

`budget_mode` routes work to cheaper models while the usage allowance burns faster than time passes. Claude Code hands the 5-hour and 7-day `rate_limits` only to the [status line](https://code.claude.com/docs/en/statusline), never to hooks, so the status line saves them and the hooks read the saved copy.

**Set it up.** Switch `budget_mode` on in `/config`, start a new session (its SessionStart hook copies `budget_snapshot.py` to the plugin's data folder, a path that survives plugin updates), and put the copy in front of your status line command in `settings.json`. `/phylax:setup` prints the line with the real path:

```json
"statusLine": {
  "type": "command",
  "command": "{ python3 ~/.claude/plugins/data/phylax-techne/budget_snapshot.py || cat; } | <your status line command>"
}
```

The snapshot passes the status line's input through unchanged, so whatever followed still renders, and `|| cat` keeps it rendering if the copy is ever missing. With no status line of your own, use `python3 <copy> > /dev/null` so the payload is not printed. Every session on the account writes the one file, and an idle session re-renders with the usage of its last response, so a reading of a window that already reset, or of the same window used less, is dropped; a live window with another reset (the next window, or another account after `/login`) replaces the stored one. An unchanged reading under five minutes old is not rewritten. It writes `phylax-budget.json` in the account's Claude config folder (`$CLAUDE_CONFIG_DIR`, or `~/.claude`), so two accounts keep two files. Pass a path argument, and set `budget_state_file` to the same path, to keep it elsewhere.

**Who pays.** The level routes background agents (sessions launched with `PHYLAX_BUDGET_ROLE=background`) and the interactive sessions you opt in with `PHYLAX_BUDGET=on`. Every other session keeps normal routing, so a deliberately heavy session keeps Opus while the background fleet sees the extra burn in the pace and gets leaner.

| Setting | Effect |
|---|---|
| `PHYLAX_BUDGET_ROLE=background` at launch | The session is routed by the level. |
| `PHYLAX_BUDGET=on` at launch | An interactive session opts in. |
| `PHYLAX_BUDGET=normal` at launch | The session keeps normal routing, whatever its role. |
| [`/phylax:budget off [hours]`](skills/phylax-budget.md) | Opted-in interactive sessions keep normal routing until the pause ends (4 hours by default); `on` ends it, `status` shows it. Background agents keep paying. |

**Levels.** Each window gets a level from its pace, the percent used minus the percent of the window already gone, and the higher window decides. A seat that reports only the 5-hour window still gets a level.

| Level | When (defaults) | What sessions are told |
|---|---|---|
| normal | below both lean marks | Opus writes and reviews. Nothing is added. |
| lean | pace 10 points ahead (`budget_lean_pace`), or 80% used (`budget_lean_used`) | Sonnet implements and runs research and the first review rounds; Opus reviews only the final round of a risky diff; Haiku does mechanical edits and digests. |
| frugal | pace 25 points ahead (`budget_frugal_pace`), or 95% used (`budget_frugal_used`) | Lean, plus no parallel Opus subagents, review rounds capped at 2, and Haiku for every digest. An `Agent` call that names Opus, Fable or `best` runs on Sonnet unless its description contains "final review". |

A routed session hears the table at start when the level is lean or frugal and again each time the level changes; when the level falls back to normal, at a prompt, on resume or after a compaction, it hears one line saying so. Frugal moves a call that names a model above Sonnet (`opus`, `fable`, `best`, or a `claude-opus-` or `claude-fable-` ID) to Sonnet through the hook's `updatedInput`, which replaces a tool's arguments before it runs ([hooks docs](https://code.claude.com/docs/en/hooks#pretooluse-decision-control)), and leaves the permission prompt as it was. That `updatedInput` applies with no permission decision was tested on Claude Code 2.1.302.

**Limits.** A hook cannot change the main session's model; start sessions with `claude --model sonnet` from your launcher for that. The snapshot holds the last value the status line saw, so a level is as fresh as the last response in any session on that account; a snapshot over a day old, or a window past its reset, reads normal. `rate_limits` reaches the status line only on claude.ai Pro and Max plans, or through a Claude apps gateway that sets a spend limit, and only after a session's first response ([status line docs](https://code.claude.com/docs/en/statusline)).

## Per-skill configuration

Most skills read additional repo-local config when needed (e.g. `techne:audit` looks for a `Makefile`; `techne:docs-site` looks for `zensical.toml`). See each skill's page for specifics.

## How it fits together

```
~/.claude/techne.toml      ← user-controlled sister-repo registry
~/.claude/plugins/...      ← installed techne, graphe, dokimasia, heuresis, epistole, schole, phylax and keryx plugins
~/.claude/settings.json    ← pluginConfigs: hook options set in /config
<repo>/.claude/...         ← per-repo overrides (skill-context, etc.)
<repo>/Makefile, logs/, zensical.toml, ... ← what individual skills read
```
