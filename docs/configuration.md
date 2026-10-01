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

## Per-skill configuration

Most skills read additional repo-local config when needed (e.g. `techne:audit` looks for a `Makefile`; `techne:docs-site` looks for `zensical.toml`). See each skill's page for specifics.

## How it fits together

```
~/.claude/techne.toml      ← user-controlled sister-repo registry
~/.claude/plugins/...      ← installed techne skills and hooks
~/.claude/settings.json    ← pluginConfigs: guard options set in /config
<repo>/.claude/...         ← per-repo overrides (skill-context, etc.)
<repo>/Makefile, logs/, zensical.toml, ... ← what individual skills read
```
