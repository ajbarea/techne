# heuresis setup runbook

This is the setup guide for heuresis, written for an agent guiding a user. The setup skill names the doctor command and the heuresis command; this runbook calls them "the doctor" and "the heuresis command".

## Rules

- The doctor only reads. Run it again after each change.
- The user sets `ideas_repo` and `repos_root` in `/config`, under the heuresis plugin's options. Do not edit settings files for them.
- The user runs every fix line that contains `sudo`, `xcode-select --install` or a Homebrew cask. In Claude Code they type it after `!`.
- You may run any other fix line after the user approves.
- Never ask for an API key in chat and never write one into a file.

## 1. Run the doctor

Fix every `missing` line first; each prints its fix. The last line is `result: ready`, or `result: missing` naming the required checks that failed.

## 2. Repos folder

Set `repos_root` in `/config` to the folder that holds the user's clones (papers, talks, project repos).

## 3. Ideas repository

If `ideas_repo` is missing:

1. Pick a folder next to the other clones, for example `<repos_root>/ideas`, and have the user set `ideas_repo` to it in `/config`.
2. Create it: run the heuresis command with `init <ideas_repo> --repos-root <repos_root>`. It lays out the folders and runs `git init -b main` but does not commit.
3. Make the first commit: `git -C <ideas_repo> add -A` then `git -C <ideas_repo> commit -m "init: ideas repository"`.
4. Ask the user before creating the GitHub repository. On a yes: `gh repo create ideas --private --source <ideas_repo> --push`.

## 4. Search keys

Each `optional` key line names what the key adds and where to get it. The user exports each key in the shell profile Claude Code starts from (`~/.bashrc` or `~/.zshrc`) and restarts Claude Code. A source without its key shows `skipped` in a verdict's coverage line; the rest still run.

## 5. Check the result

Run the doctor again until it prints `result: ready`. Then `/heuresis:idea --now <idea>` works.
