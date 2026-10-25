# techne — Implementation scratchpad

The active TODO list for whatever's in flight **right now**: current PR, open design question,
immediate next pickup. Queued specs and ordering live in [ROADMAP.md](./ROADMAP.md); landed work
moves to its dated Shipped log. Over ~50 lines means something referential crept in.

## In flight

- **#207 budget mode** (branch `feat/phylax-budget-mode`): `hooks/budget.py` (session, prompt,
  agent modes) reads the rate_limits `hooks/budget_snapshot.py` saves from the status line
  (copied to `${CLAUDE_PLUGIN_DATA}` at session start). Level per window from pace (used% minus
  elapsed%), higher window wins; frugal rewrites an Opus Agent call to Sonnet via
  `updatedInput` (live-tested on 2.1.302: honoured, no permissionDecision needed).
  Background agents pay (`PHYLAX_BUDGET_ROLE=background`); interactive sessions opt in with
  `PHYLAX_BUDGET=on`; `/phylax:budget off [hours]` pauses those. Reader r1 fixes in; r2 next.
  Owed by AJ: the global CLAUDE.md line naming the option (drafted in the PR).
  Verify: `flock /tmp/fleet-heavy.lock timeout 600 uv run pytest tests/test_budget.py
  tests/test_phylax_doctor.py` and `make test-hooks-oldest`.

## Open Minors (recorded, not scheduled)

- #198 scan: overlapping names report one; an acronym-boundary name (`ABCTool`) is not split;
  tag messages and author names are not scanned.
- #201: `hook_env` keeps `GIT_CONFIG_COUNT`/`KEY_n`/`VALUE_n`/`PARAMETERS`, and two in-process
  git-guard tests read the developer's global git config.
- #204: a cygwin or msys python3 looks for managed agents at the Linux path.
- #208: check 15 keeps an inherited `GIT_DIR` or `GIT_INDEX_FILE` (hygiene.py strips them).

## Then

- #96 commit guards on Git 2.54 config hooks: needs git 2.54 or newer here (WSL has 2.43).
- #129 onboarding follow-ups; #87 flaky behavior-deslop eval gate; #86 `make test` red on macOS;
  #118 and #119 dokimasia matching bugs.

## Skill collection state

The directory listing of `plugins/*/skills/` is the source of truth; README's per-skill tables
carry the inventory, and ROADMAP's Shipped log records each addition.
