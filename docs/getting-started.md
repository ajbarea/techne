# Getting Started

## Install

Add the marketplace and install the plugin from inside Claude Code:

```bash
/plugin marketplace add ajbarea/techne
/plugin install techne@techne
```

That's it. Skills become available as `techne:<name>` and invoke the same way as any other Claude Code skill.

## First Use

Pick a skill that matches what you're trying to do:

| Want to... | Use |
|---|---|
| Run repo's make targets and verify the log archive | [`techne:audit`](skills/audit.md) |
| Plan commits from a dirty working tree | [`techne:auto-commit`](skills/auto-commit.md) |
| Investigate failing/noisy CI on a PR | [`techne:ci-audit`](skills/ci-audit.md) |
| Trim AI-slop from comments and docstrings | [`techne:deslop`](skills/deslop.md) |
| Maintain a Zensical docs site | [`techne:docs-site`](skills/docs-site.md) |
| Verify a `.md` file's claims still match the code | [`techne:docsync`](skills/docsync.md) |
| Rewrite docstrings grounded in the implementation | [`techne:reslop`](skills/reslop.md) |
| Audit your sister repos for drift | [`techne:sisters`](skills/sisters.md) |
| Spectate a live Claude REPL session | [`techne:theoros`](skills/theoros.md) |

## Sister Repo Setup

Several skills (`techne:sisters` especially) read `~/.claude/techne.toml` to know which repos belong to your workspace. See [Configuration](configuration.md) for the schema.

A minimal `~/.claude/techne.toml`:

```toml
github_user = "ajbarea"
workspace_root = "/home/ajbar/ajsoftworks"

[[sisters]]
name = "phalanx-fl"
status = "active"

[[sisters]]
name = "vFL"
status = "active"

[[sisters]]
name = "kourai-khryseai"
status = "active"
```

## Next Steps

- [Browse all skills](skills/index.md)
- [Configuration reference](configuration.md)
- [`techne` on GitHub](https://github.com/ajbarea/techne)
