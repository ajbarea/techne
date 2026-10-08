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
| `workspace_root` | string | yes | Absolute path to the parent directory containing your sister repos. |
| `sisters[].name` | string | yes | Directory name under `workspace_root`. |
| `sisters[].status` | string | no | Defaults to `"active"`. Set to `"backburner"` to skip without removing. |
| `sisters[].kind` | string | no | A roster label. `"team"` marks a repo other people own, which `techne:sisters` exempts from solo-only conventions such as the README masthead. |

### Status semantics

- **`active`**: included in cross-repo audits, drift checks, sync sweeps.
- **`backburner`**: skipped but not deleted. Used for repos you want to remember without actively maintaining.

## Guards

phylax's guards run from a [mod](https://code.claude.com/docs/en/plugins/mods/overview): a hooks module, `hooks/register.ts`, that Claude Code 2.1.287 or later loads into the session and that checks the main conversation's commands. A `PreToolUse` command hook checks subagents' commands, and every command when the module does not load (an older Claude Code, or an organization that allows only its own mods); it stands down for a command the module already checked. Each guard is off until you switch it on in `/config`, under the phylax plugin's options.

| Option | What it does |
|---|---|
| `block_attribution_trailers` | Blanks the commit trailer and pull request footer Claude Code asks Claude to write, so neither is composed. Also refuses `git commit` and `gh pr create`, `gh pr edit` or `gh pr merge` when the message, title or body has a line matching `Claude-Session`, `claude.ai/code/session`, `Co-Authored-By: Claude` or `Generated with Claude Code`. |
| `block_commits_md` | Refuses `git add` when it would stage a file named `COMMITS.md` (exact case, any directory), and `git commit` when the commit would include one. A commit that removes it passes. |
| `warn_main_checkout_commit` | Warns, without blocking, when `git commit` runs in a repo's main checkout while linked worktrees exist. |

A refusal tells Claude the reason, so it can fix the command and retry. A warning reaches Claude after the command's output and shows as a dim line in the transcript. The guards run before the permission check, so they apply in `bypassPermissions` mode. When a blocking guard is on and the check itself fails (it errors, git times out, or `python3` cannot start), the command is refused rather than run unchecked.

What each guard reads:

- Messages from `-m`, `--message`, `--trailer`, `-F`/`--file`, `--title`, `--body` and `--body-file`, including heredocs and line continuations, the file in a `"$(cat FILE)"` or `"$(< FILE)"` value, and variables set earlier in the command. A message file is read from disk. When the same command may write it (stdin, a redirect or `tee`, or a file that does not exist yet), the arguments of `echo` and `printf` in that command are scanned too. A `grep -v` or `sed` that strips a line is not.
- The repo the command runs in. It follows `cd` (including `cd -`), `pushd`, `popd`, `git -C`, `env -C` and `sudo -D`, expanding variables from the environment or set earlier in the command, and drops a `cd` made inside `( ... )`. It looks through wrappers such as `time`, `sudo`, `nice`, `timeout` and `xargs`, and through `if`, `{ ... }`, `!` and loop keywords. `git stage` counts as `git add`, and `gh pr new` as `gh pr create`.
- For `COMMITS.md`, `git add --dry-run` with your arguments, so `.`, `-A`, globs and directories are covered and exclude pathspecs such as `':!COMMITS.md'` are respected. At commit time it checks the index, plus the working tree for `-a` and pathspec commits.

To turn an enabled guard off in one repo, set the option's camelCase name in that repo's git config:

```bash
git config phylax.blockAttributionTrailers false
git config phylax.blockCommitsMd false
git config phylax.warnMainCheckoutCommit false
```

These keys were `techne.*` before the guards moved to the phylax plugin; rename any you set.

The mod checks every Bash command that names `git` or `gh` anywhere, so `time git add` and `sudo git commit` are covered. With every option off it registers no Bash hook. Once one is on, it needs `python3` 3.9 or newer on `PATH`, runs read-only git commands in the target repo, and starts one `python3` process for each `git` or `gh` command it checks. A command without `git` or `gh` starts no process. Parsing is best effort: a git command inside `$(...)` or `bash -c` is not checked, and neither are paths that `xargs` reads from stdin or that `$(...)` produces. A `COMMITS.md` staged that way in one Bash call is still refused by the next call's `git commit`, but not by a commit later in the same call. A command that creates `COMMITS.md` and then runs a broad `git add` (`.`, `-A`) is refused.

