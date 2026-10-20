# techne setup runbook

This is the setup guide for techne, written for an agent guiding a user. Run the doctor first, then work through only the lines it marks `missing` or `optional`. The setup skill gives the doctor command and the plugin root.

## Rules

- The doctor only reads. Run it again after each fix to confirm.
- The user runs every fix line that contains `sudo`, `xcode-select --install` or a Homebrew cask (a cask install asks for the admin password). In Claude Code they type it after `!`, for example `!sudo apt install tmux`.
- The user runs `gh auth login`, because it opens a browser and asks questions. In Claude Code they type it after `!`, for example `!gh auth login --hostname github.com`.
- You may run any other fix line after the user approves, such as the uv installer, a Homebrew formula install without `sudo`, the Chromium install and the skill-context copy.
- Report only what the doctor printed.

## 1. Run the doctor

Each line starts with `ok`, `missing`, `optional` or `n/a`, then the check's name and a detail. A `missing` or `optional` line is followed by one or more `fix:` lines. The last line is `result: ready`, or `result: missing` with the names of the required checks that failed. The doctor exits 0 when nothing required is missing.

If the shell says `python3` is not found, the doctor cannot start. The user installs it with `sudo apt install python3` on Debian or Ubuntu, or `xcode-select --install` on macOS.

## 2. Fix each missing line

| Check | Used by | What to do |
| --- | --- | --- |
| `git` | every skill | The user runs the fix line with `!`. |
| `gh`, `gh-auth` | catchup, ci-audit, sisters, elenchus, auto-commit, board | The user runs the fix line with `!` (it contains `sudo` on Debian or Ubuntu; on macOS you may run `brew install gh` after the user approves), then the user signs in with `!gh auth login --hostname <host>`. The host is `GH_HOST` when set, otherwise `github.com`. |
| `uv` | docs-site, elenchus, and most repos' make targets | Run the fix line after the user approves, then open a new terminal so `uv` is on PATH. |
| `python3` | catchup, sisters, board, docs-site, docsync, ci-audit | catchup, sisters and board need Python 3.11 (`datetime.UTC`, `tomllib`); stock macOS python3 is 3.9. docsync and ci-audit run on 3.9 but treat every repo as team (they ask) when they cannot read `techne.toml`. The distro package is the old version already installed, so for a version below 3.11 the doctor prints `uv python install --default 3.12 && uv python update-shell`, and on macOS `brew install python` before it. Prefer the uv line: run it after the user approves, then open a new terminal so `~/.local/bin` is on PATH. |
| `tmux` | theoros | On Debian or Ubuntu the user runs the fix line with `!`. On macOS you may run it after the user approves. |
| `chromium` | docs-site visual QA | Optional. Run the fix line after the user approves; it downloads Chromium for Playwright 1.63.0. |
| `lsof` | sisters clean mode, macOS only | macOS keeps it in `/usr/sbin`; the fix line adds that folder to PATH in `~/.zprofile`; run it after the user approves. |

## 3. Give the repo a skill context

`techne:audit` and `techne:theoros` read `.claude/skill-context.md` at the repo root. The doctor marks it `optional` when the repo has none. If the user wants audit or theoros there, offer to run its fix line, which copies the skeleton. Then help the user keep the sections their skills use, for example `## audit` with the repo's make targets, and delete the rest. [Conventions](https://ajbarea.github.io/techne/conventions/) explains each section.

## 4. List sister repos (optional)

`techne:sisters` reads `~/.claude/techne.toml`: `github_user`, `workspace_root` and one `[[sisters]]` table per repo. Ask the user which repos to compare, and write the file only with their approval. The schema is on the [configuration page](https://ajbarea.github.io/techne/configuration/).

## 5. Check the result

Run the doctor again. When it prints `result: ready`, suggest a first skill: `/techne:audit` in a repo with a Makefile, or `/techne:catchup` in any GitHub repo.
