# techne — Implementation scratchpad

The active TODO list for whatever's in flight **right now**: current PR, open design question,
immediate next pickup. Queued specs and ordering live in [ROADMAP.md](./ROADMAP.md); landed work
moves to its dated Shipped log. Over ~50 lines means something referential crept in.

## CI best practice (branch ci/best-practice, issue #386; PR next)

Worktree .claude/worktrees/ci-best. Push only `git push origin HEAD:refs/heads/ci/best-practice`.
Fleet worker close-menu (klepsydra side: PR klepsydra#502, green). Do not merge: Heph reviews and merges.

- ✅ 0bf96b6: `make test PYTEST_ARGS="-n logical --dist worksteal ..."` in validate (17 to ~7 min), JUnit
  test summary + upload on failure, weekly mutation 16 to 32 shards (max-parallel 16, step timeout 55).
- ✅ 1a79209: the notes-off export test compares pixels within 8/255 (same counts and sizes), not bytes.
  Stress 36/36 (3 x 12 repeats, 4 workers). Mutation `_start_with({"showNotes": True})` is equivalent
  (both exports take the override); dropping the override (`_start_with({})` + `_FORCE_NOW` no-op) is
  killed: slide 1 drifts 256 (size change).
- ✅ aeae7c7: a skipped web case names its real cause.
- ✅ Review round 1 (fresh Opus): Should-fix: under xdist a worker whose Chromium probe failed skipped
  its share of web cases unseen. Now a case skips only on TECHNE_NO_BROWSER or missing libraries.
  Nits: Makefile comment says -n logical; mutation.yml comments (Pro's 40 jobs, step timeout reason).
- ✅ `make lint` clean; full `make test` (4 workers) green, 3 expected skips.

## Next
1. ✅ Verified: libraries present, Chromium unlaunchable (PLAYWRIGHT_BROWSERS_PATH=/nonexistent): the case fails with the install hint.
2. 📋 Push, open the PR (label enhancement, assignee ajbarea, Fixes #386, short top + results table),
   fresh Opus round 2 on the fix, CI green, report Heph.
