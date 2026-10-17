# heuresis

heuresis keeps every idea in one private git repository and gives each one a first opinion grounded in prior work. It searches papers (OpenAlex, Semantic Scholar, arXiv), patents (Lens, EPO), products (GitHub, Hacker News, the web) and your own bibliography, notes, decks and repos, then names the closest existing work and files the idea as trash, later or do.

## Install

```bash
/plugin marketplace add ajbarea/techne
/plugin install heuresis@techne
```

heuresis needs [uv](https://docs.astral.sh/uv/), git and the GitHub CLI. Run `/heuresis:setup` after installing: it checks each one, creates your ideas repository, and lists the API keys that widen the search. The [setup runbook](https://github.com/ajbarea/techne/blob/main/plugins/heuresis/AGENTS.md) has every step.

## Search keys

Optional keys add Semantic Scholar, Lens, EPO and a larger OpenAlex budget. Run `/plugin configure heuresis@techne`, paste each key into its masked field, and restart Claude Code. The keys sit in Claude Code's secure storage, and a session-start hook passes them to Bash commands. To import them from a `.env` file instead, `/heuresis:setup` prints a template and saves the filled-in file with a store script; the file is yours to delete afterwards. A key exported in your shell profile still works and wins. [Keys](../skills/idea.md#keys) lists what each one adds.

## First use

Run `/heuresis:idea --now <your idea>`. Without `--now`, the idea is saved to the inbox for later triage.

## Troubleshooting

- **A source shows `skipped` in the verdict's coverage line.** Its API key is not saved. `/heuresis:setup` lists which key each source needs; save it with `/plugin configure heuresis@techne` and restart Claude Code.
- **A verdict says "insufficient evidence".** No paper source returned results, or the closest rival could not be verified. Run `/heuresis:idea --retriage <id>` later.
