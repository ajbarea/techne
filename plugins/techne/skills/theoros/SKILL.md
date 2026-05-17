---
name: theoros
description: Run an observed live dev session — Claude drives an interactive REPL in a named tmux session, the human spectates read-only via `tmux attach -r`. Use when the user wants to play through, debug, or explore a service's REPL together. Trigger phrases include "let's do a live smoke", "run a theoros session", "I want to spectate while you drive the CLI", "start an observed dev run". Reads per-repo facts from the `## theoros` section of `.claude/skill-context.md`.
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

When the user asks you to start a theoros session:

1. **Check for an existing session:**
   ```bash
   tmux has-session -t <session_name> 2>/dev/null
   ```
   If a session already exists, tell the user how to attach (`tmux attach -t <session_name> -r`) or tear it down. Do not clobber it.

2. **Detect tier 2:**
   ```bash
   grep -q '^theoros:' Makefile 2>/dev/null
   ```
   - Exit 0 → tier 2: shell out to `make theoros` (prefer this).
   - Exit non-zero → tier 1: run tmux commands inline (steps 3–4 below).

3. **(Tier 1 only) Create the session inline:**
   ```bash
   tmux new-session -d -s <session_name> "<repl_command>"
   ```
   If `ops_command` is set, also:
   ```bash
   tmux split-window -t <session_name>:0 -v -l 40%
   tmux send-keys -t <session_name>:0.1 "<ops_command>" Enter
   ```

4. **Verify the session is alive:**
   ```bash
   tmux has-session -t <session_name>
   ```

5. **Print attach instructions** for the user:
   ```
   tmux attach -t <session_name> -r
   ```

6. **Begin driving per the discipline rules below.**

When the session is done: `make theoros-down` (tier 2) or `tmux kill-session -t <session_name>` (tier 1).

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

### Tier 1 quick-start (any repo, ~30 seconds)

Add to `.claude/skill-context.md`:

````markdown
## theoros

```yaml
repl_command: <shell command that launches your interactive REPL>
session_name: <repo-slug>-theoros
```
````

That is the full minimum. The skill runs tmux inline when invoked; you spectate with `tmux attach -t <repo-slug>-theoros -r`.

Optional additions still at tier 1:

- `ops_command: <bottom-pane command>` — enables split layout
- A markdown prose table beneath the YAML block listing aesthetic vs operational concerns specific to the repo

### Tier 2 upgrade (for first-class `make theoros` ergonomics)

When you outgrow tier 1 and want a Makefile target, prerequisite gating, and a persistent state file, add three files. Use kourai-khryseai as the worked reference:

- `scripts/theoros.sh` — copy from `kourai-khryseai/scripts/theoros.sh`; the script is repo-agnostic (it reads everything from `.claude/skill-context.md`).
- Makefile targets:
  ```makefile
  theoros:                   ## Start observed live dev session
  	@bash scripts/theoros.sh up

  theoros-down:              ## Stop observed live dev session
  	@bash scripts/theoros.sh down

  theoros-status:            ## Show theoros session state (JSON)
  	@bash scripts/theoros.sh status
  ```
- Extended `## theoros` YAML:
  ```yaml
  repl_command: <command>
  session_name: <name>
  ops_command: <multi-service log tail or other ops command>
  prerequisites:
    - command: <pre-check shell command>
      message: "what to tell the user if it fails"
  ```

The skill auto-detects tier 2 by grepping for `^theoros:` in `Makefile` and prefers `make theoros` when found.

## Teardown

- Tier 1: `tmux kill-session -t <session_name>`
- Tier 2: `make theoros-down`

`/tmp/<session_name>.state` is removed on `down`. Logs (if `tmux pipe-pane` was opted into) survive `down`; tmux scrollback does not (it dies with the session).
