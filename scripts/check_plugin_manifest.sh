#!/usr/bin/env bash
# claude plugin validate on the plugin and the marketplace, failing on any warning
# except the missing version: techne is unversioned so installs follow main.
# Uses `claude` when it is on PATH, otherwise the pinned npm build (no login needed).
set -euo pipefail

CLAUDE_CODE_VERSION=2.1.287
if command -v claude >/dev/null; then
	claude_cmd=(claude)
else
	claude_cmd=(npx --yes "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}")
fi

status=0
for target in plugins/techne .; do
	if ! out=$("${claude_cmd[@]}" plugin validate "$target" 2>&1); then
		echo "$out"
		status=1
		continue
	fi
	unexpected=$(grep -F '❯' <<<"$out" | grep -vF 'version: No version specified' || true)
	if [ -n "$unexpected" ]; then
		echo "FAIL: claude plugin validate $target warned:"
		echo "$unexpected"
		status=1
	fi
done
[ "$status" -eq 0 ] && echo "claude plugin validate: plugin + marketplace clean"
exit "$status"
