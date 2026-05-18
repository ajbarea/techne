# `techne:theoros`

Starts an observed live dev session: Claude drives the REPL in a named `tmux` session; you spectate read-only via `tmux attach -r`.

## When to use

- You want to watch Claude work without driving the terminal yourself.
- Pairing with a remote teammate who wants visibility into the live session.
- Recording or screen-sharing a session for later review.

## How it works

1. Skill spawns a named `tmux` session (e.g. `theoros-<ts>`).
2. Claude runs commands in that session.
3. You (or anyone with shell access) attach read-only: `tmux attach -r -t theoros-<ts>`.
4. Output streams to all observers in real time.

## Tiers

| Tier | What you need |
|---|---|
| **Tier 1 (drop-in)** | Two-field YAML block in `.claude/skill-context.md`. Skill handles the rest. |
| **Tier 2 (mechanical)** | Optional `scripts/theoros.sh` + Makefile target + extended skill context for repos that want more control. |

## Reads

- `<repo>/.claude/skill-context.md`
- `<repo>/scripts/theoros.sh` (tier 2 only)
- `<repo>/Makefile` (tier 2 only)
