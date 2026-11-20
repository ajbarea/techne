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
- 📋 Next: CI's mutation run on this head confirms 0 survivors; then a fresh Opus reader round 2
  (elenchus), then a verify pass; Heph merges. After merge: the prefs-repo PR, klepsydra#514 pin.
- Bench red on e3fd401 was noise (no phylax change; bench passed on ead67ae and 00509fe).
- Renumbered planned checks: #257 → check 19, #259 → check 20. Follow-ups filed: #391.
- Verify: `make lint`; `uv run pytest tests/test_cleanup_check.py tests/test_cleanup_markdown.py
  tests/test_lessons.py tests/test_bug_classes.py`; `make guards`.
