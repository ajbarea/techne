# techne — Implementation scratchpad

The active TODO list for whatever's in flight **right now**: current PR, open design question,
immediate next pickup. Queued specs and ordering live in [ROADMAP.md](./ROADMAP.md); landed work
moves to its dated Shipped log. Over ~50 lines means something referential crept in.

## graphe:vids idle loop (branch docs/vids-animate-image-loop, issue #380, PR not yet opened)

- Slice: docs only. New `plugins/graphe/skills/vids/references/idle-loop.md` (899/900 words), Animate-tab
  steps 31-38 in `references/playwright.md`, pointer + trigger in `SKILL.md` (825/900) and `docs/skills/vids.md`.
- ✅ `make lint` clean. `make test` failed once on the private-repo name guard (an IMPL line named a private repo; reworded and the commit amended), then was stopped by an account move before finishing. No unit failures seen.
- 📋 Next: `flock -o /tmp/fleet-heavy.lock timeout 1500 make test`; then `gh pr create --label documentation
  --assignee ajbarea` closing #380, assign #380 to ajbarea. PR top: why (graphe:vids covers animating a still
  into a seamless idle loop, from six scored takes), table of the three files, status docs only + tests pass;
  details: numbers from the klepsydra#388 spike, scorer self-test (synthetic 1.85 % bob read 1.88 %, 3.00 s,
  SSIM 0.97), scorer script left out (needs numpy in sandboxed, type-checked CI). Heph runs the Opus review and merges.
- Source data: the private heph-idle-vids review folder (README, scores.json, tools).

## phylax command-shape guards (branch feat/phylax-369-command-shapes, issue #369, PR #371)

- Slice: `block_background_loops` and `block_pkill_full` (PreToolUse), `plugins/phylax/hooks/command_shapes.py`
  wired from `git_guards.py` behind `--shapes`. Guard 3 (`gh pr edit`) dropped: fixed upstream, still
  broken on apt's gh 2.45 (#373). Deferred: one lexer for the git guards (#372).
- ✅ Review: 7 rounds plus a final verify pass, all clean.
- ✅ CI on eac632f: validate, CodSpeed, bench and mutation (run 44242229286) green. Mutation merged score:
  `command_shapes.py` 1623 mutants, 0 survived, 38 equivalent; `git_checks.py` 175, 0 survived, 2 equivalent;
  `git_guards.py` 105, 0 survived.
- ✅ Mutation work: golden tests for the lexer pieces and helpers (`tests/test_command_shapes_golden.py`), 40 entries in
  `mutation/equivalent.toml` (each with a one-line reason; keys hash the whole function source, so editing a
  function makes its key stale), a lexer fix (`2>x` lost the first character of its target), and `scripts/mutation.py`
  now treats a mutant that exhausts the data limit as a resource stop, judged like a timeout.
- Status: ready for the final review and merge (Athena).
- Gotchas: `/code-review` leaves the worktree on a local `pr371` branch (`git status -sb`, push by refspec).
- Verify: `make lint`; `uv run pytest tests/test_command_shapes.py tests/test_command_shapes_golden.py tests/test_git_guards.py tests/test_mutation.py`
  under `ulimit -d 2097152`.
