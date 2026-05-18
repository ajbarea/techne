# `techne:audit`

Runs your repo's `make` targets in dependency order and reconciles terminal output against `logs/dev-*.log` archives.

## When to use

- Pre-PR check: validate the toolchain is clean before pushing.
- "Is the build clean?" / "Am I ready to push?"
- Verify make targets actually emit what their `logs/dev-<ts>-<cmd>.log` archives claim.

## What it does

- Walks the repo's `Makefile` dependency graph (`setup` → `lint` → `test` → end-to-end).
- Runs each target and captures terminal output.
- Diffs the live terminal output against the most recent `logs/dev-*-<target>.log` archive.
- Surfaces any drift: silent failures, missing log lines, or commands that fall through dependencies.

Two modes:

| Mode | Use when |
|---|---|
| **full audit** | Pre-push or when reconciling stale logs. |
| **fast variant** | Quick lint+test sanity check. |

## Reads

- `<repo>/Makefile`
- `<repo>/logs/dev-*.log`
- `<repo>/.claude/skill-context.md` (optional repo-local overrides)
