# techne — Implementation scratchpad

The active TODO list for whatever's in flight **right now**: current PR, open design question,
immediate next pickup. Queued specs and ordering live in [ROADMAP.md](./ROADMAP.md); landed work
moves to its dated Shipped log. Over ~50 lines means something referential crept in.

## phylax fails closed (branch fix/phylax-fail-closed-378, issue #378)

- Slice: `"onFailure": "block"` on the PreToolUse hooks that can refuse (Bash, run_command, Agent|Task
  model guard, email greeting). Left out: the `budget.py agent` hook (it only rewrites a model) and every
  non-PreToolUse event (nothing to guard; no effect on Stop).
- ✅ hooks.json edited; `failed()` in git_options.py and the crash handler in git_guards.py exit 0, not 1, when
  only the warning guard is on (onFailure blocks on exit 1); tests in test_git_guards.py follow.
- ✅ Conformance tests in tests/test_phylax_conformance.py (all plugins' PreToolUse; options-off exits 0).
- ✅ Docs: docs/configuration.md Guards section, plugins/phylax/AGENTS.md "Failure behavior".
- ✅ Athena's addition: refusal text names guard, error, option, /config and /phylax:setup (`hook_failure.py`,
  `git_options.off_switch`, shell fallbacks for a missing python3); latency measured on klepsydra and techne.
- ✅ Live check in a real session (haiku, 2.1.316): python3 shim exiting 1 refused `echo`; without it `echo` ran and `pkill -f` was refused.
- ✅ PR #379 open (bug, ajbarea); CI green on 5aa4966 (the mutation gate first failed on the untested off-switch text; a test pins it).
- 📋 Next: one fresh Opus review round of `git diff origin/main...HEAD` (never run: stopped at the 5-hour limit) -- check any exit but 0 or 2
  reachable with a guard off, the `*\\u*` case pattern in the python3-missing fallback, run_command payloads; fix findings; then
  `fleet send` Heph and `fleet done`. Do not merge.
- No plugin version bump: plugin.json has no version, and marketplace.json moves only for a new plugin.
- Gotchas: `make lint` needs `uv sync` first in a fresh worktree; with python3 missing, a Bash call naming git or gh is
  refused while a git guard is on; other Bash calls run.
- Verify: `make lint`; `uv run pytest tests/test_phylax_conformance.py tests/test_git_guards.py tests/test_model_guard.py
  tests/test_email_greeting.py tests/test_command_shapes.py` under the heavy lock.
