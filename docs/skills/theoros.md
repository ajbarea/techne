# `techne:theoros`

Start an observed live dev session: Claude drives the repo's interactive REPL in a named tmux session; you spectate read-only via `tmux attach -r`.

## When to use

- "Let's do a live smoke." / "Run a theoros session." / "I want to spectate while you drive the CLI."
- Verifying a service end-to-end while watching the REPL output in real time.
- Debugging an interactive workflow where you want eyes on the session without touching the keyboard.

## Usage

Invoke by name in Claude Code:

```
/techne:theoros
```

The skill checks for an existing tmux session, starts one if absent, prints the attach command, and begins driving. The human attaches read-only:

```
tmux attach -t <session_name> -r
```

When done, the session tears down via `make theoros-down` (tier 2) or `tmux kill-session` (tier 1).

## Prerequisites

The `## theoros` section of `.claude/skill-context.md` must supply at minimum `repl_command` and `session_name`. Without it the skill aborts and explains what to add.

Two tiers:
- **Tier 1**: two-field YAML block in skill-context, no other files needed.
- **Tier 2**: `scripts/theoros.sh` + Makefile targets (`theoros`, `theoros-down`, `theoros-status`) for prerequisite gating and extended lifecycle.

The skill auto-detects tier 2 by checking for a `theoros:` target in the `Makefile`.

See [Conventions](../conventions.md) for the scaffolding walkthrough.

## See also

- [`techne:audit`](audit.md): non-interactive local toolchain validation.
- [`techne:ci-audit`](ci-audit.md): audit cloud CI runs after a theoros session surfaces failures.
- [Conventions](../conventions.md): `## theoros` section reference and tier scaffolding.
