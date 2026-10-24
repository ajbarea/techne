# techne — Implementation scratchpad

The active TODO list for whatever's in flight **right now**: current PR, open design question,
immediate next pickup. Queued specs and ordering live in [ROADMAP.md](./ROADMAP.md); landed work
moves to its dated Shipped log. Over ~50 lines means something referential crept in.

## In flight

- **#204** (closes #197, branch `fix/model-guard-agent-overrides`): `require_subagent_model`
  reads a managed, project or user definition named `general-purpose`, `claude`, `Explore` or
  `Plan`, which replaces the built-in (Claude Code 2.1.302 layers definitions by name). The walk
  starts at `CLAUDE_PROJECT_DIR`; anything unreadable allows the call. code-review high (10
  findings, 8 fixed); reader r1 running. Verify: `flock /tmp/fleet-heavy.lock timeout 600 uv run
  pytest tests/test_model_guard.py` and `make test-hooks-oldest`.
- **#206** (closes #205): sisters check 15 minors; readers r1 and r2 done, merging.

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
