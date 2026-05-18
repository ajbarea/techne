# `techne:theoros`

Starts an observed live dev session: Claude drives the REPL in a named `tmux` session; you spectate read-only via `tmux attach -r`.

## When to use

- You want to watch Claude work without driving the terminal yourself.
- Pairing with a remote teammate who wants visibility into the live session.
- Recording or screen-sharing a session for later review.
- Auditing or verifying a long-running operation (tests, builds, migrations).

## How it works

1. Skill spawns a named `tmux` session (e.g., `theoros-<ts>`).
2. Claude runs commands in that session.
3. You (or anyone with shell access) attach read-only: `tmux attach -r -t theoros-<ts>`.
4. Output streams to all observers in real time.
5. When the skill finishes, the session persists so you can review or continue manually.

## Tiers

| Tier | Complexity | Use when |
|---|---|---|
| **Tier 1 (drop-in)** | Two-field YAML block in `.claude/skill-context.md` | You want minimal setup; skill handles the rest. |
| **Tier 2 (mechanical)** | Optional `scripts/theoros.sh` + Makefile target + extended skill context | You want custom environment, hooks, or pre/post actions. |

## Usage

```bash
# Start Tier 1 observed session
techne:theoros

# Watch the session (from another terminal)
tmux attach -r -t theoros-<session-id>

# For Tier 2 with custom setup
techne:theoros --tier 2
```

## Configuration

**Tier 1 (minimal)** — add to `.claude/skill-context.md`:

```yaml
theoros:
  project_root: /home/ajbar/ajsoftworks/techne
```

**Tier 2 (extended)** — add more fields plus create `scripts/theoros.sh`:

```yaml
theoros:
  project_root: /home/ajbar/ajsoftworks/techne
  pre_run: "scripts/theoros.sh setup"
  post_run: "scripts/theoros.sh cleanup"
  environment:
    DEBUG: "1"
  shell: bash
```

Example `scripts/theoros.sh`:

```bash
#!/bin/bash
set -e

case "${1:-run}" in
  setup)
    echo "Setting up Theoros session..."
    source .venv/bin/activate
    ;;
  cleanup)
    echo "Cleaning up..."
    ;;
esac
```

## Troubleshooting

**"tmux: command not found"**: Install tmux: `apt-get install tmux` (Linux) or `brew install tmux` (macOS).

**"attach -r denied"**: Ensure the tmux session is running and you have file access to the socket (typically in `/tmp`).

**"Session exits immediately"**: Check the pre-run script for errors. Run it manually to debug: `bash scripts/theoros.sh setup`.

## See also

- Project docs on Theoros: [Theoros Design Spec](../specs/2026-05-17-theoros-design.md)

## Reads

- `<repo>/.claude/skill-context.md`
- `<repo>/scripts/theoros.sh` (Tier 2 only)
- `<repo>/Makefile` (Tier 2 only)
