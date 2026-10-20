---
description: "Keep one GitHub Projects board of every repo's work by stage: Idea, Issue, In PR, Merged, Live. Show it, sync it, add ideas, mark deploys Live, and file new issues and PRs automatically."
---

# `techne:board`

One GitHub Projects board for the work of every repo you own, by stage: **Idea**, **Issue**, **In PR**, **Merged**, **Live**. It answers "what state is X in" without opening each repo.

Part of [techne](../plugins/techne.md): `/plugin install techne@techne`, then `/techne:setup`.

## When to use

- "What state is the export fix in?" / "What's merged but not live?" / "Show the board."
- After a deploy: mark the PR **Live**.
- An idea worth tracking before it becomes an issue.
- Setting the board up, or filling it from recent work.

## Why

GitHub's own auto-add workflow is limited to one repository per workflow, and a project can have one such workflow on GitHub Free and five on Pro or Team ([GitHub docs](https://docs.github.com/en/issues/planning-and-tracking-with-projects/automating-your-project/adding-items-automatically)). Every Claude Code session loads techne, so techne files the items instead.

## Setup

1. Give gh the `project` scope: `gh auth refresh -h github.com -s project`.
2. `/techne:board init` with a title. It creates the board when the owner has no open project with that title, sets the Status options to the five stages, and prints the table to add to `~/.claude/techne.toml`:

   ```toml
   [board]
   owner = "your-login"
   number = 1
   ```

   It refuses when items still use a Status option it would remove.
3. Set two built-in workflows by hand, since GitHub's API cannot change them. On the board, open the menu (...) at the top right, then **Workflows**. For **Item closed** and then **Pull request merged**: click it, click **Edit**, set Status to **Merged**, then **Save and turn on workflow** ([GitHub docs](https://docs.github.com/en/issues/planning-and-tracking-with-projects/automating-your-project/using-the-built-in-automations)).
4. `/techne:board sync` to fill the board from recent work.

## Usage

| Command | What it does |
|---|---|
| `show` | The board grouped by Status in stage order, one line per item: `repo#n title`, or a draft's title. |
| `sync [--days N]` | For each repo pushed to in the last N days (default 14): adds open issues as Issue, open PRs as In PR and PRs merged in the window as Merged, and moves items already on the board whose state changed, including issues closed in the window (Merged). A Live item is never moved. Prints counts. |
| `idea "<title>" [--body text]` | Adds a draft item as Idea. |
| `live <url>` | Sets an issue or PR to Live, adding it first if needed. |
| `init --title T [--owner O]` | Creates and configures the board, and prints the `[board]` table. Edits no file. |

## The hook

With a `[board]` table, a `PostToolUse` hook runs after each Bash command that starts with `gh`. When the command was `gh issue create`, `gh pr create`, or a `gh api` POST to `repos/<owner>/<repo>/issues` or `/pulls`, it adds each issue or PR URL in the output whose repo the board's owner owns, with Status Issue or In PR. For a `gh api` JSON response it takes only the response's `html_url`, so URLs quoted in a PR body are left alone.

It never blocks or fails the command, and bounds its gh calls to 8 seconds. On success it prints nothing. On failure it adds one line to Claude's context, such as `board: could not add <url> (gh token lacks the 'project' scope; the user runs: gh auth refresh -h github.com -s project)`. The board's project, field and option IDs are cached in `~/.cache/techne/` and looked up again when they go stale.

## Source

[SKILL.md](https://github.com/ajbarea/techne/blob/main/plugins/techne/skills/board/SKILL.md)
