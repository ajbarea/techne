#!/usr/bin/env bash
# claude plugin test and a strict tsc on each plugin that ships a hooks module (a mod): one whose
# hooks/hooks.json names `modules`. Both run on the Claude Code build the Makefile pins.
#
# tsc needs the build's declarations, which the engine writes into <plugin>/.claude-plugin/types/
# whenever it loads the plugin from a folder. A `claude -p --plugin-dir` run in a bare environment
# (no credentials, a fresh config directory) loads it and stops at "Not logged in", so no model is
# ever called.
set -euo pipefail

: "${CLAUDE_CODE_VERSION:?run through make plugin-test, which pins the Claude Code build}"
: "${TYPESCRIPT_VERSION:?run through make plugin-test, which pins the TypeScript build}"
claude_cmd=(npx --yes "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}")

cd "$(dirname "${BASH_SOURCE[0]}")/.."
status=0
for manifest in plugins/*/hooks/hooks.json; do
	grep -q '"modules"' "$manifest" || continue
	plugin="${manifest%/hooks/hooks.json}"
	if ! compgen -G "$plugin/tests/*.test.ts" >/dev/null; then
		echo "FAIL: $plugin ships a hooks module but no tests/*.test.ts"
		status=1
		continue
	fi
	"${claude_cmd[@]}" plugin test "$plugin" || { status=1; continue; }

	# Stale types from an earlier build must not stand in for this one's.
	rm -rf "$plugin/.claude-plugin/types"
	config=$(mktemp -d)
	env -i PATH="$PATH" HOME="$HOME" CLAUDE_CONFIG_DIR="$config" \
		timeout 120 "${claude_cmd[@]}" -p --plugin-dir "$plugin" "load only" >/dev/null 2>&1 || true
	rm -rf "$config"
	if [ ! -f "$plugin/.claude-plugin/types/tsconfig.json" ]; then
		echo "FAIL: loading $plugin wrote no types to $plugin/.claude-plugin/types/"
		status=1
		continue
	fi
	npx --yes -p "typescript@${TYPESCRIPT_VERSION}" tsc --noEmit -p "$plugin" || status=1
done
[ "$status" -eq 0 ] && echo "hooks modules: tests and tsc clean"
exit "$status"
