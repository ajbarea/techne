# techne — Implementation scratchpad

The active TODO list for whatever's in flight **right now**: current PR, open design question,
immediate next pickup. Queued specs and ordering live in [ROADMAP.md](./ROADMAP.md); landed work
moves to its dated Shipped log. Over ~50 lines means something referential crept in.

## In flight

techne#255 (branch fix/quality-leak-audit, no PR yet): the leak check reads bash with
tree-sitter-bash instead of matching text; `run.py --reaudit` recomputes recorded runs' flags;
DEVIATIONS.md 2026-10-31 logs it. Reproduced on a copy of baseline-2: 43 leak flags on 9 runs
drop to 2 (techne-220 r1, `--id ../../etc`), every dropped one a local command. 327415f adds
tests/test_quality_shell_diff.py (360 generated commands run under real bash with stub network
programs; all agree); four hand mutants (timeout wrapper, raw-string unquote, eval, heredoc feed)
each go red. Lint clean; full `make test` not yet finished (stopped for the 10-31 account hold).

Next, in order:
1. `timeout 1800 flock /tmp/fleet-heavy.lock timeout 1500 make test` in this worktree.
2. Open the PR (Closes #255, label bug, assignee ajbarea), then elenchus: `/code-review medium`
   + a fresh Opus reader per round, until clean (registered-study harness), then a verify pass.
3. Merge; when the baseline (tmux quality-resume, RIT, results/quality-baseline-2) reaches 30
   runs, `uv run python quality/run.py --reaudit quality/results/2026-10-29-baseline-2` from
   main, then the judge pass + analyze, results PR, then techne#226.
Never wrap `run.py` or `make quality` in `flock /tmp/fleet-heavy.lock`: run.py takes that lock
itself, so the wrapper deadlocks. A lock held long after every job ended is likely an orphan that
inherited the fd (klepsydra#193): `lsof /tmp/fleet-heavy.lock`. A skill suite with any "ended on
an API error" run is invalid: delete its JSON and rerun.

Owed by AJ: from #209, the status line step `/phylax:setup` prints and the global CLAUDE.md
routing line; GitGuardian incidents 39081601 (techne #215), 39247473 and 39249419 (ariadne #76),
fake test credentials, to mark as false positives.

## Resume: quality evals, hooks, review-loop ledger (techne-evals brief, 10-29)

- ✅ #235 `scripts/review_loop_mine.py` + `quality/review-loop/2026-10-29.md`: 95.3% of
  class-tagged review findings (60.8% of all) since the catalog existed were classes it
  already held; no class added after its first commit. Five rounds + verify.
- ✅ #237 phylax `email_greeting` (+ `email_timezone`): Good morning/afternoon/evening by
  the clock, never Hi/Dear, on epistole and Gmail-connector drafts, sends and replies.
- ✅ #238 elenchus findings ledger + `checklist` + daily `foldback.sh` (catalog PR, one
  "Mechanical check" issue at 3 PRs/week, Retired field). Seven rounds. Timer installed on
  this PC: `~/.config/systemd/user/elenchus-foldback.{service,timer}` (06:30) running
  `~/.local/bin/elenchus-foldback`, which resolves the installed plugin path.
- 📋 #236: two hook proposals (skipped git hooks; commits gated on a piped verify); AJ picks.
- ✅ #239 (issue #244) pre-registration of the budget-trial quality evals: `quality/`
  (PREREGISTRATION.md, run.py, analyze.py, tasks.toml with 10 replayed PRs, gold-tests.json,
  judge.md, sandbox.json) and the `quality-*` skill eval cases. Each results folder's
  `set.json` pins phase, version and input hashes; a differing resume is refused. File tools
  are denied /home (but the run's saved outputs), /tmp, /mnt, /root. `--check-tasks` (all 10
  ok 10-29) and `--smoke` (Haiku) validate it; one run.py process at a time. Recorded minors:
  two redundant resolve() checks in read_denials; the store add-dir also allows writes; a
  session could write `.claude/settings.local.json` (globally gitignored), judged inert by
  reading the binary, not probed; `--setting-sources` would close it.
- 📋 Baseline, in order: `make quality MODE=normal PHASE=baseline QUALITY_OUT=...` (Opus,
  3 repeats, judge pass, analysis) and `make quality-skills` (Opus) → commit results under
  `quality/results/`; then techne#226 (fold-or-keep audit) measured on them. The
  sonnet/opus comparison (pilot → sizing → confirmatory) runs only when AJ schedules the
  budget trial. Stretch: 10 DeepSWE tasks on TIGRIS, never this PC.
- 📋 #234 step 5: rerun `review_loop_mine.py` a week after #238 (from 2026-11-05), now
  reading the ledger too, and report the change in repeat-class share.

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

- #230 logcheck: `lint-js` passes once a `noConsole` or `no-console` rule exists, without checking
  that it covers the code (periplus's first `biome.json` missed the inline scripts in `index.html`);
  a one-line `log() { echo "$*"; }` before `exit 1`, `printf -v`, and `{ echo` split from
  `exit 1; } >&2` are flagged; `raise SystemExit(-1)` is not read.
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
