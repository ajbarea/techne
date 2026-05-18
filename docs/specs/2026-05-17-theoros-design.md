# Theoros — observed live dev session

- **Date:** 2026-05-17
- **Status:** Draft for review
- **Primary artifact:** new `techne:theoros` skill + per-repo (kourai) mechanical setup

## Summary

Theoros is a tmux-based pattern for observed, live REPL sessions. Claude drives an interactive process via `tmux send-keys`; a human spectates read-only via `tmux attach -r`. The pattern ships as a techne skill (behavioral playbook plus a tier-1 inline implementation that runs tmux directly) and optionally a tier-2 per-repo mechanical setup (script plus Makefile targets) for repos that want first-class ergonomics.

The name `theoros` (θεωρός) means "state-appointed spectator who watches a divine spectacle on behalf of the polis and reports back." Etymological ancestor of *theater* and *theory*. The Greek noun precisely names the human's role.

## Motivation

Three problems with the status quo:

1. **The pattern lives in conversational memory, not in any repo.** Memory rot is real (the source memory `feedback_drive_smoke_yourself.md` is already 17 days old; longer for sessions that don't refresh it). Discipline drifts.
2. **The current English name is wrong.** "Smoke" implies a brief sanity check. The actual artifact is a long observed session with operational visibility and explicit aesthetic/operational role-splitting.
3. **The mechanical setup is five commands AJ remembers.** Each invocation re-derives them. A `make theoros` shortcut and a state file remove that toil.

Theoros commits the pattern to the repo and to the skill bundle, so the discipline is loaded into every relevant session and the mechanics are one command.

## Architecture

```
┌───────────────────────────────────────────────────────────────────┐
│ techne/plugins/techne/skills/theoros/SKILL.md                     │
│   Behavioral playbook + tier-1 inline runner                      │
│   • discipline rules (drive yourself, capture yourself, grep      │
│     logs yourself; handoff only for the aesthetic column)         │
│   • reads <repo>/.claude/skill-context.md → ## theoros            │
│   • auto-detects make target → prefers it; else runs tmux inline  │
└───────────────────────────────────────────────────────────────────┘
                           │ reads ## theoros from
                           ▼
┌───────────────────────────────────────────────────────────────────┐
│ <repo>/.claude/skill-context.md   ## theoros section              │
│   Per-repo facts: REPL command, session name, optional ops cmd,   │
│   optional prerequisites, optional aesthetic/operational table.   │
│   Two required fields (tier 1); more for tier 2.                  │
└───────────────────────────────────────────────────────────────────┘
                           │ consumed by (tier 2 only)
                           ▼
┌───────────────────────────────────────────────────────────────────┐
│ <repo>/scripts/theoros.sh   +   Makefile targets   (tier 2)       │
│   up / down / status subcommands. Writes JSON state to            │
│   /tmp/<session>.state for cross-turn persistence.                │
└───────────────────────────────────────────────────────────────────┘
```

## Tier 1 — skill-only (drop-in for any repo)

The minimum a repo needs to opt in. The `## theoros` section in `.claude/skill-context.md` contains a fenced YAML block for machine-parseable fields, plus optional human-readable prose:

````markdown
## theoros

```yaml
repl_command: <shell command that launches the interactive REPL>
session_name: <unique tmux session name; recommended <repo-slug>-theoros>
```
````

Two fields, one fenced block. When the user invokes theoros, the skill runs the REPL directly inside a detached tmux session (no `script(1)` wrapper — see "Why no `script -qc`" below):

```bash
tmux new-session -d -s "$SESSION_NAME" "$REPL_COMMAND"
```

- **Spectator:** `tmux attach -t <session-name> -r`
- **Take over:** drop `-r`
- **Driver (Claude):** `tmux send-keys -t <session-name>:0.0 '<text>' Enter` + `tmux capture-pane -t <session-name>:0.0 -p -S -<n>`
- **Read buffer:** tmux's own scrollback (raise via `tmux set-option -t <session> history-limit 20000` if a long session is expected). Capture-pane reads it without injecting an extra PTY layer.
- **Persistence across Claude's turns:** `tmux has-session -t <session-name>` is the source of truth; no state file at this tier.
- **Teardown:** `tmux kill-session -t <session-name>`.

### Why no `script -qc`

The earlier sketch wrapped the REPL in `script -qc "..." /tmp/<session>.log` for post-mortem persistence. Web search (May 2026) surfaced known issues with PTY wrappers injected inside tmux panes: the extra PTY layer between tmux and the inner process breaks `#{pane_tty}` tracking and can mangle terminal control codes. The cleaner idiom is to let tmux's own scrollback be the buffer and use `tmux capture-pane -p -S -<n>` for reads. Repos that genuinely need post-mortem persistence-after-down can opt in to `tmux pipe-pane -o 'sed -u "s/\x1b\[[0-9;]*[a-zA-Z]//g" >> /tmp/<session>.log'` as a tier-2 feature.

### Optional tier-1 additions

Adding an `ops_command` switches to split layout:

````markdown
```yaml
repl_command: <shell command>
session_name: <name>
ops_command: <command for the bottom pane>
```
````

The skill then runs `tmux split-window -t <session-name>:0 -v -l 40%` and runs the ops command in the bottom pane (`:0.1`). Modern tmux 3.1+ idiom (`-l N%`, not legacy `-p N`).

Adding an aesthetic/operational table (markdown prose, *outside* the YAML block) further specializes the discipline:

```markdown
**Aesthetic vs operational:**

| Aesthetic (human) | Operational (Claude) |
|---|---|
| <human-eye thing>  | <log/metric thing>  |
```

Absent table: Claude follows the default discipline (capture everything yourself, never ask human to paste).

## Tier 2 — full mechanical (kourai-style power-user setup)

For repos that want `make theoros` as a first-class command, persistent state file, and prerequisite gating.

### `scripts/theoros.sh`

Bash. Three subcommands. Parses the fenced ```yaml block inside `## theoros` of `.claude/skill-context.md` via `yq` if available, with a basic `awk`/`grep` fallback for portability.

**`up`:**
1. Pre-flight: run each prerequisite command from the YAML `prerequisites:` list. Abort with a clear message naming the failing prerequisite if any fail.
2. If the named tmux session already exists, print a concrete next-step message and exit non-zero:
   > `theoros session 'kourai-theoros' already running (started <timestamp from state file>).`
   > `  Attach:     tmux attach -t kourai-theoros -r`
   > `  Restart:    make theoros-down && make theoros`
3. Create the session detached. Single pane if no `ops_command`, split layout (`split-window -l 40%`) if present.
4. Top pane: `tmux new-session -d -s <session> "<repl_command>"` directly. No `script -qc` wrapper (see "Why no `script -qc`" above).
5. Bottom pane (if `ops_command` present): launched via `tmux send-keys -t <session>:0.1 "<ops_command>" Enter`.
6. Write `/tmp/<session-name>.state` (JSON): `session`, `started_at` (ISO 8601 UTC), `cwd` (absolute path of the repo, for cross-repo disambiguation when the same session name is reused elsewhere), `repl_pid` (the tmux pane PID, for health-check purposes), `attach_cmd`, `driver_pane`, `ops_pane` (or `null`).
7. Print attach instructions.

**`down`:** `tmux kill-session -t <session-name>`; remove the state file. No log files are written by default at tier 2 either — tmux scrollback is the buffer. If the repo opts into `pipe-pane` for post-mortem persistence, those logs survive `down`.

**`status`:** print the state file (pretty-printed) or `"No theoros session running."`.

**Parsing convention:** the script reads the YAML block strictly. If the script-context YAML is malformed (missing required `repl_command`/`session_name`, invalid fenced block, ambiguous indentation), abort with the YAML parser's message plus a pointer to the spec section that documents the format. No silent fallback to "best-effort" parsing.

**Missing Makefile:** the auto-detect step grep for `'^theoros:'` against `Makefile 2>/dev/null` — if the file doesn't exist (vFL doesn't have one in tier-1 form), the grep returns nonzero, the skill takes the tier-1 inline path. No special-casing needed.

