---
name: board
description: Track every repo's work on one GitHub Projects board by stage (Idea, Issue, In PR, Merged, Live). Shows the board grouped by stage, syncs recent issues and PRs from every repo the owner pushed to, adds an idea as a draft, marks a deployed item Live, and creates and configures the board. Use when the user asks what state a piece of work is in, "show the board", "what's in flight", "what's merged but not live", "sync the board", "add this idea to the board", "mark it live", "we deployed X", or wants the cross-repo board set up. Not for one repo's comment threads (techne:catchup) or for triaging an idea against prior work (heuresis:idea).
disable-model-invocation: false
allowed-tools: Bash(python3 *) Bash(gh *) Read
---

# Board

`<skill-dir>` is the directory holding this SKILL.md.

One user-owned GitHub Projects board holds the work of every repo, with a Status field whose options are, in order: **Idea**, **Issue**, **In PR**, **Merged**, **Live**. It answers "where does X stand" across all repos at once.

The board is named in `~/.claude/techne.toml`:

```toml
[board]
owner = "your-login"
number = 1
```

Without that table every board feature does nothing. With it, techne's hook files each issue or PR that a `gh issue create`, `gh pr create` or `gh api` POST to `.../issues` or `.../pulls` opens in a repo the owner owns: Status **Issue** for an issue, **In PR** for a PR. The hook never blocks the command; when filing fails it adds one `board: could not add ...` line to the context. Tell the user that line, and its fix when it names one.

Every `gh project` call needs the `project` token scope. When gh says it is missing, the user runs `!gh auth refresh -h github.com -s project`. Never ask for a token.

## Commands

```bash
python3 <skill-dir>/scripts/board.py show
python3 <skill-dir>/scripts/board.py sync [--days N]
python3 <skill-dir>/scripts/board.py idea "<title>" [--body "<text>"]
python3 <skill-dir>/scripts/board.py live <issue-or-pr-url>
python3 <skill-dir>/scripts/board.py init --title "<title>" [--owner <login>]
```

| Command | What it does |
|---|---|
| `show` | Prints the board grouped by Status in the order above, one line per item: `repo#n title`, or a draft's title. Items with no Status come last. |
| `sync` | For each repo the owner pushed to in the last N days (default 14), adds open issues (**Issue**), open PRs (**In PR**) and PRs merged in that window (**Merged**) that are not on the board, and moves items already on it whose state changed, including issues closed in the window (**Merged**). A **Live** item is never moved. Prints the counts. |
| `idea` | Adds a draft item with Status **Idea**. |
| `live` | Sets an issue or PR to **Live**, adding it first if needed. Run it after a deploy. |
| `init` | Creates the board when the owner has no open project with that title, sets its Status options to the five above, and prints the `[board]` table to add. It edits no file. It refuses when items still use an option it would remove. |

Answer "what state is X in" from `show`. When a deploy just happened, run `live` with the PR's URL.

## Setting up the board

1. `python3 <skill-dir>/scripts/board.py init --title "<title>"`. The owner defaults to `[board].owner`, then `github_user` in techne.toml.
2. Show the user the printed `[board]` table to add to `~/.claude/techne.toml`. Do not edit that file yourself.
3. Built-in workflows: a new project's "Item closed" and "Pull request merged" workflows set Status to Done, which `init` replaces. GitHub's API has no way to change a workflow, so the user does it by hand: open the board, the menu (...) at the top right, **Workflows**; for each of the two, click it, click **Edit**, set Status to **Merged**, then **Save and turn on workflow**. `init` prints these steps.
4. `python3 <skill-dir>/scripts/board.py sync` to fill the board from recent work.

## Failures

- `board: no [board] table`: the board is not configured; offer `init`.
- `board has no Status option 'X'`: the Status field lost an option; run `init` again.
- A failed `sync` line names the repo or URL and gh's reason; the rest of the sync still ran.
