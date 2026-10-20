# techne — Implementation scratchpad

The active TODO list for whatever's in flight **right now** — current
PR, open design question blocking me, immediate next pickup. Queued
specs, cross-skill themes, and "next up" ordering live in
[ROADMAP.md](./ROADMAP.md). Git history is the permanent record of
how each skill was designed.

If this file is more than ~50 lines, something queued or referential
has crept in; extract it back to ROADMAP.

## In flight

### elenchus: when the review loop ends (feat/elenchus-iterating)

Done: `## When the review loop ends` in the elenchus SKILL.md and docs page. No fixed round count;
one reproduction attempt per unproven finding before each report; continue while a reproduced
Blocking/Should-fix finding is reachable, stop otherwise; open findings go in the Phase 5 comment
or an existing linked issue; a long loop pauses for the user. Four review rounds so far; Porter et
al. 1997 dropped (two sessions beat one for one-person teams). Next: round 5, CI green
(`plugin-validate`/`plugin-test` need Linux npx, CI only), squash-merge. Verify: `make validate`.

### Landed: resume state from the branch's IMPL.md (#180)

`_shared/resume_state.py` reads a worktree's state from local git (IMPL.md compared at the
merge-base, commits, uncommitted paths, ahead/behind its pushed branch; failures read as
unknown). The `resume_brief` option's SessionStart hook gives it to a fresh session; `sisters`
marks a dirty, idle, unmerged worktree whose IMPL.md never changed as not resumable. Known
limits are in the PR body. Follow-up: klepsydra#36 (Resume from a gone card).

### Landed: heuresis phase 2, the gold set

`scripts/heuresis_gold.py run` (or `make heuresis-gold GUARD=<ideas repo>`) triages each case in
`plugins/heuresis/gold/cases.yaml` with this checkout's plugin, in a scratch ideas repository under
`~/.local/state/heuresis-gold`, and `heuresis/gold.py` grades the runs. Each grade records the case
labels and the commit under test; `report` refuses grades whose labels changed, and `regrade`
re-scores kept work folders without reviving a failed run. `RESULTS.md` is the generated summary of
the last full run; regenerate it rather than editing it.

### Then: commit guards on Git 2.54 hooks (#96)

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
| `techne` | **Observation** | `theoros` |
| `techne`, `graphe`, `heuresis`, `phylax` | **Setup** | `setup` (a read-only doctor per plugin) |
| `graphe` | **Document build** | `latex`, `pdf`, `paper`, `paper-review`, `slides` |
| `dokimasia` | **Bibliography** | `check` |
| `heuresis` | **Ideas** | `idea`, `setup` |
| `epistole` | **Mail** | MCP server, setup |
| `phylax` | **Hooks** | git guards (a mod, `hooks/register.ts`), `restart_on_update` (command hooks) |
