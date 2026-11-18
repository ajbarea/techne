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
- 📋 **Mutation job is the one open gate.** First complete sharded run: **44224760020** on d78c73c (all 6 shards
  failed on survivors; `changed-report` merged: `command_shapes.py` 1622 mutants, 1430 killed, 25 timeout, **167 survived**,
  89.7%; `git_checks.py` 175, **4 survived**; `git_guards.py` 105, 0). Survivors by function: `Scan.command` 35,
  `on_clock` 26, `Lexer.tokens` 14, `Scan.walk` 12, `_command_option` 10, `full_match` 8, `peel` 7, `shell_code` 7, `Scan.text` 7,
  `arithmetic_fors` 5, `reads_to_end` 5, `Scan.code` 5, `command_start` 5, `_limits` 4, `_reads_clock` 4, `Lexer.braces` 4,
  `loops` 3, `Lexer.substitution` 2, `strip_heredocs` 2, `_long` 2, `is_arith` 2, `loop_extent` 1, `Lexer.dquote` 1.
  Full list with diffs and equivalent-keys: `~/.local/state/phylax-369/survivors-run-44224760020.json` (tuples
  [module, function, old line, new line, key]) and the `changed-report` log of that run; artifacts `mutation-changed-1..6`.
- ✅ Done toward it: earlier 69 survivors (dead detach code deleted, units tested); `tests/test_command_shapes_golden.py`
  (about 400 golden cases for the lexer pieces and pure helpers), registered in pyproject and `HOOK_TESTS`; `_reads_clock`
  fix (a bare `SECONDS` counts only inside `(( ))`).
- 📋 Next: the big groups are the `Scan` methods (`command`, `walk`, `text`, `code`), which only `check()` reaches: add
  unit tests calling `Scan().command/walk/text/code` on small inputs and asserting `scan.loops` and `scan.full`; then
  `on_clock` goldens for the survivors' shapes, `Lexer.tokens` (comment skipping, `depth`, fd redirections), `_command_option`.
  Kill each with a test that asserts real behaviour or add a truly equivalent one to `mutation/equivalent.toml` (key from the
  JSON, one-line reason). Known equivalent: `if j < 0` / `j <= 0` / `j < 1` after `text.find(quote, j + 1)` in `git_checks.is_arith`.
  No padding. At most 3 CI rounds; the sharded run takes about 30 to 60 min: use a timed background wait.
- Gotchas: `/code-review` leaves the worktree on a local `pr371` branch (`git status -sb`, push by refspec); a hand mutant
  restored in the same second keeps its `.pyc` (delete `__pycache__`, `PYTHONDONTWRITEBYTECODE=1`); the survivor emulator
  `scratchpad/emulate2.py` is slow and can leave a mutated line on kill (check `git diff` after).
- Verify: `make lint`; `uv run pytest tests/test_command_shapes.py tests/test_command_shapes_golden.py tests/test_git_guards.py`
  under `ulimit -d 2097152`; seeds `SHAPE_SEED=N uv run pytest tests/test_command_shapes.py -k generated`.
- Athena merges; report to her when the mutation job is green.
