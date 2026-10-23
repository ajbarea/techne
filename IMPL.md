# techne — Implementation scratchpad

The active TODO list for whatever's in flight **right now**: current PR, open design question,
immediate next pickup. Queued specs and ordering live in [ROADMAP.md](./ROADMAP.md); landed work
moves to its dated Shipped log. Over ~50 lines means something referential crept in.

## In flight: release scan for private repo names (#198, branch `feat/private-name-scan`)

`scripts/check_private_names.py`, run last in `make guards`: owner's private repo names from
`gh repo list <owner> --visibility private` at run time; every `git ls-files --cached --others
--exclude-standard` file and file name; whole word, any case, `-`/`_`/space interchangeable;
names in `<git-common-dir>/info/private-words` (untracked, shared by worktrees) match only as
`owner/name` or `name#N`. Skips loudly on no gh, exit 4 or no visible private repo (CI); other
gh or git failures exit 2. Mutation check: 15 of 15 hand mutants killed.
This clone's words file lists the three private names that are ordinary words. Fixed four real
hits (`owner/name` shapes in the heuresis spec, ROADMAP, `test_board_hook.py`).
Verify: `flock /tmp/fleet-heavy.lock timeout 600 uv run pytest tests/test_private_names.py -q`
and `uv run python scripts/check_private_names.py`.

## Next, in order

1. #195 phylax doctor reads option values case-insensitively, hooks match only lowercase `true`.
2. #196 share phylax hook env and handler-runner test helpers through `tests/conftest.py`.
3. #197 user or project agent named Explore or Plan checked as the built-in (decide the cost).
4. Sisters check 15 minors (from #193, `scripts/agents_md.py`):
   - A wholly ignored non-vendored folder (`scratch/`, or `.claude/` ignored) hides a CLAUDE.md a
     session started there loads. Fix: for each `dir/` entry of the `--directory` listing, also
     check that folder's top level (`CLAUDE.md`, `.claude/CLAUDE.md`, `CLAUDE.local.md`, plus
     `dir/CLAUDE.md` when dir is `.claude`); test beside node_modules.
   - Non-UTF-8 path + strict UTF-8 stdout raises UnicodeEncodeError and aborts later repos. Fix:
     `sys.stdout.reconfigure(errors="backslashreplace")` in main; test a bytes-named folder in a
     subprocess with PYTHONIOENCODING=utf-8.
   - Dead `found = set()` in `candidates()`; nested CLAUDE.local.md gets "move into AGENTS.md"
     advice (should get the personal-notes advice); a corrupt index reads "not a git repository".
   Verify: `flock /tmp/fleet-heavy.lock timeout 600 uv run pytest tests/test_sisters_agents_md.py -q`.

## Then

- #96 commit guards on Git 2.54 config hooks: needs git 2.54 or newer here (WSL has 2.43).
- #129 onboarding follow-ups; #87 flaky behavior-deslop eval gate; #86 `make test` red on macOS;
  #118 and #119 dokimasia matching bugs.

## Skill collection state

The directory listing of `plugins/*/skills/` is the source of truth; README's per-skill tables
carry the inventory, and ROADMAP's Shipped log records each addition.