### Makefile targets

```makefile
theoros:                   ## Start observed dev session (Claude drives, spectate via tmux -r)
	@bash scripts/theoros.sh up

theoros-down:              ## Stop observed dev session
	@bash scripts/theoros.sh down

theoros-status:            ## Show theoros session state (JSON)
	@bash scripts/theoros.sh status
```

Placed alongside the existing `cli` / `gui` / `observe` block in kourai's Makefile.

### Extended `## theoros` (kourai)

Kourai's actual docker-compose has many agent services (`metis`, `mneme`, `kallos`, `dokimasia`, `puck`, `cupid`, `aidos`, `aletheia`, `hephaestus`, `vn-bridge`, plus infra `jaeger`, `prometheus`, `dozzle`, `memory-mcp`, `memory-graph-storage`). The `ops_command` should tail a curated subset of *agent* services — the ones most operationally interesting for the run you are about to do — not all 15 services (visual noise) and not the infra (better surfaced via `make observe`).

````markdown
## theoros

```yaml
repl_command: make cli
session_name: kourai-theoros
ops_command: docker compose logs -f --tail 0 metis mneme hephaestus
prerequisites:
  - command: docker compose ps --status running --quiet | grep -q .
    message: "Core containers not running. Run 'make up' first."
```

**Aesthetic vs operational responsibility:**

