# Configuration

## `~/.claude/techne.toml`

`techne:sisters` (and any future cross-repo skill) reads `~/.claude/techne.toml` at runtime. User-controlled config that lists the active sister repos to compare against.

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
| `workspace_root` | string | yes | Absolute path to the parent directory containing your sister repos. |
| `sisters[].name` | string | yes | Directory name under `workspace_root`. |
| `sisters[].status` | string | no | Defaults to `"active"`. Set to `"backburner"` to skip without removing. |
| `sisters[].kind` | string | no | A roster label. `"team"` marks a repo other people own, which `techne:sisters` exempts from solo-only conventions such as the README masthead. |

### Status semantics

- **`active`**: included in cross-repo audits, drift checks, sync sweeps.
- **`backburner`**: skipped but not deleted. Used for repos you want to remember without actively maintaining.

## Guards

techne ships three `PreToolUse` hooks on the Bash tool. Each is off until you switch it on in `/config`, under the techne plugin's options.

| Option | What it does |
|---|---|
| `block_attribution_trailers` | Refuses `git commit` and `gh pr create`, `gh pr edit` or `gh pr merge` when the message, title or body has a line matching `Claude-Session`, `claude.ai/code/session`, `Co-Authored-By: Claude` or `Generated with Claude Code`. |
| `block_commits_md` | Refuses `git add` when it would stage a file named `COMMITS.md` (exact case, any directory), and `git commit` when the commit would include one. A commit that removes it passes. |
| `warn_main_checkout_commit` | Warns, without blocking, when `git commit` runs in a repo's main checkout while linked worktrees exist. |

A refusal tells Claude the reason, so it can fix the command and retry. The hooks still apply in `bypassPermissions` mode.

What each guard reads:

- Messages from `-m`, `--message`, `--trailer`, `-F`/`--file`, `--title`, `--body` and `--body-file`, including heredocs and line continuations, the file in a `"$(cat FILE)"` or `"$(< FILE)"` value, and variables set earlier in the command. A message file is read from disk. When the same command may write it (stdin, a redirect or `tee`, or a file that does not exist yet), the arguments of `echo` and `printf` in that command are scanned too. A `grep -v` or `sed` that strips a line is not.
- The repo the command runs in. It follows `cd` (including `cd -`), `pushd`, `popd`, `git -C`, `env -C` and `sudo -D`, expanding variables from the environment or set earlier in the command, and drops a `cd` made inside `( ... )`. It looks through wrappers such as `time`, `sudo`, `nice`, `timeout` and `xargs`, and through `if`, `{ ... }`, `!` and loop keywords. `git stage` counts as `git add`, and `gh pr new` as `gh pr create`.
- For `COMMITS.md`, `git add --dry-run` with your arguments, so `.`, `-A`, globs and directories are covered and exclude pathspecs such as `':!COMMITS.md'` are respected. At commit time it checks the index, plus the working tree for `-a` and pathspec commits.

To turn an enabled guard off in one repo, set the option's camelCase name in that repo's git config:

```bash
git config techne.blockAttributionTrailers false
git config techne.blockCommitsMd false
git config techne.warnMainCheckoutCommit false
```

The hook runs on every Bash call, since Claude Code's `Bash(git *)` filter skips commands such as `time git add`. With every option off, it stops in the shell and `python3` never starts. Once one is on, it needs `python3` 3.9 or newer on `PATH`, adds about 40 ms to each Bash call, and runs read-only git commands in the target repo. Parsing is best effort: a git command inside `$(...)` or `bash -c` is not checked, and neither are paths that `xargs` reads from stdin or that `$(...)` produces. A `COMMITS.md` staged that way in one Bash call is still refused by the next call's `git commit`, but not by a commit later in the same call. A command that creates `COMMITS.md` and then runs a broad `git add` (`.`, `-A`) is refused.

## Restart on update

Claude Code updates itself on disk, but an open session keeps running the old binary until you restart it. With `restart_on_update` switched on in `/config`, techne restarts an idle session onto the installed version and keeps the conversation.

