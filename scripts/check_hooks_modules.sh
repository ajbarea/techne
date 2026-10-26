#!/usr/bin/env bash
# claude plugin test and a strict tsc on each plugin that ships a hooks module (a mod): one whose
# hooks/hooks.json names `modules`. Both run on the Claude Code build the Makefile pins.
#
# tsc needs the build's declarations. Since 2.1.295 the engine writes them only in an interactive
# session that develops the mod, never in `-p` or CI, so they are kept in scripts/mod-types/ (from
# `make mod-types`) and copied into <plugin>/.claude-plugin/types/ here. Their first line names the
# build that wrote them, which must be the pinned one.
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
		echo "FAIL: $plugin ships a hooks module but no tests/*.test.ts" >&2
		status=1
		continue
	fi
	"${claude_cmd[@]}" plugin test "$plugin" || { status=1; continue; }

	stamp="$(head -n 1 scripts/mod-types/claude-code/index.d.ts 2>/dev/null || true)"
	if [ "$stamp" != "// Written by Claude Code ${CLAUDE_CODE_VERSION}." ]; then
		echo "FAIL: scripts/mod-types is from '${stamp#// }', not ${CLAUDE_CODE_VERSION}; run make mod-types" >&2
		status=1
		continue
	fi
	if [ ! -f scripts/mod-types/claude-code-tools/index.d.ts ]; then
		echo "FAIL: scripts/mod-types/claude-code-tools is missing; run make mod-types" >&2
		status=1
		continue
	fi
	types="$plugin/.claude-plugin/types"
	rm -rf "$types"
	mkdir -p "$types"
	cp -r scripts/mod-types/claude-code scripts/mod-types/claude-code-tools "$types/"
	printf '*\n' >"$types/.gitignore"
	cat >"$types/tsconfig.json" <<'JSON'
{
  "compilerOptions": {
    "target": "es2023", "lib": ["es2023"], "module": "esnext", "moduleResolution": "bundler",
    "strict": true, "noUncheckedIndexedAccess": true, "noEmit": true, "skipLibCheck": true,
    "jsx": "react", "jsxFactory": "h", "jsxFragmentFactory": "Fragment",
    "typeRoots": ["."], "types": ["claude-code", "claude-code-tools"]
  },
  "include": ["../../hooks", "../../types", "../../tests"]
}
JSON
	npx --yes -p "typescript@${TYPESCRIPT_VERSION}" tsc --noEmit -p "$plugin" || status=1
done
[ "$status" -eq 0 ] && echo "hooks modules: tests and tsc clean"
exit "$status"
