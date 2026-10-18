---
description: techne plugin, the code-repo skills for Claude Code. Install it, run /techne:setup, then audit builds, review CI and changes, plan commits, catch up on GitHub and check docs against code.
---

# techne

techne is the plugin for work in a code repo: build audits, CI log review, pre-merge review, commit plans, GitHub catch-up, cross-repo drift checks, and comment and doc cleanup.

## Use it when

- You want to know the build is clean before you push, or why CI is noisy.
- A change needs an adversarial review before merge.
- Pending changes should become a reviewable commit plan.
- You returned to a repo and need to know who is waiting on whom.
- Docs, comments or a docs site may have drifted from the code.
- Several linked repos should stay in step.

## Install

```text
/plugin marketplace add ajbarea/techne
/plugin install techne@techne
```

## Needs

git, the GitHub CLI (`gh`) and its sign-in, uv, and python3 3.11 or newer. tmux is needed by `techne:theoros`. Playwright's Chromium is optional and used by the docs-site visual check. On macOS, `lsof` must be on PATH for the clean mode of `techne:sisters`.

## Set up

Run `/techne:setup`. It checks each item above, the repo's `.claude/skill-context.md` and `~/.claude/techne.toml`. It only reads, and prints an install command (a `fix:` line) for anything missing. The last line is `result: ready`, or `result: missing` with the names of the required checks that failed. Pass `--repo PATH` to the doctor to look for `skill-context.md` somewhere other than the current directory. Claude follows the [setup runbook](https://github.com/ajbarea/techne/blob/main/plugins/techne/AGENTS.md).

## Options

| Option | What it does |
|---|---|
| `clean_finished_work` | Off by default. When a session starts or resumes, runs `techne:sisters` auto mode in the background: removes worktrees and branches whose PR merged and that nothing is using, and gives Claude what a merge left behind with the instruction to investigate each held item and report it to you, removing one only when nothing would be lost or you say so. Claude sees the report on its next turn. The script ends itself after 240 seconds. The session's working directory is included when its repo is yours. Set it in `/config` under the techne plugin. See [auto mode](../skills/sisters.md#auto-mode). |

## Skills

| Skill | Use it to |
|---|---|
| [`techne:audit`](../skills/audit.md) | Run the repo's `make` targets in order and check the output against the `logs/` archive. |
| [`techne:auto-commit`](../skills/auto-commit.md) | Turn pending changes into a `COMMITS.md` commit plan. |
| [`techne:catchup`](../skills/catchup.md) | See what changed on a repo's issues and PRs since you last took part. |
| [`techne:ci-audit`](../skills/ci-audit.md) | Review GitHub Actions runs for warnings and failures. |
| [`techne:deslop`](../skills/deslop.md) | Find AI-generated filler in comments and docstrings. |
| [`techne:docs-site`](../skills/docs-site.md) | Audit the Zensical docs site. |
| [`techne:docsync`](../skills/docsync.md) | Check documentation claims against the code. |
| [`techne:elenchus`](../skills/elenchus.md) | Review a change adversarially before merge. |
| [`techne:research-grounded`](../skills/research-grounded.md) | Ground design decisions in current sources. |
| [`techne:reslop`](../skills/reslop.md) | Rewrite docstrings from the implementation. |
| [`techne:setup`](../skills/techne-setup.md) | Check what techne needs on this machine. |
| [`techne:sisters`](../skills/sisters.md) | Audit linked repos for drift. |
| [`techne:theoros`](../skills/theoros.md) | Drive a REPL in tmux while you watch. |

## Configuration

- `.claude/skill-context.md` in a repo holds per-repo facts, one `##` section per skill family. [Conventions](../conventions.md) lists the sections.
- `~/.claude/techne.toml` lists the sister repos and your workspace. [Configuration](../configuration.md) gives its schema.

## Troubleshooting

- **`gh` or `gh-auth` is missing.** Install the GitHub CLI with the doctor's fix line, then run `!gh auth login --hostname github.com` in Claude Code. On GitHub Enterprise, set `GH_HOST` to your host first; the doctor and gh both read it.
- **`skill-context` is missing.** `/techne:setup` offers to copy the skeleton into the repo. Keep the sections for the skills you use.
- **`techne.toml` is missing.** `techne:sisters` requires it. `techne:catchup` reads `workspace_root` from it to resolve a bare repo name, and falls back to the parent of the current directory without it. The schema is on the [configuration page](../configuration.md).
- **`python3` is older than 3.11.** `techne:catchup` and `techne:sisters` need 3.11, and stock macOS ships 3.9. Both stop with one line naming the fix. `uv python install --default 3.12 && uv python update-shell` puts a newer `python3` in `~/.local/bin` and on your PATH.
- **Chromium does not start on Linux.** Its system libraries are missing. Run `uv run --no-project --with playwright==1.63.0 playwright install-deps chromium`, which calls `sudo apt` itself.
- **`lsof` is missing on macOS.** macOS keeps it in `/usr/sbin`. The doctor's fix line adds that folder to PATH in `~/.zprofile`.
- **A skill is not listed.** Run `/reload-plugins`, then `/skills`.
