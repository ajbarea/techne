# heuresis setup runbook

This is the setup guide for heuresis, written for an agent guiding a user. The setup skill names the doctor command and the heuresis command; this runbook calls them "the doctor" and "the heuresis command".

## Rules

- The doctor only reads. Run it again after each change.
- The user sets `ideas_repo` and `repos_root` in `/config`, under the heuresis plugin's options. Do not edit settings files for them.
- The user runs every fix line that contains `sudo`, `xcode-select --install` or a Homebrew cask. In Claude Code they type it after `!`.
- You may run any other fix line after the user approves.
- Every path you pass to the doctor or the heuresis command is absolute. The heuresis command runs with its working directory set to the plugin, so a relative path points inside the plugin.
- Never ask for an API key in chat. The user writes any file that holds a key; you never read, cat or write it.

## 1. Run the doctor

Fix every `missing` line first; each prints its fix. The last line is `result: ready`, or `result: missing` naming the required checks that failed.

## 2. Repos folder

Set `repos_root` in `/config` to the folder that holds the user's clones (papers, talks, project repos).

## 3. Ideas repository

If `ideas_repo` is missing:

1. Pick a folder next to the other clones, for example `<repos_root>/ideas`, and have the user set `ideas_repo` to it in `/config`.
2. Create it: run the heuresis command with `init <ideas_repo> --repos-root <repos_root>`. It lays out the folders and runs `git init -b main` but does not commit.
3. Make the first commit: `git -C <ideas_repo> add -A` then `git -C <ideas_repo> commit -m "init: ideas repository"`. If git has no `user.name` or `user.email` (`git config user.name` prints nothing), ask the user to set them with `git config --global user.name "<name>"` and `git config --global user.email "<email>"`. Never invent them.
4. Create the GitHub repository only when the doctor shows `ok gh` and `gh auth status` succeeds, and ask the user first. On a yes: `gh repo create ideas --private --source <ideas_repo> --push`. If `gh` is missing, the user installs it with the doctor's fix line. If `gh auth status` fails, the user runs `gh auth login`. Until then the ideas repository works locally.

## 4. Search keys

Each `optional` key line names what the key adds and where to get it. A source without its key shows `skipped` in a verdict's coverage line; the rest still run. Claude Code keeps the keys in its secure storage. At session start heuresis writes them to a private (0600) per-process file in its plugin data folder that Bash commands load, and deletes the file when the session ends. Pick one route:

- **Route A (recommended).** The user runs `/plugin configure heuresis@techne` and pastes each key into its masked field.
- **Route B, from a file.** Print the template with the store command and `template`, then have the user save it at a private path outside any repository (for example `~/heuresis-keys.env`), fill in the keys and run `chmod 600` on it. Run the store command with `store` and that absolute path. It saves the keys to secure storage and prints only their names. Afterwards the user deletes the file or keeps it somewhere private.

Either way the user restarts Claude Code, then you run the doctor again. A key already in the Bash environment, such as one exported in the shell profile, wins over a saved one.

## 5. Check the result

The skill's doctor command was filled in before the user set the paths in `/config`, so it may still show them empty. Run the doctor script the setup skill names, passing the chosen paths explicitly: `IDEAS_REPO=<ideas_repo> REPOS_ROOT=<repos_root>`, both absolute. Or have the user run `/reload-plugins` and invoke `/heuresis:setup` again. Repeat until it prints `result: ready`. Then `/heuresis:idea --now <idea>` works.
