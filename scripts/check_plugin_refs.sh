#!/usr/bin/env bash
# Every ${CLAUDE_PLUGIN_ROOT}/<path> a plugin names must exist inside that plugin: a plugin
# installs alone, so a file that lives only in a sibling plugin is missing at runtime.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
status=0
for plugin in plugins/*/; do
	plugin="${plugin%/}"
	refs=$(grep -rhoE '\$\{CLAUDE_PLUGIN_ROOT\}/[A-Za-z0-9_./-]+' "$plugin" \
		--include='*.md' --include='*.json' --include='*.sh' --include='*.py' \
		--exclude-dir=eval-fixtures | sort -u) || true
	while IFS= read -r ref; do
		[ -n "$ref" ] || continue
		rel="${ref#'${CLAUDE_PLUGIN_ROOT}/'}"
		rel="${rel%.}"
		if [ ! -e "$plugin/$rel" ]; then
			echo "FAIL: $plugin names \${CLAUDE_PLUGIN_ROOT}/$rel, which it does not ship"
			status=1
		fi
	done <<<"$refs"
done
[ "$status" -eq 0 ] && echo "OK: every \${CLAUDE_PLUGIN_ROOT} path resolves inside its plugin"
exit "$status"
