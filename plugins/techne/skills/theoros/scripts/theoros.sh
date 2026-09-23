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
#
# Panes are addressed by tmux pane id (%N), never by window.pane index, so a
# tmux.conf with base-index 1 or pane-base-index 1 does not break the layout.
##############################################################################

set -euo pipefail
shopt -s inherit_errexit  # a failed lookup inside $( ) must abort the command

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

# A YAML scalar with one layer of matching quotes removed.
unquote() {
    local v="$1"
    if [[ ${#v} -ge 2 && ( ( "${v:0:1}" == '"' && "${v: -1}" == '"' ) || ( "${v:0:1}" == "'" && "${v: -1}" == "'" ) ) ]]; then
        v="${v:1:${#v}-2}"
    fi
    printf '%s' "$v"
}

# A single top-level scalar from the YAML block.
yaml_get() {
    local raw
    raw="$(extract_theoros_yaml | awk -v key="$1" '
        $0 ~ "^" key ":[[:space:]]" {
            sub("^" key ":[[:space:]]*", "")
            sub(/[[:space:]]+$/, "")
            print
            exit
        }
    ')"
    unquote "$raw"
}

required() {
    local value
    value="$(yaml_get "$1")"
    [[ -n "$value" ]] || err "Required field '$1' missing from the '## theoros' YAML block in $SKILL_CONTEXT"
    printf '%s' "$value"
}

# tmux rewrites "." and ":" in a session name to "_"; use the name tmux will actually hold,
# or a slug like "ajbarea.github.io-theoros" creates one session and looks up another.
session_name() {
    local name
    name="$(required session_name)"
    printf '%s' "${name//[.:]/_}"
}

json_str() {
    local s="$1"
    s="${s//\\/\\\\}"
    s="${s//\"/\\\"}"
    printf '"%s"' "$s"
}

# Each `prerequisites:` item is a `- ` entry carrying `command:` and `message:` in either
# order; items are checked in file order and the first failure aborts.
run_prerequisites() {
    local yaml in_section=0 in_item=0 cmd="" msg="" line body
    yaml="$(extract_theoros_yaml)"
    grep -q '^prerequisites:' <<< "$yaml" || return 0
    while IFS= read -r line; do
        if [[ "$line" =~ ^prerequisites:[[:space:]]*$ ]]; then in_section=1; continue; fi
        (( in_section )) || continue
        [[ "$line" =~ ^[a-zA-Z] ]] && break
        if [[ "$line" =~ ^[[:space:]]*-[[:space:]]*(.*)$ ]]; then
            (( in_item )) && check_prerequisite "$cmd" "$msg"
            in_item=1 cmd="" msg=""
            body="${BASH_REMATCH[1]}"
        else
            body="$line"
        fi
        if [[ "$body" =~ ^[[:space:]]*command:[[:space:]]*(.*[^[:space:]])[[:space:]]*$ ]]; then
            cmd="$(unquote "${BASH_REMATCH[1]}")"
        elif [[ "$body" =~ ^[[:space:]]*message:[[:space:]]*(.*[^[:space:]])[[:space:]]*$ ]]; then
            msg="$(unquote "${BASH_REMATCH[1]}")"
        fi
    done <<< "$yaml"
    (( in_item )) && check_prerequisite "$cmd" "$msg"
    return 0
}

check_prerequisite() {
    [[ -n "$1" ]] || err "A prerequisites item has no command: ${2:-(no message)}"
    (cd "$REPO_ROOT" && eval "$1") >/dev/null 2>&1 || err "Prerequisite failed: ${2:-$1}"
}

alive() { tmux has-session -t "=$1" 2>/dev/null; }

cmd_status() {
    local session sf
    session="$(session_name)"
    sf="$STATE_DIR/$session.state"
    if [[ -f "$sf" ]] && alive "$session"; then
        cat "$sf"
    elif [[ -f "$sf" ]]; then
        rm -f "$sf"
        info "No theoros session running (removed a stale state file for '$session')."
    else
        info "No theoros session running."
    fi
}

cmd_up() {
    local session repl ops sf driver ops_pane="null"
    session="$(session_name)"
    repl="$(required repl_command)"
    ops="$(yaml_get ops_command || true)"
    sf="$STATE_DIR/$session.state"

    if alive "$session"; then
        printf 'theoros session %s is already running.\n  Attach:  tmux attach -t %s -r\n  Restart: bash %s down, then up\n' \
            "$session" "$session" "$0" >&2
        exit 1
    fi

    run_prerequisites

    driver="$(tmux new-session -d -P -F '#{pane_id}' -s "$session" -c "$REPO_ROOT" "$repl")"
    # A REPL that exits on start takes its session with it; say so instead of "ready".
    sleep 0.3
    alive "$session" || err "The REPL exited as soon as it started: $repl"
    tmux set-option -t "$driver" history-limit 50000 >/dev/null
    if [[ -n "$ops" ]]; then
        ops_pane="$(json_str "$(tmux split-window -P -F '#{pane_id}' -t "$driver" -v -l 40% -c "$REPO_ROOT" "$ops")")"
    fi

    cat > "$sf" <<EOF
{
  "session": $(json_str "$session"),
  "started_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "cwd": $(json_str "$REPO_ROOT"),
  "attach_cmd": $(json_str "tmux attach -t $session -r"),
  "driver_pane": $(json_str "$driver"),
  "ops_pane": $ops_pane
}
EOF
    info "theoros session ready."
    info "  Spectate:  tmux attach -t $session -r"
    info "  Driver:    $driver"
    info "  Tear down: bash $0 down"
}

cmd_down() {
    local session
    session="$(session_name)"
    if alive "$session"; then tmux kill-session -t "=$session"; fi
    rm -f "$STATE_DIR/$session.state"
    info "theoros session '$session' stopped."
}

case "${1:-}" in
    up) cmd_up ;;
    down) cmd_down ;;
    status) cmd_status ;;
    *) printf 'Usage: bash %s {up|down|status}\n' "$0" >&2; exit 2 ;;
esac
