---
name: theoros
description: Run an observed live dev session: Claude drives an interactive REPL in a named tmux session while the human spectates read-only via `tmux attach -r`. Use when the user wants to play through, debug, or explore a service's REPL together. Trigger phrases include "let's do a live smoke", "run a theoros session", "I want to spectate while you drive the CLI", "start an observed dev run". Reads per-repo facts from the `## theoros` section of `.claude/skill-context.md`. Not for launching an app just to confirm a change works when nobody is watching.
disable-model-invocation: false
allowed-tools: Bash Read Grep
---

# Theoros

θεωρός — the "state-appointed spectator who watches a divine spectacle on behalf of the polis and reports back." Etymological ancestor of *theater* and *theory*. In this skill, **you (Claude) are the driver; the human is the theoros.**

The pattern: a long-running tmux session where you exercise the repo's interactive REPL via `tmux send-keys`, and the human attaches read-only via `tmux attach -r` to spectate. The human's eyes/ears judge aesthetic concerns (does it feel right, does it sound right). Your queries against logs and panes judge operational concerns (did the request fire, did the log line emit). Never confuse the two.

## Repo context

```!
cat .claude/skill-context.md 2>/dev/null || echo "(no .claude/skill-context.md found — this skill needs one; ask the user to add a \`## theoros\` section with a fenced YAML block containing at minimum \`repl_command\` and \`session_name\`. See the scaffolding section below.)"
```

If the injected content above does not contain a `## theoros` section, abort and direct the user to the **Scaffolding theoros into a new repo** section below.

## Required YAML fields

From the fenced ```yaml block inside `## theoros`:

- `repl_command` (required) — the shell command that launches the interactive REPL
- `session_name` (required) — the tmux session name, conventionally `<repo-slug>-theoros`
- `ops_command` (optional) — bottom-pane command for the split layout (e.g., `docker compose logs -f --tail 0 svc1 svc2 svc3`)
- `prerequisites` (optional) — list of `{command, message}` pairs to run before `up`; first failure aborts with the matching message

A markdown table outside the YAML block can specialise the aesthetic vs operational split for the repo.

## Lifecycle

Run everything from the target repo's root. The bundled script reads the `## theoros` YAML,
runs the prerequisites, lays out the panes, and writes a state file:

```bash
bash ${CLAUDE_SKILL_DIR}/scripts/theoros.sh up       # start; refuses if the session exists
bash ${CLAUDE_SKILL_DIR}/scripts/theoros.sh status   # the state file as JSON, or "not running"
bash ${CLAUDE_SKILL_DIR}/scripts/theoros.sh down     # kill the session, remove the state file
```

1. **Start it** with `up`. If the session already exists, the script refuses and prints the
   attach command; tell the user, and do not clobber it.
2. **Print the attach command** for the user: `tmux attach -t <session_name> -r`.
3. **Drive it** per the rules below, and `down` when the session is done.

**Do not run the repo's own `make theoros` from a conversation.** A repo may wire that target
to its own launcher, and one such launcher starts a second, autonomous Claude in a pane with
permissions bypassed. You are already the driver. A repo's `make theoros` is for a human
starting a session outside Claude Code.

With no bash or no script available, the inline equivalent is
`tmux new-session -d -s <session_name> "<repl_command>"`, plus
`tmux split-window -t <session_name>:0 -v -l 40% "<ops_command>"` when there is an ops command.

## Driving the REPL

Send keys to the driver pane (always pane index `0.0`):

```bash
tmux send-keys -t <session_name>:0.0 '<text>' Enter
```

Enter is a **separate argument**, never embedded inside the quoted string.

Read driver pane output:

```bash
tmux capture-pane -t <session_name>:0.0 -p -S -<n>
```

`-p` prints to stdout; `-S -<n>` reads the last n lines of scrollback (default scrollback is 2000 lines).

Read ops pane output (split layout only):

```bash
tmux capture-pane -t <session_name>:0.1 -p -S -<n>
```

Or query the underlying source directly — for `docker compose logs -f`, that means `docker compose logs <svc> | grep <pattern>`. The direct source query is the source of truth; the pane is informational for the human.

## Discipline rules

These are load-bearing. Read them before every theoros session you drive.

1. **Drive via `send-keys`.** Never paste-and-go via the human's terminal. Never ask "type this for me."
2. **Capture pane output yourself.** Never ask "what does the screen say?" — `tmux capture-pane` is your job.
3. **Grep logs yourself.** Either via `capture-pane` against the ops pane, or directly against the source (`docker compose logs <svc> | grep ...`, `kubectl logs ...`, `tail -F ...`). Don't ask the human to paste a log excerpt.
4. **Handoff is only for aesthetic judgment.** Defined by the table in skill-context.md when present, by the default split below when absent:
   - **Aesthetic (human):** does it sound right, feel right, look right, hang together coherently
   - **Operational (you):** did the request fire, did the log line emit, what was the value of X
5. **If the human pastes a transcript, you forgot rules 1–4.** Acknowledge the slip explicitly and resume from where you were, this time driving the captures yourself.

The ops pane is informational for the human's confidence. **Your source of truth is your own queries**, not what is visible on the screen right now.

## Scaffolding theoros into a new repo

Add to `.claude/skill-context.md`:

````markdown
## theoros

```yaml
repl_command: <shell command that launches your interactive REPL>
session_name: <repo-slug>-theoros
```
````

That is the whole minimum. Optional additions:

- `ops_command: <bottom-pane command>` for the split layout, e.g. a multi-service log tail.
- `prerequisites:`, a list of checks run before `up`; the first failure aborts with its message:
  ```yaml
  prerequisites:
    - command: docker info
      message: "Start Docker first."
  ```
- A markdown table beneath the YAML block listing the aesthetic and operational concerns
  specific to the repo.

No repo-side script or Makefile target is needed: the lifecycle script ships with this skill.

## Teardown

`bash ${CLAUDE_SKILL_DIR}/scripts/theoros.sh down` kills the session and removes
`/tmp/<session_name>.state`. Tmux scrollback dies with the session; logs survive only if
`tmux pipe-pane` was opted into.