## Restart on update

Claude Code updates itself on disk, but an open session keeps running the old binary until you restart it. With `restart_on_update` switched on in `/config`, phylax restarts an idle session onto the installed version and keeps the conversation.

It runs on the `idle_prompt` notification, which Claude Code sends about a minute after a turn ends, and only when you appear to be away from that terminal and have not typed since. A session in the tab you are looking at is not restarted, and Claude Code does not send the notification again when you leave later, so that session moves after its next reply. The hook goes ahead only when all of these hold:

- The `claude` on `PATH` is a newer version than the session runs. A session on a newer build is never moved to an older one.
- The session's own `~/.claude/sessions/<pid>.json` reads `idle`, the session is interactive, and its pid still belongs to the process that wrote the file.
- The session's last turn, ended in this same process, finished with no background task or subagent running and no session cron (`/loop`, CronCreate) scheduled, as the `Stop` hook reports them. A session cron ends with the process, so a session that has one is not restarted. Submitting a prompt clears that record until the turn ends, so a turn you interrupt with Esc, which skips `Stop`, leaves nothing to go on, and the session waits for its next completed turn.

It then opens a new tmux window, when the session runs in tmux, or a new Windows Terminal tab, when it runs in WSL. That window counts down 15 seconds, and any key cancels. A cancel holds until the next update. When the countdown ends, the handoff checks every condition again, then:

1. Checks that the session's directory still exists, then sends SIGTERM to the old process and waits for it to exit. After 10 seconds it keeps waiting and says so, and any key stops the wait. A process that never exits is left running, and the window prints the command to resume it once it does. The handoff never sends SIGKILL.
2. Closes the old shell, or in tmux respawns the old pane in place. Either happens only when the old session was the pane's first process, or the only child of the tab's or pane's top shell. A shell with a job, an editor's terminal or a nested shell is left open, and in tmux the session resumes in the new window instead.
3. Runs `claude --resume <session id>` from the directory the session started in, with its launch flags `--model`, `--effort`, `--permission-mode`, `--agent`, `--agents`, `--settings`, `--setting-sources`, `--plugin-dir`, `--add-dir`, `--mcp-config`, `--strict-mcp-config`, `--allowedTools`, `--disallowedTools`, `--fallback-model`, the system-prompt flags, `--dangerously-skip-permissions`, `--allow-dangerously-skip-permissions`, `--chrome`, `--ide` and `--verbose`. Every other argument is dropped, including a positional prompt and the session flags (`--resume`, `--continue`, `--session-id`, `--worktree`, `--name`). Once the old process has exited, the session always resumes: when the old pane or tab cannot take it, or the directory has gone, it resumes in the new window instead.

The resumed session keeps the effort and permission mode its last turn ended with. Unless that turn ended in bypass mode, `--dangerously-skip-permissions` becomes `--allow-dangerously-skip-permissions`, so bypass stays one shift+tab away instead of switching back on. For the model, `/model` saves its choice as your default, so the resume normally starts on the same model and keeps aliases such as `opusplan` and a `[1m]` context window. An `ANTHROPIC_MODEL` set for the old process becomes `--model`, since the new window does not inherit it. Only when the model a resume would start on (the `--model` flag, else your settings) is a different family from the session's latest reply, as happens after another session changes the default, is that reply's exact model id passed.

When Claude exits in the new tab, you are left in a login shell, as before.

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

## Per-skill configuration

Most skills read additional repo-local config when needed (e.g. `techne:audit` looks for a `Makefile`; `techne:docs-site` looks for `zensical.toml`). See each skill's page for specifics.

## How it fits together

```
~/.claude/techne.toml      ← user-controlled sister-repo registry
~/.claude/plugins/...      ← installed techne, graphe, dokimasia, phylax and keryx plugins
~/.claude/settings.json    ← pluginConfigs: hook options set in /config
<repo>/.claude/...         ← per-repo overrides (skill-context, etc.)
<repo>/Makefile, logs/, zensical.toml, ... ← what individual skills read
```
