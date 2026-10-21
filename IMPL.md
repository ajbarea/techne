# techne — Implementation scratchpad

The active TODO list for whatever's in flight **right now** — current
PR, open design question blocking me, immediate next pickup. Queued
specs, cross-skill themes, and "next up" ordering live in
[ROADMAP.md](./ROADMAP.md). Git history is the permanent record of
how each skill was designed.

If this file is more than ~50 lines, something queued or referential
has crept in; extract it back to ROADMAP.

## In flight: solo repos act, team repos ask (branch `feat/solo-act-team-ask`, PR #189)

Done: `_shared/repo_kind.py` classifies solo/team (only GitHub facts make solo; unsettled is
team); docsync acts on solo repos, ci-audit `[PROPOSE→FIX]`, gates never `[FIX]`. 12 review
rounds; rounds 11-12 hit bugs from the previous fix, so per elenchus the fuzzy owner matcher was
replaced (2026-10-21, AJ: decide by research) with ONE canonical marker, `- owner: team` under
`## repo`; any look-alike reads team and the reason names the line (RFC 9413 s.2.1, 4.2, 5.1).
Template no longer ships the line. Round-12 fixes landed 2026-10-21: `github_slug` (ssh alias) lives in `git_env.py` and hygiene
uses it; GraphQL first, then collaborators, then invitations, serially and only while still
possibly solo (GitHub REST best practices); `same_remote` only when nothing else matched;
`local_env()` = git's runtime list, LOCAL_ENV only when git cannot be asked; heuresis doctor
uses `without_repo_overrides()`. Mutation check: 14/14 killed (strict marker, lint path, empty
`owner:`, call order, fallbacks).
Round 13 (one high-tier review: /code-review high + elenchus reader, verdict mergeable) fixed:
plural/`ownership` look-alikes (`- owner: teams` read solo), advice both ways in the reason,
HEAD copy decoded from bytes, scp alias never a port, relative paths never reach ssh, hygiene
git env strips git's local list. Mutation check 21/21 killed. Left to #190: hygiene print_env's
inline kind rule. Not changed: `ssh -G` in hygiene --auto (measured ~10 ms, capped 10 s).
Light reader on the round-13 delta: HEAD read had dropped doctor_lib.run's process-group
guards; now `doctor_lib.run_bytes` (run decodes on top of it) with GIT_NO_LAZY_FETCH=1;
resume_state git env strips git's local list too. Mutation 4/4. High-tier rerun owed (the hygiene
env change reaches existing destructive git calls). Full suite was memory-reaped at 91%, no
failures; rerun only when memory allows (AJ's call).
High-tier rerun (after the 12:26 WSL crash): /code-review high + reader, verdict mergeable.
Fixed: working-copy read is regular-file only and capped at 1 MiB (a /dev/zero symlink grew
memory without bound); reasons name the copy (working copy, current commit, default branch);
`ssh -G` back through doctor_lib.run (group kill). Mutation 5/5. Left as Minor: the lint misses
owner values without "team" (`- owner: lab`), documented contract; a kind-less path match hides
a same-origin team entry (to #190).
Light reader on that delta: git_env's `import doctor_lib` needed the caller's sys.path (test
isolation + load by file path); now it appends its own folder. Working-copy read uses os.stat
(3.14 swallows EACCES in is_file), names a broken link. Mutation 4/4. Review loop stopped at
AJ's budget (one high-tier review); remaining Minors documented in the PR. Next: CI green, merge.
Next, in order:
1. Full suite on a frozen tree; CI green; merge (squash).
2. ldqis follow-up: rewrite its owner line to canonical `- owner: team`.
Verify: `make validate`.

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
