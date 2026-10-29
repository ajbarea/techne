# techne — Implementation scratchpad

The active TODO list for whatever's in flight **right now**: current PR, open design question,
immediate next pickup. Queued specs and ordering live in [ROADMAP.md](./ROADMAP.md); landed work
moves to its dated Shipped log. Over ~50 lines means something referential crept in.

## In flight

Logging rollout (fleet, 10-28/29), one PR per repo. This branch, `chore/logging-rollout`, is techne's
own PR: the standard says `-ra` (`-rs` alone drops FAILED lines) and `RUFF_OUTPUT_FORMAT` in a
workflow `env:`; `stderr-for-errors` also reads an echo or `print()` right before a non-zero exit;
techne's own hits fixed. Repo PRs: sphragis #225, pharos #102, ariadne #76; then keryx, kourai,
ajbarea.github.io, papers, phalanx-fl, periplus, talks, the coding-gym repo, the CSCI-739
class repo, ldqis. Status per repo:
the queue file's Running-now line.

Owed by AJ: from #209, the status line step `/phylax:setup` prints and the global CLAUDE.md
routing line; GitGuardian incident 39081601 (a fake test token in #215, gone from the history)
to mark as a false positive in the dashboard.

## Logging gaps on main, 10-28 (logcheck.py plus the review pass)

| Repo | Finding | Severity |
|---|---|---|
| sphragis | lint-python: ruff lacks G, LOG; 124 files use print, 1 uses logging | medium |
| sphragis | log-file-tracked: 842 files in datasets/logs/ (evidence, to skip) | low |
| sphragis | review: no `*.log` ignore (only logs/*), pytest without -ra, ruff without annotations | low |
| pharos | lint-python: ruff lacks G, LOG; 47 print files | medium |
| pharos | review: no `*.log` ignore, pytest without -ra in ci.yml, ruff without annotations | low |
| ariadne | lint-python: ruff lacks G | medium |
| ariadne | review: a bad `ARIADNE_STREAM_STALL_S` silently ignored; silent OTel and graph fallbacks; pytest without -ra | medium |
| techne | check ✓; review: no `*.log` ignore; `-rs` drops FAILED lines; shell/Python failure text on stdout the check missed | medium |
| keryx | lint-python: ruff lacks G, LOG; 9 files log | medium |
| keryx | review: no `*.log`/logs/ ignore, pytest without -ra | low |
| kourai-khryseai | lint-python: ruff lacks G (94 G004/G201/G003 to fix); templates lack G, LOG | medium |
| kourai-khryseai | unbounded-log-file: scripts/diagnose_m14_timeout.py FileHandler | medium |
| kourai-khryseai | lint-js: templates/frontend, tools/voice-lab | low |
| ajbarea.github.io | lint-js: no no-console rule; 7 files call console.log/info/debug | medium |
| papers | lint-python: ruff lacks G, LOG; pytest without -ra | low |
| phalanx-fl | lint-python: ruff lacks G, LOG; no `*.log` ignore | low |
| periplus | lint-js: no no-console rule; no `*.log`/logs/ ignore | low |
| talks | lint-python: ruff lacks G, LOG; no `*.log` ignore | low |
| the coding-gym repo | lint-python: ruff lacks G, LOG; no `*.log` ignore | low |
| csci739-qfl-privacy | lint-python: ruff lacks G, LOG; pytest -q without -ra | low |
| ldqis | lint-js + lint-python; no `*.log` ignore | low |
| klepsydra | meets the standard (#145) | - |
| velocity-fl | lint-python, lint-rust | skipped: harvest-only |

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
