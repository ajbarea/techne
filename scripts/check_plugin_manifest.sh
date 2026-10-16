#!/usr/bin/env bash
# claude plugin validate on each plugin and the marketplace, failing on any warning
# except the missing version: the plugins are unversioned so installs follow main.
# Always the pinned npm build the Makefile names, so local runs and CI judge the same output.
set -euo pipefail

: "${CLAUDE_CODE_VERSION:?run through make plugin-validate, which pins the Claude Code build}"
claude_cmd=(npx --yes "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}")

status=0
for target in plugins/*/ .; do
	target="${target%/}"
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
	# A hook that can refuse an action must refuse when it fails, which only a .catch does.
	if [ -f "$target/hooks/hooks.json" ] && grep -q '"modules"' "$target/hooks/hooks.json"; then
		report=$("${claude_cmd[@]}" plugin validate "$target" --json 2>/dev/null || true)
		uncaught=$(VALIDATE_JSON="$report" python3 - <<'PY'
import json
import os

data = json.loads(os.environ["VALIDATE_JSON"])
parts = [data.get("manifest") or {}] + list(data.get("contents") or [])
for part in parts:
    for hook in part.get("gatingHooks") or []:
        if not hook.get("hasCatch"):
            print(hook.get("module"), hook.get("hook"))
PY
		) || uncaught="(could not read claude plugin validate --json)"
		if [ -n "$uncaught" ]; then
			echo "FAIL: $target has a gating hook without .catch: $uncaught"
			status=1
		fi
	fi
done
[ "$status" -eq 0 ] && echo "claude plugin validate: plugins + marketplace clean"
exit "$status"
