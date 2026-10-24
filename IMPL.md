# techne — Implementation scratchpad

The active TODO list for whatever's in flight **right now**: current PR, open design question,
immediate next pickup. Queued specs and ordering live in [ROADMAP.md](./ROADMAP.md); landed work
moves to its dated Shipped log. Over ~50 lines means something referential crept in.

## In flight: release scan for private repo names (#198, branch `feat/private-name-scan`)

`scripts/check_private_names.py`, run last in `make guards`: owner's private repo names from
`gh` at run time. Scans staged blobs, tracked and addable working-tree files, blobs, paths and
messages of commits no remote has, the branch name, and file names. A name matches as a word or
CamelCase part, any case, parts joined by any run of `-`, `_`, `.`, space or none. Names in
`<git-common-dir>/info/private-words` (this clone: the three that are ordinary words) match
only as slugs `owner/name` (also `.git` or a full stop after) and `name#N`. Any gh failure
skips loudly (CI included); git, gh output or words-file failures exit 2.
Review: code-review high (10 findings, 8 fixed, 2 declined); reader r1 (3 Should-fix, 4 Minor
fixed); reader r2 (PR body drift fixed; a prefilter search per text cut the scan from 11.5 s
to about 5 s; two untested halves got tests). Next: reader r3 (the cap), then merge.
Open Minors: a spaced name wrapped across two lines; a history hit names no commit.
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
