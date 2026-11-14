# techne — Implementation scratchpad

The active TODO list for whatever's in flight **right now**: current PR, open design question,
immediate next pickup. Queued specs and ordering live in [ROADMAP.md](./ROADMAP.md); landed work
moves to its dated Shipped log. Over ~50 lines means something referential crept in.

## seele (branch feat/seele, issue #339)

- Slice: `/techne:seele`, a blind panel of models with a chair that holds no seat. One PR, not merged by the author.
- ✅ `plugins/techne/skills/seele/` (SKILL.md, `scripts/seele.py`, references, logo), `plugins/techne/agents/seele-seat.md`,
  `tests/test_seele.py` (in `HOOK_TESTS`, so it also runs on the oldest python3), docs page, registrations, routing evals.
- ✅ First live run: Opus, Sonnet, `fleet:agy`, `fleet:copilot`, Fable chair.
- ✅ PR #340 open (not merged). Reviewed by fresh readers: one full review, then verify passes on each set of fixes
  (nine rounds, past the ceiling of five; rounds 4 to 8 each found one more shape the chair's `PICK` line could be misread in).
  The parser now has one rule in place of a list of shapes (`second()`): the line may name one candidate id,
  the picked candidate's own text may be quoted, and anything else that names a candidate (`B over C`,
  `B; C is close`, `B: Plan A`) or a tie is refused, so the chair is asked again. A refusal costs one dispatch;
  a misread would report the wrong winner.
  Open, known and unlikely: a second pick written as a small `a` or `i`, as a two-letter id in small letters, or as
  an ordinal (`B, the third too`), or with a look-alike letter from another alphabet, is not seen, and the line
  reads as B. So is an id straight after the pick's apostrophe (`B'C`), and a later `PICK: none` line
  under a real pick. The last verify pass (round 9) came back with these two nits and nothing else. `REASON: One sentence.` followed by more
  lines is read as a copied form line.
  Left open on purpose: the 2,000-character cap is per candidate, so a review-mode panel with many long changes can
  still pass a lane's page limit in round 2; the lane then refuses with both sizes and says what to shorten.
- ✅ 60 guards mutation-checked by hand (all killed); the list is in the PR. 167 tests.
- 📋 Next: answer review on the PR. The routing evals for `fires-seele` and `never-seele-code-review` have not run
  (`make evals`: real sessions, not part of `validate`). A live `ollama:` seat has only ever run against a stub.
- A run folder written before the second seat folder (`dir2`) existed cannot be tallied by this version; none were kept.
- Verify: `make lint`; `uv run pytest tests/test_seele.py`; `make validate` under the heavy lock.

## schole-fetch (branch feat/schole-fetch-list, issue #316)

- ✅ Issue #316 with research and design. ✅ Slice 1: `schole-fetch --list [--classes DIR] [--state F] [--record]`
  (`schole/fetch.py`, `tests/test_schole_fetch.py`, `tests/fixtures/schole_toc.json`), read-only: one toc GET per course.
- Next: review rounds (fresh Opus reader each, bug-class catalog), then wait for the module Download address and the
  visit-recording answer before any `--download` (opt-in flag, off by default).
- Verify: `make lint`; `uv run pytest tests/test_schole_fetch.py tests/test_schole_d2l.py`.

## In flight

**techne#277 performance + mutation testing**, four PRs in order, each reviewed with
/techne:elenchus (Opus readers); worktrees under `.claude/worktrees/`:
1. ✅ #282 latency budgets + git_guards 48.6→15.8 ms on a non-git call.
2. ✅ #284 CodSpeed (simulation, parsers only).
3. ✅ #287 hyperfine weekly bench: wall gate 1.15x against `bench/baseline-ci.json`, the median of
   seven pinned runs (`bench/median.py`); README says how to refresh it.
4. ✅ #290 mutation (scripts/mutation.py, weekly 16-shard sweep, per-PR --changed-since run).
   Five review rounds plus two verify passes. A kill counts only when the deciding tests pass
   unmutated; a timeout only when they finish unmutated within the same limit, else the module's
   tests judge it and a shared timeout is an error (exit 1 even with --report-only). Deferred:
   per-module budget is a share of test files, not test time; board_add/project_board never
   traced (GhStub env); legacy survivors #289; the runner is not mutated by itself (each mutant
   would rerun test_mutation.py, about 3 min).
5. ✅ #295 phylax parser speed-up: four review rounds plus a verify pass, clean. Greeting check
   stops at the first line (x879 same machine), body gate reads the body once (x1.66); a parser
   error is named on stderr and the plain body still checked; body_gate verdicts equal main's on
   240,420 comparisons (3.9-3.14).
6. ✅ #293 flaky bench temp-name fix (Heph's request, #292) merged 69bc788.
7. 📋 #301 phylax: refuse gh pr/issue create, comment and review that name no repo when gh would
   pick a repo other than origin's (worktree .claude/worktrees/fork-guard).
Readers: `flock -o /tmp/fleet-heavy.lock timeout -k 10 900 bash -c 'ulimit -v 3000000; ...'`,
append findings to the report file as confirmed (the 11-04 OOM was an orphaned pytest).
Report each merge to Heph (tmux pane in orchestrator.pane); `fleet done` after all four.

techne#249 is fixed in PR #252 (branch results/quality-baseline): the task notes state what the
hidden tests check, `--check-tasks` fails a task with a gap, `quality/DEVIATIONS.md` records it.
Seven reader rounds plus a verify pass, clean; `--check-tasks` 10/10 ok on 5ec4dc0. Old runs stay
in `quality/results/2026-10-29-baseline-void/`.

Next, in order:
1. Merge #252 on green.
2. Restart the Opus baseline from main in a fresh worktree on the RIT account (the default config
   folder): point `~/.local/state/techne-quality/resume.sh`'s `cd` at that worktree and its
   QUALITY_OUT at `quality/results/2026-10-29-baseline-2`, then
   `tmux new-session -d -s quality-resume -e CLAUDE_CONFIG_DIR="$HOME/.claude" "bash
   ~/.local/state/techne-quality/resume.sh"`. Rerunning resumes; always pass `-e CLAUDE_CONFIG_DIR`.
   Progress: `grep tests= ~/.local/state/techne-quality/baseline.log`.
3. Commit the results under `quality/results/` by PR, then start techne#226 measured on them.
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

- #287 bench: median.py has no test merging two patch releases of one python3 minor, or runs
  where only some carry instruction counts; the docs-threshold test matches a bare `1.05x`
  substring (assert on `past 1.05x`); compare notes "baseline on None" when neither summary has
  a cpu; median.py trusts the first summary's cpus/runs/warmup, raises KeyError on a missing key,
  and duplicates compare.minor().
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