It runs on the `idle_prompt` notification, which Claude Code sends about a minute after a turn ends, and only when you appear to be away from that terminal and have not typed since. A session in the tab you are looking at is not restarted, and Claude Code does not send the notification again when you leave later, so that session moves after its next reply. The hook reads the session's own `~/.claude/sessions/<pid>.json` and goes ahead only when all of these hold:

- The session's version differs from the version of the `claude` on `PATH`.
- Its status is `idle`. A background Bash job or a subagent's tool call reads as `shell`, and a turn in progress reads as `busy`.
- No subagent has started without stopping. The hook counts them from `SubagentStart` and `SubagentStop`.
- The session's last turn ended with no background task running and no session cron (`/loop`, CronCreate) scheduled, as the `Stop` hook reports them. A session cron ends with the process, so a session that has one is never restarted. Until a turn has ended with the option on, the session is not restarted.
- It is an interactive session, and its pid still belongs to the process that wrote the file.

It then opens a new tmux window, when the session runs in tmux, or a new Windows Terminal tab, when it runs in WSL. That window counts down 15 seconds, and any key cancels. A cancel holds until the next update. When the countdown ends, the handoff checks every condition again, then:

1. Sends SIGTERM to the old process and waits up to 10 seconds for it to exit. If it does not exit, it is left running. The handoff never sends SIGKILL.
2. Closes the old shell (tmux respawns the old pane in place).
3. Runs `claude --resume <session id>` from the directory the session started in, on the model, effort and permission mode the session has now. The model is the one its latest reply used, and the effort and permission mode are the ones its last turn ended with, so `/model`, `/effort` and shift+tab changes carry over; a `[1m]` model chosen at launch is kept as launched. The launch flags `--agent`, `--agents`, `--settings`, `--setting-sources`, `--plugin-dir`, `--add-dir`, `--mcp-config`, `--strict-mcp-config`, `--allowedTools`, `--disallowedTools`, `--fallback-model`, the system-prompt flags, `--dangerously-skip-permissions`, `--chrome`, `--ide` and `--verbose` carry over too. A positional prompt and the session flags (`--resume`, `--continue`, `--session-id`, `--worktree`, `--name`) do not.

When Claude exits in the new tab, you are left in a login shell, as before.

In any other terminal, the hook tells you once per session that it cannot restart there and does nothing else. Sessions started with `--bg` are never restarted.

### Closing the old Windows Terminal tab

Windows Terminal's default `closeOnExit` closes a tab only when its shell exits with code 0, and a shell ended by a signal exits with 129. To let the old tab close cleanly, add this to `~/.bashrc`:

```bash
# techne restart_on_update: close this tab once its Claude session has moved to a new one
__techne_restart_close() {
  local m="${XDG_RUNTIME_DIR:-/tmp}/techne-restart-$UID/close-$$"
  if [ -e "$m" ]; then rm -f "$m"; exit 0; fi
}
PROMPT_COMMAND="__techne_restart_close${PROMPT_COMMAND:+;$PROMPT_COMMAND}"
```

Without it, the handoff sends the shell SIGHUP, and the tab stays open showing the exit code until you close it. Tabs the handoff opens close themselves either way. Only the top shell of a tab is closed. A session started from a nested shell or an editor's terminal leaves its shell alone.

### Limits

- The session file is undocumented Claude Code state. When a field is missing or changes meaning, the check fails and nothing restarts.
- Text typed into the prompt but not sent is lost on restart. The countdown takes focus, so a key pressed in the new tab cancels the restart.
- `restart_on_update` needs `python3` 3.9 or newer, and `tmux`, or `wt.exe` under WSL. It writes its state and a log to `$XDG_RUNTIME_DIR/techne-restart-<uid>/`.

## Per-skill configuration

Most skills read additional repo-local config when needed (e.g. `techne:audit` looks for a `Makefile`; `techne:docs-site` looks for `zensical.toml`). See each skill's page for specifics.

## How it fits together

```
~/.claude/techne.toml      ← user-controlled sister-repo registry
~/.claude/plugins/...      ← installed techne skills and hooks
~/.claude/settings.json    ← pluginConfigs: hook options set in /config
<repo>/.claude/...         ← per-repo overrides (skill-context, etc.)
<repo>/Makefile, logs/, zensical.toml, ... ← what individual skills read
```
