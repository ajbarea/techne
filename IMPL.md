# techne — Implementation scratchpad (feat/actionlint-pins-391)

The active TODO list for whatever's in flight right now. Queued specs live in [ROADMAP.md](./ROADMAP.md).

## Shared action-pin check + actionlint (issue #391, PR #406)

- Slice (techne side of #391): `scripts/check_action_pins.sh [DIR]` checks any repo; composite action
  `.github/actions/check-action-pins` runs it for a sister; `make actionlint` in `validate` and CI;
  sisters check 17 reports a repo whose CI runs no actionlint.
- ✅ agy's first pass (adf277a).
- ✅ Opus review fixes: actionlint pinned in uv.lock (`actionlint-py==1.7.12.*`; its sdist build checks the
  release binary's sha256) instead of an unpinned `uvx`; the composite action passes its inputs through
  `env:` (no `${{ }}` in `run:`); the unreachable `$/` case arm dropped (the ref regex never matches `$/`).
- ✅ Opus round 2 fixes: the action fails on a workspace with no workflows (no checkout) and on an
  empty `directory`; `runs_zizmor`/`runs_actionlint` merged into `runs_tool`, its test parametrized over
  both linters (4 untested branches); short-SHA case. 7 hand mutants killed.
- ✅ Live: the shared script passes on ldqis, ariadne and periplus; sisters check 17 flags ldqis
  "no actionlint in CI"; `uv run actionlint` and zizmor clean on techne.
- 📋 Deferred to #391: the shared script misses quoted `uses:` refs and composite actions'
  `action.yml`, which sisters check 17 already reads (no fleet repo hits it today).
- 📋 Left for #391 (stays open): replace the inline `pin-check.yml` in the seven sisters (ldqis, ariadne,
  ajbarea.github.io, periplus, phalanx-fl, kourai-khryseai, velocity-fl) with
  `uses: ajbarea/techne/.github/actions/check-action-pins@<SHA>` once this merges, one PR each.
- ⏸ PARKED 11-23 at 6db034b; 📋 Next: CI, fresh Opus round 3 (verify of round-2 fixes), merge.
- Verify: `uv run pytest tests/test_check_action_pins.py tests/test_sisters_security_floor.py`;
  `make actionlint zizmor guards`.
