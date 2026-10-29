# techne — Implementation scratchpad

The active TODO list for whatever's in flight **right now**: current PR, open design question,
immediate next pickup. Queued specs and ordering live in [ROADMAP.md](./ROADMAP.md); landed work
moves to its dated Shipped log. Over ~50 lines means something referential crept in.

## In flight

Branch results/quality-baseline, worktree `.claude/worktrees/baseline`: techne#249. The first 4
of 30 Opus baseline runs failed hidden tests that checked names or wording their reports never
gave. Done on the branch (3818b38 .. c5bd08b, pushed): interface notes completed on 8 tasks;
`run.py` `interface_gaps` + `defined` make `--check-tasks` fail such a task (55 hand mutations,
all killed; on the real parents' failures the old notes flag the four tasks no model could pass,
techne-206, sphragis-149, -186, -212, and the new notes flag nothing); `quality/DEVIATIONS.md`
records it (598 of 600 words); old runs in `quality/results/2026-10-29-baseline-void/`.
Review: r1 reader, r2 `/code-review medium`, r3-r6 readers (each found Should-fix, all fixed;
recurring classes got structural fixes), **r7 clean** (Minors only). `--check-tasks` on 6c56cbd:
10/10 ok; on c5bd08b 7/7 ok when stopped for the move to RIT.

Next, in order:
1. r7 Minors (optional but cheap; then ONE fresh Opus reader verifies those fixes only):
   (a) `interface_gaps` docstring + DEVIATIONS: "the fix added it" → "the fix added it or
   stopped passing it; either way the report must name it in a code span"; (b) add a pytest
   temp path value (`/tmp/pytest-of-x/p0`) to `test_interface_gaps_read_every_unrecognized_flag`
   (kills the `FLAG` lookbehind mutant); (c) a test with wording only in a parent comment
   (`before` is whole-file); (d) a missing-file failure on a file the parent already has (no gap).
2. `uv run python quality/run.py --check-tasks` on the final commit, all 10 ok (log to
   `~/.local/state/techne-quality/check-tasks-9.log`; ~50 min; never under flock).
3. PR (links #249; body: why/what/status, results table: old notes 4 tasks flagged, new 0;
   deferred ledger: junit double parse, `messages` flag, repeated git show, check_tasks'
   --name-status without -z, r6 minors 4 and 6, r7 informational 5) → merge.
4. Restart the baseline from main's commit in `quality/results/2026-10-29-baseline-2` on RIT
   (`CLAUDE_CONFIG_DIR=/home/ajbar/.claude`; edit `~/.local/state/techne-quality/resume.sh`'s
   QUALITY_OUT and its `cd` to a fresh worktree of main first), in tmux `quality-resume`:
   `tmux new-session -d -s quality-resume -e CLAUDE_CONFIG_DIR=/home/ajbar/.claude "bash
   ~/.local/state/techne-quality/resume.sh"`. Rerunning resumes; always pass `-e CLAUDE_CONFIG_DIR`.
Never wrap `run.py` or `make quality` in `flock /tmp/fleet-heavy.lock`: run.py takes that lock
itself, so the wrapper deadlocks. A lock held long after every job ended is likely an orphan that
inherited the fd (klepsydra#193: a test tmux server held it 40 min on 10-29): `lsof
/tmp/fleet-heavy.lock`. Progress: `grep tests= ~/.local/state/techne-quality/baseline.log`. A
skill suite with any "ended on an API error" run is invalid: delete its JSON and rerun. Then
commit results under `quality/results/` by PR and start techne#226.

Before it: the logging rollout (10-28/29) is done, one PR per repo, each re-checked `logging standard ✓`
on main with #230's check: sphragis #225, techne #230, pharos #102, ariadne #76, keryx #69,
ajbarea.github.io #137, papers #115, phalanx-fl #139, periplus #62, talks #41, the coding-gym repo
#7, the CSCI-739 class repo #22, ldqis #209 (klepsydra met it in #145). Left: kourai-khryseai's code
(harvest-only since Aug 2026; 94 G004/G201/G003, an uncapped FileHandler in
`scripts/diagnose_m14_timeout.py`, templates without the lint rules) until AJ asks; velocity-fl
skipped (harvest-only).

Owed by AJ: from #209, the status line step `/phylax:setup` prints and the global CLAUDE.md
routing line; GitGuardian incident 39081601 (a fake test token in #215, gone from the history)
to mark as a false positive in the dashboard. Same for ariadne incident 39247473 and 39249419
(fake Neo4j credentials in the #76 tests, squashed out of the PR before merge).

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
