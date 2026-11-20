# techne — Implementation scratchpad

The active TODO list for whatever's in flight **right now**: current PR, open design question,
immediate next pickup. Queued specs and ordering live in [ROADMAP.md](./ROADMAP.md); landed work
moves to its dated Shipped log. Over ~50 lines means something referential crept in.

## CI best practice (branch ci/best-practice, issue #386; no PR yet)

Worktree .claude/worktrees/ci-best. Push only `git push origin HEAD:refs/heads/ci/best-practice`.
Fleet worker close-menu (klepsydra side: PR klepsydra#502). Do not merge: Heph reviews and merges.

- ✅ 0bf96b6: `make test PYTEST_ARGS="-n logical --dist worksteal ..."` in validate (17 to ~7 min), JUnit
  test summary + upload on failure, weekly mutation 16 to 32 shards (max-parallel 16, step timeout 55).
- ✅ WIP (this commit): `test_an_editable_export_keeps_the_notes_off_the_slide` compared picture blobs byte
  for byte and failed 2-3 of 12 runs under 4 workers (7 px of slide 4's figure, off by <= 3/255).
  Now: same picture counts per slide, same sizes, max per-channel drift <= RASTER_DRIFT (8).
  Playwright's own screenshot compare tolerates raster noise the same way (threshold 0.2 by default).
- 📋 NOT YET PROVEN. The first stress run skipped every case: playwright is not in the project venv,
  so run with the Makefile's TEST_WITH. Script: run under `flock -o /tmp/fleet-heavy.lock timeout 2400`:
  3 x `uv run -q $TEST_WITH --with pytest-repeat pytest -q -p no:cacheprovider -n 4 --count 12 <test>`
  must all pass; then mutation: set `_EXPORT_START = _start_with({"showNotes": True})` in
  plugins/graphe/skills/slides/scripts/slides.py, the test must FAIL (if it passes, the runtime
  `Reveal.configure` line ~1941 still hides notes: mutate that too); `git checkout` slides.py after.
- 📋 Small fix in scope: tests/test_slides_web.py's skip reason says "declared by TECHNE_NO_BROWSER"
  even when playwright is just not importable (HAVE_LIBS false); name the real cause.
- 📋 Then: `make lint`, full `make test PYTEST_ARGS=...` under the lock, open the PR (label enhancement,
  assignee ajbarea, Fixes #386, short top + results table), CI green, report Heph, update #386 status.

## Verify
- `make lint`; the stress + mutation runs above; `make test` under the heavy lock.
