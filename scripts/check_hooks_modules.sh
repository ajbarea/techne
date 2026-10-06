#!/usr/bin/env bash
# claude plugin test and a strict tsc on each plugin that ships a hooks module (a mod), both on
# the Claude Code build the Makefile pins.
#
# tsc needs the build's declarations, which the engine writes into <plugin>/.claude-plugin/types/
# whenever it loads the plugin from a folder. An unauthenticated `claude -p --plugin-dir` run loads
# it and stops at "Not logged in", so no model is called; its config directory is a fresh temp one
# and ANTHROPIC_API_KEY is unset to keep it that way.
set -euo pipefail

: "${CLAUDE_CODE_VERSION:?run through make plugin-test, which pins the Claude Code build}"
: "${TYPESCRIPT_VERSION:?run through make plugin-test, which pins the TypeScript build}"
claude_cmd=(npx --yes "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}")

cd "$(dirname "${BASH_SOURCE[0]}")/.."
status=0
for tests in plugins/*/tests; do
	plugin="${tests%/tests}"
	"${claude_cmd[@]}" plugin test "$plugin" || { status=1; continue; }

	config=$(mktemp -d)
	env -u ANTHROPIC_API_KEY CLAUDE_CONFIG_DIR="$config" \
		"${claude_cmd[@]}" -p --plugin-dir "$plugin" "load only" >/dev/null 2>&1 || true
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
