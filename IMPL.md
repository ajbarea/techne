# techne — Implementation scratchpad

The active TODO list for whatever's in flight **right now** — current
PR, open design question blocking me, immediate next pickup. Queued
specs, cross-skill themes, and "next up" ordering live in
[ROADMAP.md](./ROADMAP.md). Git history is the permanent record of
how each skill was designed.

If this file is more than ~50 lines, something queued or referential
has crept in; extract it back to ROADMAP.

## In flight: elenchus bug-class catalog + phylax model guard (branch `feat/elenchus-bug-classes`, PR #194)

Done (tests green):
- `plugins/techne/skills/elenchus/references/bug-classes.md`: 9 core classes plus learned ones,
  each Symptom, Question, Guard, Incidents (at most three; private repos described, not named).
  `tests/test_bug_classes.py` parses it strictly and enforces the incident grammar and budget.
- elenchus SKILL.md: catalog first, class tags, recurring class escalates, deferred-findings
  ledger with issues, 3-round default budget, After merge, reader on the strongest model the
  session can dispatch, "Before you ask for review" pre-flight.
- phylax `require_subagent_model`: refuses a no-model call to general-purpose, claude, Explore,
  Plan; plugin and user agents left to their definitions; stands down while any
  `CLAUDE_CODE_SUBAGENT_MODEL*` or coordinator setting is present (round 3 showed _FORCE can
  remove `model` from the Agent schema, so modelling the order failed three rounds running).

Rounds: r1 `/code-review high` (10), r2 opus reader (4), r3 opus reader (1 Blocking, 1
Should-fix, both recurring classes, both now fixed structurally). Ledger: #195, #196, #197.
Budget of three rounds is spent: the r3 fixes are unreviewed. Next: AJ's go-ahead for a fourth
round, then merge, then the companion prefs PR (it waits on this one).

## Follow-up: sisters check 15 minors (PR #193 merged)

Check 15 (`scripts/agents_md.py`) flags every CLAUDE.md, .claude/CLAUDE.md and CLAUDE.local.md
in a sister (tracked, untracked or ignored, any depth, except inside a wholly ignored folder)
or above it. Six review rounds; the last found no Blocking or Should-fix. Open Minors:
1. A wholly ignored non-vendored folder (`scratch/`, or `.claude/` ignored) hides a CLAUDE.md
   a session started there loads (probe: PLUM). Fix: for each `dir/` entry from the
   `--directory` listing, also check that folder's top level (`CLAUDE.md`, `.claude/CLAUDE.md`,
   `CLAUDE.local.md`, plus `dir/CLAUDE.md` when dir is `.claude`); test beside node_modules.
2. Non-UTF-8 path + strict UTF-8 stdout raises UnicodeEncodeError and aborts later repos. Fix:
   `sys.stdout.reconfigure(errors="backslashreplace")` in main; test a bytes-named folder in a
   subprocess with PYTHONIOENCODING=utf-8 (kills the fsdecode-revert mutant).
3. Dead `found = set()` in `candidates()`; nested CLAUDE.local.md gets "move into AGENTS.md"
   advice (should get the personal-notes advice); a corrupt index reads "not a git repository".
Fleet: velocity-fl (harvest-only) has no AGENTS.md; every other sister passes.
Verify: `flock /tmp/fleet-heavy.lock timeout 600 uv run pytest tests/test_sisters_agents_md.py -q -rA`.

### Landed on main: one techne.toml reader (#192, closes #190)

`_shared/techne_config.py` is the only reader of `~/.claude/techne.toml`: bounded
`read_regular()` (also repo_kind's skill-context read), `load()` with one `ConfigError` family
each caller maps, strict roster (`sisters()`, one-folder names), `required()`, `workspace_root()`
(absolute or `~`), kind/status rules, `checkout()`, `matches()`. A guard test keeps every other
techne script from parsing TOML or building a path to the file. Not changed on purpose:
same-origin git call per team sister (~5 ms), `matches()` resolving per sister, board init's
double parse.

### Landed on main: solo repos act, team repos ask (#189)

`_shared/repo_kind.py`: only GitHub facts make a repo solo; the canonical marker `- owner: team`
under `## repo` or `kind = "team"` makes it team; unsettled reads team. docsync acts on solo
repos; ci-audit `[PROPOSE→FIX]`. ldqis carries the canonical line (ldqis #200).

## In flight: `techne:board` (branch `feat/board`)

One user-owned GitHub Projects board, Status = Idea, Issue, In PR, Merged, Live, named by
`[board] owner/number` in `~/.claude/techne.toml` (absent = every board feature is a no-op).

Done:
- `_shared/project_board.py` (imports on 3.9; config needs tomllib): trigger
  detection, URL extraction, gh with one time budget, ID cache in `~/.cache/techne/`.
- `hooks/board_add.py` + PostToolUse entry in `hooks/hooks.json` (`if: Bash(gh *)`).
- `skills/board/` SKILL.md + `scripts/board.py`: show, sync, idea, live, init (init sets
  Status via GraphQL `updateProjectV2Field.singleSelectOptions`, keeps IDs of kept options,
  refuses to drop an option an item uses, prints the `[board]` table and workflow clicks).
- Tests: `tests/test_board_hook.py` (in HOOK_TESTS, runs on 3.9), `tests/test_board_script.py`,
  stub gh `tests/fixtures/gh_stub.py` + `gh_stub` fixture. Docs page, config schema, eval case.

Review fixes (PR #186): the hook takes only URL-only lines and a top-level `html_url`, never
moves an item already on the board (GraphQL `resource.projectItems` check before adding),
matches `gh issue/pr new` and wrappers outside quotes and heredocs, reads techne.toml only with
tomllib (no fallback; below 3.11 it is a silent no-op), and caps its failure line under 300.

Not verified live: the token here lacks the `project` scope, so every gh project call is
stub-tested only. After merge: `gh auth refresh -h github.com -s project`, then
`/techne:board init --title ajsoftworks`, add the printed table, set the two workflows,
`/techne:board sync`.

Verify: `make validate`.

### Landed on main: elenchus review tiers (#187)

Three roles (author dispatches and relays, dispatched reader runs one round and writes nowhere,
independent reader runs every phase) and two tiers (high: `/code-review high` on the PR or branch
first, for a new subsystem, a destructive op added or fed, persisted state, a security, privacy,
access or governance boundary, or a sensitive target; light: the reader alone; unsure is high).

### Landed on main: elenchus says when the review loop ends (#185)

`## When the review loop ends` in the elenchus SKILL.md and docs page: no fixed round count; one
reproduction attempt per unproven finding before each report; continue while a reproduced
Blocking/Should-fix finding is reachable, stop otherwise; open findings go in the Phase 5 comment
or an existing linked issue; a long loop pauses for the user. Took five review rounds; the first
draft's Porter et al. 1997 citation was dropped (two sessions beat one for one-person teams).

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
