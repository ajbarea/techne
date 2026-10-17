---
description: techne:setup checks what the techne code-repo skills need on this machine (git, gh and its sign-in, uv, python3, tmux, Chromium) and prints the install command for each gap.
---

# `techne:setup`

Check what the techne skills need on this machine and print the install command for each gap.

Part of [techne](../plugins/techne.md): `/plugin install techne@techne`.

## When to use

After installing techne, when a techne skill says `gh`, tmux, a sign-in or a config file is missing, or to ask whether techne is ready on this machine.

## Usage

```text
/techne:setup
```

The skill runs a doctor script that only reads, then follows the [setup runbook](https://github.com/ajbarea/techne/blob/main/plugins/techne/AGENTS.md). It installs nothing itself: you run each `fix:` line, or Claude runs it after you approve. Lines with `sudo`, `xcode-select --install` or a Homebrew cask, and `gh auth login`, are yours to run (in Claude Code, after `!`).

## What it checks

| Check | Used by |
|---|---|
| `git` | Every skill. |
| `gh`, `gh-auth` | `catchup`, `ci-audit`, `sisters`, `elenchus`, `auto-commit`. Sign-in is checked for `GH_HOST`, else `github.com`. |
| `uv` | `docs-site`, `elenchus`, and most repos' make targets. |
| `python3` | 3.11 or newer for `catchup` and `sisters`. |
| `tmux` | `theoros`. |
| `chromium` | Optional. Playwright's Chromium for the docs-site visual check. |
| `lsof` | macOS only: `sisters` clean mode. |
| `skill-context` | Optional. The repo's `.claude/skill-context.md`, read by `audit` and `theoros`. The fix line copies the skeleton. |
| `techne.toml` | Optional. `~/.claude/techne.toml`, read by `sisters` and `catchup`. |

## Output

Each line starts with `ok`, `missing`, `optional` or `n/a`, then the check's name and a detail. A `missing` or `optional` line is followed by one or more `fix:` lines. The last line is `result: ready`, or `result: missing` with the names of the required checks that failed. The doctor exits 0 when nothing required is missing, and only reads. Run the doctor script with `--repo PATH` to look for `skill-context.md` somewhere other than the current directory.

## See also

- [techne plugin](../plugins/techne.md): install, needs and troubleshooting.
- [Conventions](../conventions.md): what `skill-context.md` holds.

## Full instructions

[`SKILL.md` on GitHub](https://github.com/ajbarea/techne/blob/main/plugins/techne/skills/setup/SKILL.md) holds the full instructions Claude follows for this skill.
