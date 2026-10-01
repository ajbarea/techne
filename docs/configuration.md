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
| `block_commits_md` | Refuses `git add` when it would stage a `COMMITS.md`, and `git commit` when the commit would include one. |
| `warn_main_checkout_commit` | Warns, without blocking, when `git commit` runs in a repo's main checkout while linked worktrees exist. |

A refusal tells Claude the reason, so it can fix the command and retry. The hooks still apply in `bypassPermissions` mode.

What each guard reads:

- Messages from `-m`, `--message`, `--trailer`, `-F`/`--file`, `--title`, `--body` and `--body-file`, including heredocs. A message file is read from disk; if it does not exist yet, the whole command is scanned.
- The repo the command runs in, following `cd <dir> &&` and `git -C <dir>`.
- For `COMMITS.md`, `git add --dry-run` with your arguments, so `.`, `-A`, globs and directories are covered and exclude pathspecs such as `':!COMMITS.md'` are respected. At commit time it checks the index, plus the working tree for `-a` and pathspec commits.

To turn an enabled guard off in one repo, set the option's camelCase name in that repo's git config:

```bash
git config techne.blockAttributionTrailers false
git config techne.blockCommitsMd false
git config techne.warnMainCheckoutCommit false
```

The hooks need `python3` on `PATH`. They run read-only git commands in the target repo. Parsing is best effort: a git command inside `$(...)` or `bash -c` is not checked.

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
