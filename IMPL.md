# techne — Implementation scratchpad

The active TODO list for whatever's in flight **right now** — current
PR, open design question blocking me, immediate next pickup. Queued
specs, cross-skill themes, and "next up" ordering live in
[ROADMAP.md](./ROADMAP.md). Git history is the permanent record of
how each skill was designed.

If this file is more than ~50 lines, something queued or referential
has crept in; extract it back to ROADMAP.

## In flight

### In review: shared plugin key hook, graphe keys

A plugin's own `plugin.json` is its key table: every `sensitive` string option is a key (variable =
option name in capitals, text = its `description`), and `metadata.keyGroups` lists keys that only
work together. One module, `plugins/techne/_shared/plugin_keys.py` (copied to heuresis and graphe
by `make guards`), runs the SessionStart and SessionEnd hooks (`start` / `end`), the `.env` import
(`store`, `template`) and `load_keys` for the doctors. At session start it writes the keys to a
private (0600) per-process file `<session_id>.<claude pid>.sh` in `CLAUDE_PLUGIN_DATA/session-keys`
and appends only a line that sources it to `CLAUDE_ENV_FILE` (Claude Code leaves those files at
0644 and never deletes them, so no value goes in one). SessionEnd deletes its own process's file,
and start prunes files whose process is gone (by age, 30 days, on Windows). A key already in the
Bash environment wins. graphe gains `openalex_api_key` and `s2_api_key` for paper-review.

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
