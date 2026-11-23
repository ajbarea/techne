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
- ✅ Reader rounds 1-2, verify rounds 3-6 and mutation runs 2-8 done (history in git log);
  equivalents with reasons in mutation/equivalent.toml.
- ✅ Heph r1 (reports/cleanup-check-394-r1.md) fixed in 2e86d61 + docs commit: S1 CRLF
  `## cleanup`; S2 span_hazard refuses a link/footnote definition in the cut, Scan: a plain
  one-line definition starts no paragraph, others are hazards; rendered-HTML differential test
  (kept_html) added; S3 retry keys with any non-zero value (not in .py or workflows: N6);
  N1 no ROADMAP exit 0; N2 surrogateescape write; N3 no added final newline; N4 heading-like
  indented # only; N7 prune prints `note:` for kept lines naming the cut (dangling, slug);
  N8 check skips a registered_report ROADMAP. Tests pass locally; make lint clean.
- 📋 PARKED 11-23 (Heph: Personal 5h room). Next, in order:
  1. Mutation run (stopped part-way: 113 killed, 15 survived): `flock -o /tmp/fleet-heavy.lock
     timeout 3000 uv run --no-sync python scripts/mutation.py --changed-since d6397e3 --module
     plugins/techne/_shared/cleanup.py --workers 4`. Survivors seen: dangling mutmut_1/8/17/18/
     25/26/29/31/32/33/35, prune 87/92/96, slug 20: add cells (limit cap, anchor-only match,
     blank title) or equivalents with reasons.
  2. N5: a Windows leg for the cleanup tests (AJ's Windows stations run the claude-prefs hook).
     Local try: copy tracked files to %TEMP%\techne-win-394,
     `cmd.exe /c "uv.exe run --python 3.12 python -m pytest tests/test_cleanup_check.py
     tests/test_cleanup_markdown.py"` under the lock; skipif POSIX-only cells (mkfifo,
     symlink); then a windows-latest job in validate.yml. Delete the temp copy after.
  3. Push once, verify pass (fresh Opus reader), Heph r2 and merge. After merge: claude-prefs
     #56, then repin klepsydra#514's ci.yml techne ref to the merge SHA.
- Bench red on e3fd401 was noise (no phylax change; bench passed on ead67ae and 00509fe).
- Renumbered planned checks: #257 → check 19, #259 → check 20. Follow-ups filed: #391.
- Verify: `make lint`; `uv run pytest tests/test_cleanup_check.py tests/test_cleanup_markdown.py
  tests/test_lessons.py tests/test_bug_classes.py`; `make guards`.
