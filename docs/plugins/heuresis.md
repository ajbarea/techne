---
description: heuresis plugin, idea triage. Capture an idea, search papers, patents, products and your own work, name the closest existing work, and file the idea as trash, later, do or merged.
---

# heuresis

heuresis keeps every idea in one private git repository and gives each one a first opinion grounded in prior work. It searches papers (OpenAlex, Semantic Scholar, arXiv), patents (Lens, EPO), products (GitHub, Hacker News, the web) and your own bibliography, notes, decks and repos, then names the closest existing work and files the idea as trash, later, do or merged.

## Use it when

- You have an idea for an app, tool, product or research direction and want it saved.
- You want to know whether someone already built it.

## Install

```text
/plugin marketplace add ajbarea/techne
/plugin install heuresis@techne
```

## Needs

[uv](https://docs.astral.sh/uv/) and git. The GitHub CLI is optional: it adds GitHub search and the private ideas remote. Search API keys are optional and widen the search.

## Search keys

Optional keys add Semantic Scholar, Lens, EPO and a larger OpenAlex budget. Run `/plugin configure heuresis@techne`, paste each key into its masked field, and restart Claude Code. The keys sit in Claude Code's secure storage. At session start heuresis writes them to a private (0600) per-process file in its plugin data folder that Bash commands load, and deletes the file when the session ends. To import them from a `.env` file instead, `/heuresis:setup` prints a template and saves the filled-in file with a store script; the file is yours to delete afterwards. A key already in the Bash environment, such as one exported in your shell profile, wins. [Keys](../skills/idea.md#keys) lists what each one adds.

## Set up

Run `/heuresis:setup` after installing. It checks each tool, creates your ideas repository, and lists the API keys that widen the search. The last line is `result: ready`, or `result: missing` with the names of the required checks that failed. The [setup runbook](https://github.com/ajbarea/techne/blob/main/plugins/heuresis/AGENTS.md) has every step.

## Skills

| Skill | Use it to |
|---|---|
| [`heuresis:idea`](../skills/idea.md) | Capture an idea and triage it against prior work. |
| [`heuresis:setup`](../skills/heuresis-setup.md) | Check the tools, create the ideas repository, list the search keys. |

First run: `/heuresis:idea --now <your idea>`. Without `--now`, the idea is saved to the inbox for later triage.

## Commands and tools

The skill drives a `heuresis` command and five agents. The agents are `scout-papers`, `scout-patents`, `scout-products`, `scout-context` and `judge`; Claude dispatches them, and they are not for direct use. The `heuresis` subcommands are `init`, `capture` (with `--via terminal|phone|form|import`), `context`, `similar`, `restate`, `search`, `add-record`, `pool`, `verify`, `apply`, `override`, `board`, `publish` and `version`. Claude runs them through the skills: `/heuresis:setup` runs `init`, and `/heuresis:idea` runs `publish` when pushing your ideas repository failed. heuresis puts no command on your PATH.

## Configuration

`ideas_repo` (your local ideas repository) and `repos_root` (the folder holding your clones) are plugin options, set in `/config` under the heuresis plugin. The five search keys are sensitive plugin options, saved with `/plugin configure heuresis@techne` (see [Search keys](#search-keys)); a key exported in your shell profile wins over a saved one.

The ideas repository also holds `projects.toml` and `context.toml`, which `init` seeds. `heuresis context` reads them to find your research sources, and `--project` names come from `projects.toml`.

## Troubleshooting

- **A source shows `skipped` in the verdict's coverage line.** Its API key is not saved. `/heuresis:setup` lists which key each source needs; save it with `/plugin configure heuresis@techne` and restart Claude Code. The coverage line can also read `failed`, `empty`, or `ok` with a `partial:` note, which name what that source did.
- **A verdict says "insufficient evidence".** The judge proposed `do` but a rule failed: no type, no closest rival named or one that could not be verified or compared on all four facets, or no paper source returned results. The reason line names which. Run `/heuresis:idea --retriage <id>` later.