| Aesthetic (AJ's eyes/ears) | Operational (Claude via logs) |
|---|---|
| Does Metis's voice sound natural? | Did Metis receive the request? |
| Does recall narration feel earned? | Did `narration emitted` fire? |
| Does audio crackle / clip? | What sample rate did pygame init at? |
| Does the comms-window layout look right? | What was the box width / content length? |
| Does the chat feel coherent across turns? | What did Hephaestus's user-message body contain? |
````

## Auto-detection (skill logic)

When invoked, the skill in techne:

1. `cat .claude/skill-context.md`; look for `## theoros`. Missing → abort with the scaffolding instructions from the skill body.
2. Parse the fenced ```yaml block. `repl_command` and `session_name` are required; missing either is a hard error pointing back to the spec format.
3. Probe for tier 2: `grep -q '^theoros:' Makefile 2>/dev/null` (the `2>/dev/null` handles repos with no Makefile at all, falling through to tier 1).
   - **Yes:** shell out to `make theoros`. Tier 2 path.
   - **No:** run tmux commands inline. Tier 1 path.
4. Verify the session was created (`tmux has-session -t <session-name>`); abort with the tmux error if not.
5. Print spectator attach command to the user.
6. Begin driving per the discipline rules.

One IF statement, two paths, same skill.

## Discipline rules (encoded in the skill body)

Hard rules, derived from the M17 lessons in `feedback_drive_smoke_yourself.md`:

1. **Drive the REPL via `send-keys`.** Never paste-and-go via the human's terminal.
2. **Capture pane output yourself.** Never ask "what does the screen say?"
3. **Grep logs yourself.** Either via the ops pane (`tmux capture-pane -t <session>:0.1 -p -S -<n> | grep <pattern>`) or directly against the source (`docker compose logs <svc> | grep`, `kubectl logs`, `tail`, etc.). Direct source query is the source of truth; the pane is informational for the human.
4. **Handoff is for aesthetic judgment only.** Defined by the aesthetic/operational table when present, by the default discipline when absent.
5. **If the human pastes a transcript, treat that as a signal you forgot rules 1–4.** Acknowledge before continuing.

## Skill body structure

Sections of `techne/plugins/techne/skills/theoros/SKILL.md`, in order:

1. Frontmatter (`name`, `description` with trigger phrases, `disable-model-invocation: false`, `allowed-tools: Bash Read Grep`)
2. What theoros is — one paragraph including the etymology
3. Repo context — `cat .claude/skill-context.md` inline, with the "no `## theoros` section" abort path
4. Lifecycle (the five steps above)
5. Discipline rules (the five rules above)
6. Capture-pane / send-keys idioms (exact incantations for driver pane and ops pane)
7. Scaffolding section — graduated quick-start
   - **Tier 1 quick-start:** paste this 4-line `## theoros` block, you are done
   - **Tier 2 upgrade path:** when you want `make theoros` ergonomics, copy these templates and adapt. Kourai is the worked example.
8. Teardown

## README + docs updates

### `techne/README.md`

Add to the `## Skills` bullet list:

> `techne:theoros` — start an observed live dev session: Claude drives the REPL in a named tmux session, you spectate read-only via `tmux attach -r`. Tier-1 drop-in (two-line skill-context.md opt-in); tier-2 mechanical setup optional.

### `kourai-khryseai/README.md`

Add a subsection under the existing dev-workflow section:

> #### Live observed dev session (`make theoros`)
>
> Spins up a split tmux session where Claude drives `make cli` and you spectate with backend container logs. Run `make theoros`, then attach in another terminal: `tmux attach -t kourai-theoros -r`. `make theoros-down` tears it down.

### `kourai-khryseai/docs/theoros.md`

New page alongside `cli.md` / `gui.md` / `observability.md`. Covers, in roughly this order:

- The etymology line
- Role split: Claude as driver, AJ as theoros
- How to start a session (`make theoros`) and how to attach
- The aesthetic vs operational table and the philosophy behind it
- How to grep the captured logs after the session ends
- Troubleshooting (session won't start, attach shows nothing, etc.)

Target length: 200–300 words. One Zensical-rendered page. Add to `zensical.toml` nav under the dev section.

## State and lifecycle

- **Tier 1:** `tmux has-session` is the source of truth between Claude's turns. No state file. Tmux's own scrollback buffer (raise via `set-option history-limit` if needed) serves as the read buffer.
- **Tier 2:** `/tmp/<session-name>.state` (JSON) carries metadata across turns: session name, started_at, cwd (for cross-repo disambiguation), repl_pid, attach_cmd, pane references. Removed on `down`.
- **Logs:** none by default. The REPL output lives in tmux scrollback; capture-pane on demand. Repos opting into `tmux pipe-pane -o '...'` for post-mortem persistence write to `/tmp/<session-name>-cli.log` — this is opt-in, not default.
- **Reboot semantics:** tmux sessions and `/tmp` files do not survive reboot. Clean slate each boot. This is the desired behavior.
- **Cross-repo session name collisions:** the state file's `cwd` field disambiguates if two repos pick the same `session_name`. Recommend repos use `<repo-slug>-theoros` to avoid the issue entirely.

## Platform notes

- **Tested host:** WSL2 (Linux 6.6 kernel) — AJ's primary dev environment. Tmux 3.4, Docker Compose v5.1.3.
- **WSL2 quirk:** none specific to theoros — tmux and docker compose work normally inside WSL2. The `script(1)` PTY issue would have been platform-agnostic, so dropping that wrapper avoids any cross-platform surprises.
- **macOS:** `tmux pipe-pane` and `tmux send-keys` behave identically. The `awk`/`grep` YAML-fallback path must use BSD-awk-compatible syntax (or require `yq` on macOS too).
- **Native Linux desktop:** same as WSL2.

## Research notes (May 2026 web search)

Validated against current best practice:

- **`tmux attach -r`** is the documented spectate idiom; named persistent sessions are the recommended pattern for "zero context loss when switching between human and AI control." (tmux 3.4 manual, 2026 tmux guides.)
- **`tmux send-keys ... 'text' Enter`** with Enter as a separate argument is the canonical form. Embedding Enter in the quoted string is a known foot-gun.
- **`tmux split-window -l N%`** is the current idiom (tmux 3.1+). Legacy `-p N` still works in 3.4 but is no longer documented as primary.
- **`docker compose logs -f --tail 0 svc1 svc2 ...`** does native multi-service multiplexing with built-in service-name prefix and color. Strictly better than a hand-rolled `docker logs -f | sed 's/^/Prefix|/' &` parallel pipeline.
- **Anthropic RFC #26572** (CustomPaneBackend protocol) is in flight to decouple Claude Code agent teams from tmux specifically. Tmux is the correct call now; the skill's contract is replaceable behind the same interface later.
- **Haiku-as-state-monitor** (small model reads raw pane scrollback, emits JSON state summaries) is an emerging 2026 technique. Not v1; flagged as future work.

## File list (touch surface)

**New files** (3):
- `techne/plugins/techne/skills/theoros/SKILL.md`
- `kourai-khryseai/scripts/theoros.sh`
- `kourai-khryseai/docs/theoros.md`

**Edited files** (5):
- `techne/README.md` — add bullet to skills list
- `kourai-khryseai/Makefile` — three new targets next to the existing `cli` block
- `kourai-khryseai/README.md` — dev-workflow subsection
- `kourai-khryseai/.claude/skill-context.md` — new `## theoros` section
- `kourai-khryseai/zensical.toml` — nav entry for the new docs page

Total: 3 new, 5 edited.

## Out of scope (deferred or rejected)

- **Greek-renaming the other 8 techne skills.** Considered; rejected. The existing English names are descriptive industry vocabulary; renaming would hurt DX for the "random dev trying the bundle" path. Theoros stands alone in tier 1 of the Greek naming until a future skill earns it.
- **Haiku-as-state-monitor.** Future technique; not v1.
- **Multi-session orchestration.** One theoros session per repo at a time.
- **Non-tmux backends** (zellij, ghostty, WezTerm panes). RFC #26572 will make this swappable later; the skill's contract is tmux-shaped for now.
- **Auto-scaffolding tier 2** ("Claude detects no tier-2 setup, offers to scaffold"). Future enhancement; manual copy from kourai is the v1 path.
- **Phalanx-fl / vFL / fl-execution-framework-dev adoption.** None have interactive REPLs today. Opt-in if they ever grow one.
- **`script(1)` log rotation.** Per-session logs in `/tmp` are tolerated; reboot wipes them. No rotation needed.

## Resolved in red-pen pass

- **Skill-context format:** fenced ```yaml block for machine fields + markdown prose outside the block for the aesthetic/operational table. Earlier open question Q4 resolved.
- **No `script(1)` wrapper:** dropped due to known PTY-injection issues inside tmux panes (web search, May 2026). Tmux scrollback is the read buffer; `pipe-pane` is the tier-2-optional persistence mechanism.
- **State file PID:** include `repl_pid` for health-check purposes (was open question Q2).

## Open questions for review

1. Should `scripts/theoros.sh up` accept `--force` to replace an existing session, or is the concrete "session exists" message + manual `make theoros-down` flow enough? (Leaning enough; explicit is better than magic for a 4-hour-stale session.)
2. Where in `zensical.toml`'s nav does the kourai theoros docs page slot? Likely the section that currently holds `cli.md` / `gui.md` — need to grep `zensical.toml` during implementation and confirm.
3. **Techne itself has no Zensical docs site yet.** AJ flagged this mid-review. This spec adds `techne/docs/specs/2026-05-17-theoros-design.md` as a static file; the techne README absorbs the user-facing bullet. A full techne docs site (mirroring kourai / vFL / phalanx-fl) is a separate, larger initiative not covered here. Worth flagging as a follow-on but explicitly out of scope.

## Success criteria

- A stranger cloning techne can read `techne:theoros` SKILL.md, add ~6 lines (heading + fenced YAML with two fields) to their repo's `.claude/skill-context.md`, run the skill, and have a working session.
- Kourai's existing live-smoke pattern is replaced by `make theoros` + `tmux attach -r` with no loss of discipline; the aesthetic/operational table is committed to the repo, not the memory.
- The discipline rules survive memory rot (now encoded in skill body + repo skill-context, not in conversational memory).
- No regressions in kourai's existing dev workflow (`make cli`, `make observe`, etc. still work unchanged).
- The `script(1)` PTY-wrapper foot-gun is avoided from day one.
