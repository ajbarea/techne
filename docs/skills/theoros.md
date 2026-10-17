---
description: Drive an interactive REPL in a named tmux session while you watch read-only with tmux attach -r.
---

# `techne:theoros`

Start an observed live dev session: Claude drives the repo's interactive REPL in a named tmux session; you spectate read-only via `tmux attach -r`.

Part of [techne](../plugins/techne.md): `/plugin install techne@techne`, then `/techne:setup`.

## When to use

- "Let's do a live smoke." / "Run a theoros session." / "I want to spectate while you drive the CLI."
- Verifying a service end-to-end while watching the REPL output in real time.
- Debugging an interactive workflow where you want eyes on the session without touching the keyboard.

## Usage

Invoke by name in Claude Code:

```
/techne:theoros
```

The skill runs `theoros.sh up`, which starts the session and writes a state file, or refuses and prints the attach command when a session of that name is already running. It then prints the attach command and begins driving. The human attaches read-only:

```
tmux attach -t <session_name> -r
```

When done, the skill runs its bundled `theoros.sh down`, which kills the session and removes the state file.

## Prerequisites

The `## theoros` section of `.claude/skill-context.md` must supply at minimum `repl_command` and `session_name`. Without it the skill aborts and explains what to add.

Optional fields add a split log pane (`ops_command`) and checks that must pass before the session starts (`prerequisites`). The lifecycle script (`up`, `down`, `status`) ships with the skill, so the repo needs no script or Makefile target of its own.

`status` prints the state file, which holds the `driver_pane` and `ops_pane` ids. Claude addresses panes by their `%id`, never by `session:0.0`, because tmux's `base-index` setting changes that numbering. The script exits 2 on an unknown subcommand. The session keeps 50000 lines of scrollback and the ops pane takes 40% of the window; the scrollback ends with the session unless you opt in to `tmux pipe-pane`.

A repo's own `make theoros`, if it has one, is for a human starting a session outside Claude Code. The skill does not call it, because such a target may launch its own autonomous driver.

See [Conventions](../conventions.md#section-reference) for the `## theoros` keys.

## See also

- [`techne:audit`](audit.md): non-interactive local toolchain validation.
- [`techne:ci-audit`](ci-audit.md): audit cloud CI runs after a theoros session surfaces failures.
- [Conventions](../conventions.md): the `## theoros` section.

## Full instructions

[`SKILL.md` on GitHub](https://github.com/ajbarea/techne/blob/main/plugins/techne/skills/theoros/SKILL.md) holds the full instructions Claude follows for this skill.
