# techne — Implementation scratchpad

The active TODO list for whatever's in flight **right now**: current PR, open design question,
immediate next pickup. Queued specs and ordering live in [ROADMAP.md](./ROADMAP.md); landed work
moves to its dated Shipped log. Over ~50 lines means something referential crept in.

## phylax command-shape guards (branch feat/phylax-369-command-shapes, issue #369, PR #371)

- Slice: `block_background_loops` and `block_pkill_full` (PreToolUse), `plugins/phylax/hooks/command_shapes.py`
  wired from `git_guards.py` behind `--shapes`. Guard 3 (`gh pr edit`) dropped: fixed upstream, still
  broken on apt's gh 2.45 (#373). Deferred: one lexer for the git guards (#372).
- ✅ Review: 7 rounds plus a final verify pass, all clean (class `shell-semantics-mismatch` recurred;
  structural fixes are in the code: fail-closed on unclosed constructs, any `&` in a text detaches its loops).
- ✅ CI: validate, CodSpeed, bench green. #375 (sharded PR mutation job, merged 82a4a9f) now runs the
  `changed` job as 6 shards; read the `changed-report` job summary for the merged score.
- 📋 **Mutation job is the one open gate.** Run 44210327831 (before sharding, cancelled at the 60-min cap)
  left 241 survivors in `command_shapes.py` and 6 in `git_checks.py`: by function `on_clock` 35, `shell_code` 22,
  `Lexer.substitution` 22, `Lexer.expansions` 16, `Lexer.tokens` 15, `command_start` 13, `peel` 11, `full_match` 11,
  `_signal` 10, `_command_option` 10, `Lexer.braces` 10, `reads_to_end` 9, `arithmetic_fors` 8, `_forks` 8, `loops` 7,
  `Lexer.dquote` 7, `_reads_clock` 6, `_is_test` 6, `_limits` 5, `loop_extent` 4, `split_redirects` 3, `_long` 3,
  `is_arith` 4, `strip_heredocs` 2. Full list: that run's step summary, artifact `mutation-changed`.
- ✅ Done toward it: the earlier 69 survivors (dead detach code deleted, units tested); `tests/test_command_shapes_golden.py`
  (about 400 golden cases for the lexer pieces, `commands`, `command_start`, `loops`, `loop_extent`, `reads_to_end`,
  `on_clock`, `_reads_clock`, `peel`, `shell_code`, `full_match`, `_signal`, `_limits`, `_long`, `_forks`, `split_redirects`,
  `arithmetic_fors`), registered in pyproject and `HOOK_TESTS`; `_reads_clock` fix (a bare `SECONDS` counts only inside `(( ))`).
- 📋 Next: push, then read the sharded run's `changed-report` table and survivor list; kill each survivor with a test
  that asserts real behaviour, or add it to `mutation/equivalent.toml` (key = hash printed in the CI survivor list, one-line
  reason). Known equivalent: `if j < 0` / `j <= 0` / `j < 1` after `text.find(quote, j + 1)` in `git_checks.is_arith` (find
  never returns 0 there). No padding. Keep to 1 to 3 CI rounds; timed background wait each run (shards take about 30 to 60 min).
- Gotchas: `/code-review` leaves the worktree on a local `pr371` branch (`git status -sb`, push by refspec); a hand mutant
  restored in the same second keeps its `.pyc` (delete `__pycache__`, `PYTHONDONTWRITEBYTECODE=1`); the survivor emulator
  `scratchpad/emulate2.py` is slow and can leave a mutated line on kill (check `git diff` after).
- Verify: `make lint`; `uv run pytest tests/test_command_shapes.py tests/test_command_shapes_golden.py tests/test_git_guards.py`
  under `ulimit -d 2097152`; seeds `SHAPE_SEED=N uv run pytest tests/test_command_shapes.py -k generated`.
- Athena merges; report to her when the mutation job is green.
