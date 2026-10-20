# techne — Implementation scratchpad

The active TODO list for whatever's in flight **right now** — current
PR, open design question blocking me, immediate next pickup. Queued
specs, cross-skill themes, and "next up" ordering live in
[ROADMAP.md](./ROADMAP.md). Git history is the permanent record of
how each skill was designed.

If this file is more than ~50 lines, something queued or referential
has crept in; extract it back to ROADMAP.

## In flight: `techne:board` (branch `feat/board`)

One user-owned GitHub Projects board, Status = Idea, Issue, In PR, Merged, Live, named by
`[board] owner/number` in `~/.claude/techne.toml` (absent = every board feature is a no-op).

Done:
- `_shared/project_board.py` (python3 3.9): config with a no-tomllib fallback, trigger
  detection, URL extraction, gh with one time budget, ID cache in `~/.cache/techne/`.
- `hooks/board_add.py` + PostToolUse entry in `hooks/hooks.json` (`if: Bash(gh *)`).
- `skills/board/` SKILL.md + `scripts/board.py`: show, sync, idea, live, init (init sets
  Status via GraphQL `updateProjectV2Field.singleSelectOptions`, keeps IDs of kept options,
  refuses to drop an option an item uses, prints the `[board]` table and workflow clicks).
- Tests: `tests/test_board_hook.py` (in HOOK_TESTS, runs on 3.9), `tests/test_board_script.py`,
  stub gh `tests/fixtures/gh_stub.py` + `gh_stub` fixture. Docs page, config schema, eval case.

Not verified live: the token here lacks the `project` scope, so every gh project call is
stub-tested only. After merge: `gh auth refresh -h github.com -s project`, then
`/techne:board init --title ajsoftworks`, add the printed table, set the two workflows,
`/techne:board sync`.

Verify: `make validate`.

## Then: commit guards on Git 2.54 hooks (#96)

Config-based `commit-msg` and `pre-commit` hooks set through `CLAUDE_ENV_FILE`. Git 2.54 has shipped
(2.56 is current), but WSL's Ubuntu 24.04 has 2.43; testing needs a 2.54 or newer git here.

## Skill collection state

Shipped plugins and skills by catalog dimension (the directory listing of `plugins/*/skills/` is the source of truth):

| Plugin | Dimension | Skills |
| --- | --- | --- |
| `techne` | **Audit** | `audit`, `ci-audit` |
| `techne` | **Drift** | `docsync`, `docs-site`, `research-grounded`, `sisters` |
| `techne` | **Hygiene** | `auto-commit`, `deslop`, `reslop` |
| `techne` | **Review** | `catchup`, `elenchus` |
| `techne` | **Tracking** | `board` (and its PostToolUse hook) |
| `techne` | **Observation** | `theoros` |
| `techne`, `graphe`, `heuresis`, `phylax` | **Setup** | `setup` (a read-only doctor per plugin) |
| `graphe` | **Document build** | `latex`, `pdf`, `paper`, `paper-review`, `slides` |
| `dokimasia` | **Bibliography** | `check` |
| `heuresis` | **Ideas** | `idea`, `setup` |
| `epistole` | **Mail** | MCP server, setup |
| `phylax` | **Hooks** | git guards (a mod, `hooks/register.ts`), `restart_on_update` (command hooks) |
