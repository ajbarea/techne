# techne — Implementation scratchpad

The active TODO list for whatever's in flight **right now**: current PR, open design question,
immediate next pickup. Queued specs and ordering live in [ROADMAP.md](./ROADMAP.md); landed work
moves to its dated Shipped log. Over ~50 lines means something referential crept in.

## In flight

techne #214 `techne:logging` (branch `feat/logging-standard`): the standard, `logcheck.py`
with tests, sisters check 16, a ci-audit section, docs page; 3 review rounds done. Owed by AJ from #209:
the status line step `/phylax:setup` prints, and the global CLAUDE.md routing line.

## Logging rollout (stopped here 10-26; AJ moved sphragis and the MSR paper to the top)

One PR per repo: `/techne:logging`, fix the check's findings and the review items, then
reproduce one real failure and quote the log line that names it (before and after). Baseline
from `logcheck.py --summary` on 10-26:

1. klepsydra (wait until its other agent is done): lint-rust in `src-tauri` and
   `src-tauri/fleet`, lint-js, lint-python. Backend logs with `eprintln!` plus the capped
   `problem_log`: move to `tracing` with a `RollingFileAppender::builder().max_log_files(n)`
   file in the OS log folder (or `tauri-plugin-log` with `KeepSome(n)`), front end through
   `@tauri-apps/plugin-log`, hooks log the Claude `session_id` as the run id.
2. sphragis: lint-python; its 834 committed `datasets/logs/` files are evidence, so add
   `- skip: datasets/logs/` under `## logging`.
3. keryx, ariadne, pharos, the coding-gym repo, phalanx-fl, papers, talks, the CSCI-739 class repo:
   lint-python (select `G` and `LOG`, fix what ruff then reports), plus the review pass.
4. ajbarea.github.io, periplus: lint-js.
5. ldqis (team repo): propose lint-js and lint-python fixes in a PR, ask first.
6. Left out: kourai-khryseai and velocity-fl (harvest-only since Aug 2026).

## Back on the queue

- docsync covers repo metadata (GitHub description, homepage, topics, README lead vs what the
  repo does; solo applies with `gh repo edit`, team proposes; eval case; docs page).
- Poppler on the CI runner so the 3 skipped web-deck tests run; confirm in the CI log.

## Open Minors (recorded, not scheduled)

- #214 logcheck: an awk `}'` line closes an enclosing `{ ... } >&2` group; a Rust appender
  builder split over two statements is flagged; a JS ternary branch (`c ? token : "x"`) and a
  TS arrow parameter (`(token: string) =>`) are read as object fields; `$(( (a) << b ))` and
  `<<\EOF` are misread; `outside_quotes` ignores `\"` inside double quotes.

- #198 scan: overlapping names report one; an acronym-boundary name (`ABCTool`) is not split;
  tag messages and author names are not scanned.
- #201: `hook_env` keeps `GIT_CONFIG_COUNT`/`KEY_n`/`VALUE_n`/`PARAMETERS`, and two in-process
  git-guard tests read the developer's global git config.
- #204: a cygwin or msys python3 looks for managed agents at the Linux path.
- #208: check 15 keeps an inherited `GIT_DIR` or `GIT_INDEX_FILE` (hygiene.py strips them).
- #209: the frugal table text in budget.py says "Opus or Fable"; the guard also moves `best`.
- #209: `/phylax:budget off 1e-9` is accepted (a pause already over); two accounts active at
  once in one config folder make the snapshot alternate; a symlink loop at the snapshot path
  is replaced by a file.

## Then

- #96 commit guards on Git 2.54 config hooks: needs git 2.54 or newer here (WSL has 2.43).
- #129 onboarding follow-ups; #87 flaky behavior-deslop eval gate; #86 `make test` red on macOS;
  #118 and #119 dokimasia matching bugs.

## Skill collection state

The directory listing of `plugins/*/skills/` is the source of truth; README's per-skill tables
carry the inventory, and ROADMAP's Shipped log records each addition.
