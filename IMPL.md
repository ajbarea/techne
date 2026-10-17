# techne — Implementation scratchpad

The active TODO list for whatever's in flight **right now** — current
PR, open design question blocking me, immediate next pickup. Queued
specs, cross-skill themes, and "next up" ordering live in
[ROADMAP.md](./ROADMAP.md). Git history is the permanent record of
how each skill was designed.

If this file is more than ~50 lines, something queued or referential
has crept in; extract it back to ROADMAP.

## In flight

### In review: heuresis search keys in secure storage

The five search keys are `sensitive` plugin options (`/plugin configure heuresis@techne`), kept in
Claude Code's secure storage. A SessionStart hook (`hooks/export_keys.py`) appends `export` lines to
`CLAUDE_ENV_FILE` so every Bash command sees them, unless the shell already exports the key.
`skills/setup/scripts/store_keys.py` imports a `.env` file through `claude plugin configure
--values-stdin`. One table, `hooks/search_keys.py`, feeds the manifest test, the hook, the store
script and the doctor. Not in `_shared/`: that folder holds copies `make guards` syncs from techne.

### Landed: heuresis phase 1 (v1.4.0)

`/heuresis:idea` captures an idea in the private ideas repository and triages it (four scouts, a
judge, `verify`, `apply`, regenerated `BOARD.md` and `LOG.md`). The Lens and EPO adapters are not
yet confirmed with live keys.

### Next: heuresis phase 2, the gold set

A gold set of ideas with known verdicts and a harness that scores the pipeline, run before any
verdict is trusted. Later phases are in ROADMAP.

### Then: commit guards on Git 2.54 hooks (#96)

Config-based `commit-msg` and `pre-commit` hooks set through `CLAUDE_ENV_FILE`. Blocked on Git 2.54
being available to test against. Open: the Zenodo concept DOI into `CITATION.cff` and a README
badge; epistole's day-8 token check (2026-10-19, #123).

## Skill collection state

Shipped plugins and skills by catalog dimension (the directory listing of `plugins/*/skills/` is the source of truth):

| Plugin | Dimension | Skills |
| --- | --- | --- |
| `techne` | **Audit** | `audit`, `ci-audit` |
| `techne` | **Drift** | `docsync`, `docs-site`, `research-grounded`, `sisters` |
| `techne` | **Hygiene** | `auto-commit`, `deslop`, `reslop` |
| `techne` | **Review** | `catchup`, `elenchus` |
| `techne` | **Observation** | `theoros` |
| `techne`, `graphe`, `heuresis`, `phylax` | **Setup** | `setup` (a read-only doctor per plugin) |
| `graphe` | **Document build** | `latex`, `pdf`, `paper`, `paper-review`, `slides` |
| `dokimasia` | **Bibliography** | `check` |
| `heuresis` | **Ideas** | `idea`, `setup` |
| `epistole` | **Mail** | MCP server, setup |
| `phylax` | **Hooks** | git guards (a mod, `hooks/register.ts`), `restart_on_update` (command hooks) |
