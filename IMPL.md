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
- ✅ Mutation round 2 committed as 66dda39 (simplified `Scan`, whole-message tests, walk
  fallback, origin forms, `without()` edges); pushed with this IMPL for the relaunch, so CI's
  mutation run on it is the first data (the local run was stopped for the relaunch).
- 📋 Next, in order:
  1. Read CI's mutation result on HEAD, and run it locally before any further push (Heph's
     rule): `flock -o /tmp/fleet-heavy.lock timeout 3000 uv run python scripts/mutation.py
     --changed-since origin/main --module plugins/techne/_shared/cleanup.py --workers 4 --out
     /tmp/mut.json`. CI's 00509fe survivors (226, before 66dda39) are in
     ~/.local/state/fleet-orchestrator/reports/cleanup-ratchet/techne-ci-survivors-00509fe.json.
     Kill survivors with tests; a true equivalent goes in mutation/equivalent.toml with a reason
     per mutant (likely: O_NONBLOCK/O_BINARY getattr defaults, decode "utf-8", check=False→None,
     newline="" on POSIX, Config.prune_off "" vs None, normal_title `\s+`).
  2. Fresh Opus reader round 2 (elenchus), then a verify pass; Heph merges.
- Bench red on e3fd401 was noise (no phylax change; bench passed on ead67ae and 00509fe).
- Renumbered planned checks: #257 → check 19, #259 → check 20. Follow-ups filed: #391.
- Verify: `make lint`; `uv run pytest tests/test_cleanup_check.py tests/test_cleanup_markdown.py
  tests/test_lessons.py tests/test_bug_classes.py`; `make guards`.
