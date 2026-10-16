#!/usr/bin/env bash
# Regenerate scripts/mod-types/ from the Claude Code build the Makefile pins. Since 2.1.295 the
# engine writes a mod's declarations only in an interactive session that develops it, so this
# opens one in a detached tmux pane on your own login, accepts the folder trust prompt, waits for
# the files, quits, and keeps the two the build defines. No prompt is sent, so no model is called.
set -euo pipefail

: "${CLAUDE_CODE_VERSION:?run through make mod-types, which pins the Claude Code build}"
command -v tmux >/dev/null || { echo "make mod-types needs tmux" >&2; exit 1; }
cd "$(dirname "${BASH_SOURCE[0]}")/.."
plugin=plugins/phylax
types="$plugin/.claude-plugin/types"
session="mod-types-$$"
rm -rf "$types"
tmux new-session -d -s "$session" -x 200 -y 50 -c "$PWD" \
	"env -u CLAUDECODE npx --yes @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION} --plugin-dir $plugin"
trap 'tmux kill-session -t "$session" 2>/dev/null || true' EXIT
trusted=0
for _ in $(seq 1 90); do
	sleep 2
	[ -f "$types/claude-code/index.d.ts" ] && [ -f "$types/claude-code-tools/index.d.ts" ] && break
	if [ "$trusted" = 0 ] && tmux capture-pane -t "$session" -p 2>/dev/null | grep -q "Yes, I trust this folder"; then
		tmux send-keys -t "$session" Down
		sleep 0.5
		tmux send-keys -t "$session" Enter
		trusted=1
	fi
done
[ -f "$types/claude-code/index.d.ts" ] || { echo "FAIL: the session wrote no declarations to $types" >&2; exit 1; }
stamp="$(head -n 1 "$types/claude-code/index.d.ts")"
[ "$stamp" = "// Written by Claude Code ${CLAUDE_CODE_VERSION}." ] || { echo "FAIL: got '$stamp'" >&2; exit 1; }
rm -rf scripts/mod-types
mkdir -p scripts/mod-types
cp -r "$types/claude-code" "$types/claude-code-tools" scripts/mod-types/
echo "scripts/mod-types: declarations from Claude Code ${CLAUDE_CODE_VERSION}"
