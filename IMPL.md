# techne — Implementation scratchpad

The active TODO list for whatever's in flight **right now**: current PR, open design question,
immediate next pickup. Queued specs and ordering live in [ROADMAP.md](./ROADMAP.md); landed work
moves to its dated Shipped log. Over ~50 lines means something referential crept in.

## phylax fails closed (branch fix/phylax-fail-closed-378, issue #378, PR #379)

- Slice: `"onFailure": "block"` on the PreToolUse hooks that can refuse (Bash, run_command, Agent|Task
  model guard, email greeting). Left out: `budget.py agent` (only rewrites a model) and non-PreToolUse events.
- ✅ Round 1 (code-review medium + Opus reader + Heph's review) fixed:
  - `hooks/no_python3.sh`, sourced when python3 is missing or exits other than 0/2 (`$phylax_rc`): checks only
    the `command`/`CommandLine` JSON values, git/gh as words, blocking options only; one decision point.
  - Model and greeting hooks map a failing python3 to a named refusal; scripts pin their folder on sys.path.
  - Warning-only failures emit a warning verdict (`git_options.unchecked`); crash handler counts SHAPES only
    before the shape check; `off_switch(keys)` names only options that could refuse.
  - 50 s shared budget (`git_options.time_left`) for git runs and secret scans; doctor `fail-closed` line.
  - `make shellcheck` now covers `plugins/*/hooks/*.sh`. Mutation checks: each new guard turns a test red.
- ✅ Round-1 suite + `make shellcheck`: green after two test fixes (b7522e9 budget test anchored on now, which
  broke CI's mutation baseline; c524e7c doctor tests' option list lacked email_greeting, now pinned to
  plugin.json). mutation.py prints `::error` per failed baseline test (CI report finding).
- 📋 Next: the live check (settings + plugin copies + python3 stub built in the session scratchpad) (tmux -L live378, haiku, CLAUDE_CONFIG_DIR=~/.claude-rit, a --settings file
  with `enabledPlugins: {"phylax@techne": false}` and `pluginConfigs` options block_pkill_full + block_secrets
  under `phylax@inline` and `phylax`; confirm which key reaches the hook by logging `env | grep CLAUDE_PLUGIN_OPTION`
  from a copy's hook). Cases: branch as is (`echo` runs, `pkill -f zz` refused); PATH with a python3 stub exiting
  1 (`echo` runs, `pkill -f zz` refused naming "python3 failed (exit 1)"); a plugin copy whose Bash hook timeout
  is 5 and git_guards.main sleeps 30 (`echo` refused: the only case that tests onFailure itself); a copy whose
  main raises (refused with the crash text). Kill the server after. Then push, round 2 fresh Opus reader on
  `git diff origin/main...HEAD`, CI, update the PR body (no-python behavior, budget, doctor line), `fleet send`
  Heph, `fleet done`. Do not merge.
- Not verified: whether Claude Code before 2.1.295 rejects the unknown `onFailure` key (only 2.1.300+ here).
- No plugin version bump: plugin.json has no version.
- Verify: `make lint`; `uv run pytest tests/test_phylax_conformance.py tests/test_git_guards.py
  tests/test_model_guard.py tests/test_email_greeting.py tests/test_command_shapes.py tests/test_hook_latency.py
  tests/test_phylax_doctor.py tests/test_secret_guard.py` under the heavy lock.
