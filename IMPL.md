# techne — Implementation scratchpad

The active TODO list for whatever's in flight **right now**: current PR, open design question,
immediate next pickup. Queued specs and ordering live in [ROADMAP.md](./ROADMAP.md); landed work
moves to its dated Shipped log. Over ~50 lines means something referential crept in.

## In flight

Nothing. #220 (heuresis refuses a relative folder, techne#219) and the 10-26 techne batch are merged: #215 docsync repo metadata, #216 poppler on CI,
#217 graphe `pptx --editable` (see ROADMAP Shipped). Next pickup: the logging rollout below.

Owed by AJ: from #209, the status line step `/phylax:setup` prints and the global CLAUDE.md
routing line; GitGuardian incident 39081601 (a fake test token in #215, gone from the history)
to mark as a false positive in the dashboard.

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

## Open Minors (recorded, not scheduled)

- #215 repo_meta: a 1-2 word subtitle under the title hides the lead; a 3+ word section heading
  before any prose reads as a tagline; `*args and **kwargs`, `> ## Warning` and pipe-less tables
  are read as prose.
- #216: the poppler guard lives in test_slides_web.py, so test_pdf_render_e2e.py run alone has
  none; `HAVE_POPPLER` ignores pdffonts and pdftoppm; test_latex_e2e ignores `TECHNE_NO_POPPLER`.
- #217: a ::before space in right-to-left text is lost in PowerPoint; rotated text lands in a
  narrow box; `system-ui` maps to Arial, so a deck drawn in another system face shifts.
- slides.py `_READ_SLIDE`'s screen-reader check compares screen pixels with 1px, so at a deck
  scale above 1 it misses sr-only text (pptx_editable measures offsetWidth instead).

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

## Resume: shared footer brand mark (Review #2, done 2026-10-28)

- #224 merged: the shared stylesheet draws the mark (`.footer-brand`, a text-colored mask);
  `extra.brand_mark` is retired. Cause of the gap: only the partial was shared, the image and its
  dark-mode rule were per-site.
- Synced and merged: ariadne#75, keryx#63, pharos#100, periplus#61, phalanx-fl#137,
  sphragis#222, Hackathon#13. Live re-check 10-28: every inner page shows the mark and its own
  repo's GitHub icon, light and dark; hero landings hide the footer by design (as kourai does).
- kourai-khryseai and velocity-fl keep the old partial (harvest-only; they already show the mark).
