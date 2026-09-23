#!/bin/bash
##############################################################################
# theoros: observed live dev session.
#
# Claude drives an interactive REPL in a named tmux session; the human
# spectates with `tmux attach -r`. Run from inside the target repo:
#
#   bash theoros.sh up      # start a session (prerequisites first)
#   bash theoros.sh down    # stop it and remove the state file
#   bash theoros.sh status  # print the state file, or say nothing is running
#
# Configuration is the fenced `yaml` block inside the `## theoros` section of
# the repo's `.claude/skill-context.md`: repl_command and session_name are
# required; ops_command and prerequisites are optional.
##############################################################################

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
SKILL_CONTEXT="${THEOROS_SKILL_CONTEXT_OVERRIDE:-$REPO_ROOT/.claude/skill-context.md}"
STATE_DIR="${THEOROS_STATE_DIR:-/tmp}"

info() { printf '%s\n' "$*"; }
err() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

# The YAML body of the `## theoros` section, without fences.
extract_theoros_yaml() {
    [[ -f "$SKILL_CONTEXT" ]] || err "Skill context not found: $SKILL_CONTEXT"
    awk '
        /^## theoros($|[[:space:]])/ { in_section = 1; next }
        in_section && /^## / { in_section = 0 }
        in_section && /^```yaml[[:space:]]*$/ { in_yaml = 1; next }
        in_section && in_yaml && /^```[[:space:]]*$/ { exit }
        in_section && in_yaml { print }
    ' "$SKILL_CONTEXT"
}

# A single top-level scalar from the YAML block.
yaml_get() {
    extract_theoros_yaml | awk -v key="$1" '
        $0 ~ "^" key ":[[:space:]]" {
            sub("^" key ":[[:space:]]*", "")
            sub(/[[:space:]]+$/, "")
            print
            exit
        }
    '
}

required() {
    local value
    value="$(yaml_get "$1")"
    [[ -n "$value" ]] || err "Required field '$1' missing from the '## theoros' YAML block in $SKILL_CONTEXT"
    printf '%s' "$value"
}

state_file() { printf '%s/%s.state' "$STATE_DIR" "$(required session_name)"; }

# Each `prerequisites:` item is { command, message }; the first failure aborts.
run_prerequisites() {
    local yaml in_section=0 cmd="" msg=""
    yaml="$(extract_theoros_yaml)"
    grep -q '^prerequisites:' <<< "$yaml" || return 0
    while IFS= read -r line; do
        if [[ "$line" =~ ^prerequisites:[[:space:]]*$ ]]; then in_section=1; continue; fi
        (( in_section )) || continue
        [[ "$line" =~ ^[a-zA-Z] ]] && break
        if [[ "$line" =~ ^[[:space:]]*-[[:space:]]*command:[[:space:]]*(.*)$ ]]; then
            [[ -n "$cmd" ]] && check_prerequisite "$cmd" "$msg"
            cmd="${BASH_REMATCH[1]}"
            msg=""
        elif [[ "$line" =~ ^[[:space:]]+message:[[:space:]]*\"(.*)\"[[:space:]]*$ ]]; then
            msg="${BASH_REMATCH[1]}"
        elif [[ "$line" =~ ^[[:space:]]+message:[[:space:]]*(.*)$ ]]; then
            msg="${BASH_REMATCH[1]}"
        fi
    done <<< "$yaml"
    [[ -n "$cmd" ]] && check_prerequisite "$cmd" "$msg"
    return 0
}

check_prerequisite() {
    (cd "$REPO_ROOT" && eval "$1") >/dev/null 2>&1 || err "Prerequisite failed: ${2:-$1}"
}

cmd_status() {
    local sf
    sf="$(state_file)"
    if [[ -f "$sf" ]]; then cat "$sf"; else info "No theoros session running."; fi
}

cmd_up() {
    local session repl ops sf ops_pane="null"
    session="$(required session_name)"
    repl="$(required repl_command)"
    ops="$(yaml_get ops_command || true)"
    sf="$(state_file)"

    if tmux has-session -t "=$session" 2>/dev/null; then
        printf 'theoros session %s is already running.\n  Attach:  tmux attach -t %s -r\n  Restart: bash %s down, then up\n' \
            "$session" "$session" "$0" >&2
        exit 1
    fi

    run_prerequisites

    tmux new-session -d -s "$session" -c "$REPO_ROOT" "$repl"
    tmux set-option -t "$session" history-limit 50000 >/dev/null
    if [[ -n "$ops" ]]; then
        tmux split-window -t "${session}:0.0" -v -l 40% -c "$REPO_ROOT" "$ops"
        ops_pane="\"${session}:0.1\""
    fi

    cat > "$sf" <<EOF
{
  "session": "$session",
  "started_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "cwd": "$REPO_ROOT",
  "attach_cmd": "tmux attach -t $session -r",
  "driver_pane": "${session}:0.0",
  "ops_pane": $ops_pane
}
EOF
    info "theoros session ready."
    info "  Spectate:  tmux attach -t $session -r"
    info "  Tear down: bash $0 down"
}

cmd_down() {
    local session
    session="$(required session_name)"
    if tmux has-session -t "=$session" 2>/dev/null; then tmux kill-session -t "=$session"; fi
    rm -f "$(state_file)"
    info "theoros session '$session' stopped."
}

case "${1:-}" in
    up) cmd_up ;;
    down) cmd_down ;;
    status) cmd_status ;;
    *) printf 'Usage: bash %s {up|down|status}\n' "$0" >&2; exit 2 ;;
esac
