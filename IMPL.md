# techne — Implementation scratchpad

The active TODO list for whatever's in flight **right now**: current PR, open design question,
immediate next pickup. Queued specs and ordering live in [ROADMAP.md](./ROADMAP.md); landed work
moves to its dated Shipped log. Over ~50 lines means something referential crept in.

## In flight: #207 budget mode, PR #209 (branch `feat/phylax-budget-mode`, this worktree)

Done: `hooks/budget.py` (modes session, prompt, agent; off/on/status for `/phylax:budget`),
`hooks/budget_snapshot.py` (status line step, copied to `${CLAUDE_PLUGIN_DATA}`), options,
doctor `budget` line, docs, `skills/budget`, marketplace description test. Live test: Agent
honours `updatedInput` without permissionDecision (2.1.302). Reviews: code-review medium (8 of
10 fixed, 2 declined in PR body), reader r1 (fixed), reader r2 (2 Should-fix + 8 Minors fixed
in 540e149, failing tests first; 9 of 9 hand mutants on the new guards killed). Next: reader r3
(the cap; no /code-review high), fix what it holds on, then merge.
Then: update the PR body counts, re-read PR and issue comments, squash-merge, move #207 to
ROADMAP's dated log, remove this worktree. Owed by AJ: the global CLAUDE.md line (drafted in
the PR body) and the status line step `/phylax:setup` prints.
Verify: `flock /tmp/fleet-heavy.lock timeout 600 uv run pytest tests/test_budget.py
tests/test_phylax_doctor.py` and `flock /tmp/fleet-heavy.lock timeout 1200 make test-hooks-oldest`,
`make lint`, `make guards build plugin-validate`.

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
