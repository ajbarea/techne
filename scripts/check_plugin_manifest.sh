#!/usr/bin/env bash
# claude plugin validate on the plugin and the marketplace, failing on any warning
# except the missing version: techne is unversioned so installs follow main.
# Always the pinned npm build, so local runs and CI judge the same output.
set -euo pipefail

CLAUDE_CODE_VERSION=2.1.287
claude_cmd=(npx --yes "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}")

status=0
for target in plugins/techne .; do
	if ! out=$("${claude_cmd[@]}" plugin validate "$target" 2>&1); then
		echo "$out"
		status=1
		continue
	fi
	if ! grep -q 'Validation passed' <<<"$out"; then
		echo "FAIL: claude plugin validate $target printed no pass line:"
		echo "$out"
		status=1
		continue
	fi
	# One "Found N warning(s)" block per file validated (manifest, hooks, ...).
	found=$(sed -n 's/.*Found \([0-9][0-9]*\) warning.*/\1/p' <<<"$out" | awk '{n += $1} END {print n + 0}')
	allowed=$(grep -cF 'version: No version specified' <<<"$out" || true)
	if [ "$found" -ne "$allowed" ]; then
		echo "FAIL: claude plugin validate $target warned beyond the missing version:"
		echo "$out"
		status=1
	fi
done
[ "$status" -eq 0 ] && echo "claude plugin validate: plugin + marketplace clean"
exit "$status"
