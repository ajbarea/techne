# techne

techne is a Claude Code plugin marketplace (`ajbarea/techne`). Each plugin is installed on its own. This file is for an agent that lands on the repository, either to use the plugins for a user or to change them.

Docs for agents: <https://ajbarea.github.io/techne/llms.txt> lists every page with a description, and <https://ajbarea.github.io/techne/llms-full.txt> holds them all in one file. Any docs page has a Markdown copy at the same URL ending in `index.md`.

## Which plugin for which task

| The user wants to | Plugin | Setup skill |
| --- | --- | --- |
| Audit a build, review CI or a change before merge, plan commits, catch up on GitHub threads, check docs against code, keep linked repos in step | `techne` | `/techne:setup` |
| Build LaTeX, render markdown to PDF, make a talk deck, scaffold or review a paper | `graphe` | `/graphe:setup` |
| Verify a bibliography against arXiv and Crossref | `dokimasia` | none (needs only uv) |
| Capture an idea and check it against prior work | `heuresis` | `/heuresis:setup` |
| Search, read and draft Gmail across accounts, catch up on mail | `epistole` | `/epistole:setup` |
| Check a Brightspace (D2L) course site for news and due work | `schole` | `/schole:setup` |
| Block attribution lines, guard commits, restart idle sessions on update | `phylax` | `/phylax:setup` |
| Hear a gist of each reply (WSL2) | `keryx` (own repo, `ajbarea/keryx`) | `keryx status` |

## Install and set up

From inside Claude Code:

```text
/plugin marketplace add ajbarea/techne
/plugin install <plugin>@techne
```

epistole and schole ship commands in `bin/`, so they install in Claude Code's terminal and desktop app but not on claude.ai or in Cowork ([plugin reference](https://code.claude.com/docs/en/plugins-reference#standard-layout)).

Then run the plugin's setup skill. Each setup guide is the plugin's `AGENTS.md`: `plugins/<plugin>/AGENTS.md` (dokimasia has one too, and keryx's is in its own repository). The doctors only read; a `fix:` line that contains `sudo`, and every sign-in, is the user's to run, after `!` in Claude Code. Never ask for a password, token or API key in chat.

## Changing the repository

```bash
make setup      # uv sync
make validate   # lint, shellcheck, zizmor, plugin validate and test, tests, strict docs build
make lint       # ruff check, ruff format --check and ty over scripts/, plugins/ and tests/
make build      # strict Zensical build of the docs site
```

- Work in a git worktree, not the main checkout, and open a pull request; `main` is protected.
- Never commit `site/` (build output) or `COMMITS.md` (a local scratchpad).
- A skill's `SKILL.md` frontmatter `description:` is the canonical summary. README and `docs/skills/*.md` must match it, and a new skill needs a docs page (`tests/test_docs_coverage.py` fails without one).
- Do not write skill or plugin counts into prose. README's per-skill tables carry the inventory.
- `.claude/skill-context.md` holds the facts the techne skills read for this repo.
- `docs/epistole.md` is the registered privacy-policy URL of the epistole Google OAuth app. Do not move or rename it.
