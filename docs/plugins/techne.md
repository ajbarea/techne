# techne

techne is a set of Claude Code skills for work in a code repo: build audits, CI log review, pre-merge review, commit plans, GitHub catch-up, cross-repo drift checks, and comment and doc cleanup. The [skill pages](../skills/index.md) describe each one.

## Install

```bash
/plugin marketplace add ajbarea/techne
/plugin install techne@techne
```

Then run `/techne:setup`. It checks git, the GitHub CLI and its sign-in, uv, python3 3.11 or newer, tmux, Playwright's Chromium, the repo's `.claude/skill-context.md` and `~/.claude/techne.toml`. It only reads, and prints the install command for anything missing. Claude follows the steps in the [setup runbook](https://github.com/ajbarea/techne/blob/main/plugins/techne/AGENTS.md).

## First use

- In a repo with a Makefile, run `/techne:audit` to check the build before you push. It reads the `## audit` section of `.claude/skill-context.md`; [Conventions](../conventions.md) describes the file.
- In any GitHub repo, run `/techne:catchup` to see what changed since you last looked.

## Troubleshooting

- **`gh` or `gh-auth` is missing.** Install the GitHub CLI with the doctor's fix line, then run `!gh auth login --hostname github.com` in Claude Code. On GitHub Enterprise, set `GH_HOST` to your host first; the doctor and gh both read it.
- **`skill-context` is missing.** `/techne:setup` offers to copy the skeleton into the repo. Keep the sections for the skills you use.
- **`techne.toml` is missing.** Only `techne:sisters` reads it. The schema is on the [configuration page](../configuration.md).
- **`python3` is older than 3.11.** `techne:sisters` reads TOML with `tomllib`. `uv python install --default 3.12` puts a newer `python3` in `~/.local/bin`.
- **Chromium does not start on Linux.** Its system libraries are missing. Run `uv run --no-project --with playwright==1.63.0 playwright install-deps chromium`, which calls `sudo apt` itself.
- **A skill is not listed.** Run `/reload-plugins`, then `/skills`.
