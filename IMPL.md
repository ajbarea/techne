# techne — Implementation scratchpad

The work in flight right now: current branch, slice, what is done, what is next, how to verify.
Forward plans live in [ROADMAP.md](./ROADMAP.md); finished work lives in git and GitHub. The
cleanup check holds this file to 50 lines.

## Cleanup check (branch feat/cleanup-check-390, issue #390, PR #394)

- Slice: `plugins/techne/_shared/cleanup.py` + sisters check 18. Parts: roadmap (done-log,
  300 lines), impl (50), agents (200 lines / 25,000 bytes), transient (owner + expires/reviewed),
  rules (a `### slug:` entry dated within 90 days), flaky (retry markers need `quarantine: until`
  within 30 days). `done-log` and `prune` (refuses untracked/dirty/linked ROADMAP, `prune: off`,
  config errors, a `registered_report` sister from any worktree or clone, an unreadable roster).
  `--no-dates` = the PR gate (`make guards`, `.github/workflows/cleanup.yml`); `cleanup-weekly.yml`
  runs the dated half. klepsydra#514 imports `transient_status`/`Transient.expired`/`done_sections`.
- ✅ Reader round 1 (1 Blocking + 7 Should-fix) fixed in ead67ae; tests in 00509fe.
- ✅ Mutation round 2 (66dda39): CI on it left 74 survivors. Round 3 (c250332 + equivalents):
  a test cell per killable survivor, four reads simplified (origin by re.split, BREAK takes a
  kept line ending, BOM by removeprefix, quarantine per line); local run on the head: 1669
  mutants, 1629 killed, 4 timeouts (detected), 36 survivors each with a reason in
  mutation/equivalent.toml (POSIX-only getattr/newline defaults, equal codecs, `--` pathspecs).
- ✅ Reader round 2 (3 Should-fix) fixed in 3f7ea0f: roster match through techne_config.matches
  + git_env.github_slug, names lowercased; Scan.open_fence → span_hazard refuses; without()
  merges back-to-back cuts, skips setext underlines, and puts a blank before a setext title;
  property test: CommonMark headings outside the cut survive (40k docs, CRLF too, 0 bad).
- ✅ Verify round 3 (3 Should-fix: a fence in a list item, an HTML block above the cut, odd
  line breaks) fixed in 47bb5f7: Scan marks hazard regions (HTML/quote blocks to their end, a
  doubtful fence makes what follows unsure), odd breaks refuse, a break under text is never
  popped; 48k-doc sweep: 0 section mismatches, 0 heading losses. Mutation run 6: 1839 mutants,
  1784 killed, 4 timeouts, 45 equivalents with reasons, 6 killed by tests added after it.
- ✅ Verify round 4 (a fence inside a quote or HTML-looking region) fixed in 8cea436; mutation
  run 7 on it: 1843 mutants, 1794 killed, 45 equivalents, 4 timeouts, 0 left.
- ✅ Verify round 5 (an HTML opener inside a quote region) fixed in 4121688; the reviewer's block
  oracle: 0 bad over 6 seeds; mutation run 8: 1849 mutants, 1800 killed, 45 equivalents, 0 left.
- ✅ Verify round 6 on 5f9d398: clean (no next member of the block-region class).
- 📋 PARKED 11-20 17:10 (Personal week at 3%). Next, on relaunch: Heph's independent review r1,
  ~/.local/state/fleet-orchestrator/reports/cleanup-check-394-r1.md: SF1 CRLF skill-context
  drops `## cleanup` (accept \r\n, cleanup.py:216); SF2 prune deletes link reference
  definitions in the cut (keep or move them; extend the differential test to rendered output);
  SF3 flaky check misses `retries: process.env.CI ? 2 : 0`, vitest `retry:`, JSON "retries": 2.
  Nits N1-N8 there (no-ROADMAP exit 0, surrogateescape write, final newline, narrow ` +#`,
  POSIX-only equivalents: Windows leg or say so, github-script retries, harvest grep, check 18
  on registered_report). Then local mutation run, push once, verify; Heph r2 and merge.
  After merge: the prefs-repo PR, then repin klepsydra#514's ci.yml to the merge SHA.
- Bench red on e3fd401 was noise (no phylax change; bench passed on ead67ae and 00509fe).
- Renumbered planned checks: #257 → check 19, #259 → check 20. Follow-ups filed: #391.
- Verify: `make lint`; `uv run pytest tests/test_cleanup_check.py tests/test_cleanup_markdown.py
  tests/test_lessons.py tests/test_bug_classes.py`; `make guards`.
