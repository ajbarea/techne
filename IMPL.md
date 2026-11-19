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
- ✅ Mutation gate: 17 survivors killed by tests (edb1aa2); survivors and failed baselines now print `::error`.
- ✅ Live check (2.1.316, haiku, ~/.claude-rit, --plugin-dir + settings with phylax@inline options): branch as
  is: echo runs, pkill -f refused by the guard; python3 stub exit 1: echo runs, pkill -f refused "python3 failed
  (exit 1)"; Bash hook timeout 5 + guard sleeping 30: echo refused "timed out; blocking because onFailure is
  "block""; guard raising: echo refused with the crash text + off switch. Server killed, no claude left.
- ✅ Round 2 (fresh Opus): 2 should-fix + 3 nits fixed in 2040d83 (warn-only crash prints a warning verdict;
  doctor fail-closed counts only refusing guards; docs name every no-python3 refusal). 2.1.294 checked live with
  `-p`: loads the hooks, refuses pkill -f, ignores onFailure (echo ran past a timed-out hook).
- ✅ Round 3 (fresh Opus): clean; 4 nits fixed (crash handler catches any parse error; docs: 75 s timeout
  caveat, AGENTS no-grep and \u wording).
- ✅ Verify pass on round-3 nits clean; deep-input regression test forced via json.loads (CI's Python parses
  100000 nested lists). CI green on ee6251e (validate 25m37s; apt slowness is techne#382). PR body updated.
- 📋 Next: Heph reviews and merges; nothing open on this branch.
- No plugin version bump: plugin.json has no version.
- Verify: `make lint`; `uv run pytest tests/test_phylax_conformance.py tests/test_git_guards.py
  tests/test_model_guard.py tests/test_email_greeting.py tests/test_command_shapes.py tests/test_hook_latency.py
  tests/test_phylax_doctor.py tests/test_secret_guard.py` under the heavy lock.
