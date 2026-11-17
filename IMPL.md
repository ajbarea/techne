# techne — Implementation scratchpad

The active TODO list for whatever's in flight **right now**: current PR, open design question,
immediate next pickup. Queued specs and ordering live in [ROADMAP.md](./ROADMAP.md); landed work
moves to its dated Shipped log. Over ~50 lines means something referential crept in.

## phylax command-shape guards (branch feat/phylax-369-command-shapes, issue #369, PR #371)

- Slice: `block_background_loops` and `block_pkill_full`, two PreToolUse options that refuse an
  untimed background `while`/`until` loop and `pkill -f` / `pgrep -f`, naming the form that works.
  Guard 3 (`gh pr edit`) dropped: it fails only on gh older than 2.82.1 (2.45 fails, 2.104 works,
  measured on PR #371); the decision is #373. Deferred: one lexer for the git guards is #372.
- ✅ `plugins/phylax/hooks/command_shapes.py` (bash-aware lexer, wired from `git_guards.py`, gated by
  `--shapes` in hooks.json so options-off costs nothing: triage 1.04x of main, was 1.90x), the
  `unwrap_wrappers` and `strip_heredocs` fixes in `git_checks.py` (shared with the git guards),
  manifest, doctor, docs, AGENTS.md.
- ✅ Tests: `tests/test_command_shapes.py` (differential against real bash: hand cases plus 250
  generated per seed, 20 seeds clean; known gaps pinned), `tests/test_phylax_conformance.py`
  (every docs-table guard fires through hooks.json), doctor, latency, bench cases.
- ✅ Live check in a real Claude Code session (tmux, `--plugin-dir`): both guards refused,
  the `timeout` form ran. Live sessions must be ended with /exit or a PID kill, not `tmux kill-session`.
- ✅ Review: rounds 1 to 3 fixed (class `shell-semantics-mismatch` recurred; structural fix: fail
  closed on unclosed constructs, `strip_heredocs` frames, lexer comments, wider generator).
  Round 4 (fresh `/code-review medium` + fresh Opus reader) on a871cc2 in progress.
- 📋 Next: fix round 4 findings; a verify pass on the last fixes; CI mutation job on the final
  head (survivors need tests); then report. Athena verifies and merges; the author does not.
- Verify: `make lint`; `uv run pytest tests/test_command_shapes.py tests/test_phylax_conformance.py
  tests/test_git_guards.py`; seeds: `SHAPE_SEED=N uv run pytest tests/test_command_shapes.py -k generated`;
  full `make test` under the heavy lock (1 failure fixed earlier: the manifest option test).
