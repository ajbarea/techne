# techne setup runbook

This is the setup guide for techne, written for an agent guiding a user. Run the doctor first, then work through only the lines it marks `missing` or `optional`. The setup skill gives the doctor command and the plugin root.

## Rules

- The doctor only reads. Run it again after each fix to confirm.
- After the user approves, you may run a fix that needs no `sudo` and no browser: the Chromium install and the skill-context copy.
- The user runs every fix that starts with `sudo`, and `xcode-select --install`. In Claude Code they type it after `!`.
- The user runs `gh auth login`, because it opens a browser and asks questions: `!gh auth login --hostname github.com`.
- Report only what the doctor printed.

## 1. Run the doctor

Each line starts with `ok`, `missing`, `optional` or `n/a`, then the check's name and a detail. A `missing` or `optional` line is followed by one or more `fix:` lines. The last line is `result: ready`, or `result: missing` with the names of the required checks that failed. The doctor exits 0 when nothing required is missing.

If the shell says `python3` is not found, the doctor cannot start. The user installs it with `sudo apt install python3` on Debian or Ubuntu, or `xcode-select --install` on macOS.

## 2. Fix each missing line

| Check | Used by | What to do |
| --- | --- | --- |
| `git` | every skill | Run the fix line. |
| `gh`, `gh-auth` | catchup, ci-audit, sisters, elenchus, auto-commit | Install gh with the fix line, then the user signs in with `!gh auth login --hostname <host>`. The host is `GH_HOST` when set, otherwise `github.com`. |
| `uv` | docs-site, elenchus, and most repos' make targets | Run the fix line, then open a new terminal so `uv` is on PATH. |
| `python3` | catchup, sisters | sisters reads TOML with `tomllib`, which needs Python 3.11. On a system whose package python3 is older, `uv python install --default 3.12` puts a newer `python3` in `~/.local/bin`. |
| `tmux` | theoros | Run the fix line. |
| `chromium` | docs-site visual QA | Optional. Run the fix line after the user approves; it downloads Chromium for Playwright 1.63.0. |
| `lsof` | sisters clean mode, macOS only | macOS keeps it in `/usr/sbin`; add that folder to PATH. |

## 3. Give the repo a skill context

`techne:audit` and `techne:theoros` read `.claude/skill-context.md` at the repo root. The doctor marks it `optional` when the repo has none. If the user wants audit or theoros there, offer to run its fix line, which copies the skeleton. Then help the user keep the sections their skills use, for example `## audit` with the repo's make targets, and delete the rest. [Conventions](https://ajbarea.github.io/techne/conventions/) explains each section.

## 4. List sister repos (optional)

`techne:sisters` reads `~/.claude/techne.toml`: `github_user`, `workspace_root` and one `[[sisters]]` table per repo. Ask the user which repos to compare, and write the file only with their approval. The schema is on the [configuration page](https://ajbarea.github.io/techne/configuration/).

## 5. Check the result

Run the doctor again. When it prints `result: ready`, suggest a first skill: `/techne:audit` in a repo with a Makefile, or `/techne:catchup` in any GitHub repo.
