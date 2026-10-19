#!/usr/bin/env bash
# Install the marketplace from GitHub into Claude Code, Codex and Copilot CLI inside a throwaway
# container with an empty home, as a new user would. Mounts nothing from this machine and signs
# in to nothing, so it tests the published main branch, not the working tree.
set -euo pipefail
cd "$(dirname "$0")/.."

repo="${INSTALL_PROBE_REPO:-ajbarea/techne}"
image="${INSTALL_PROBE_IMAGE:-node:22-bookworm}"
claude_plugins=$(python3 -c 'import json; print(" ".join(p["name"] for p in json.load(open(".claude-plugin/marketplace.json"))["plugins"]))')
portable=$(sed -n 's/^PORTABLE=" *\(.*[^ ]\) *"$/\1/p' scripts/check_plugin_refs.sh)
[ -n "$portable" ] || { echo "install-probe: no PORTABLE list in scripts/check_plugin_refs.sh"; exit 2; }

command -v docker >/dev/null || { echo "install-probe: docker not on PATH"; exit 2; }

# shellcheck disable=SC2016  # expanded inside the container
docker run --rm -e REPO="$repo" -e CLAUDE_PLUGINS="$claude_plugins" -e PORTABLE="$portable" \
	--user node -e HOME=/home/node "$image" bash -c '
set -uo pipefail
export NPM_CONFIG_PREFIX=$HOME/.npm-global PATH=$HOME/.npm-global/bin:$PATH CI=1
failed=0
step() {
	if out=$("$@" 2>&1); then echo "ok    $*"; else echo "FAIL  $*"; echo "$out" | tail -5 | sed "s/^/      /"; failed=1; fi
}
npm install -g --silent @anthropic-ai/claude-code @openai/codex @github/copilot >/dev/null 2>&1 \
	|| { echo "FAIL  npm install of the three CLIs"; exit 1; }
echo "claude $(claude --version | head -1); codex $(codex --version); copilot $(copilot --version | head -1)"
step claude plugin marketplace add "$REPO"
for p in $CLAUDE_PLUGINS; do step claude plugin install "$p@techne"; done
step codex plugin marketplace add "$REPO"
for p in $PORTABLE; do step codex plugin add "$p@techne"; done
step copilot plugin marketplace add "$REPO"
for p in $PORTABLE; do step copilot plugin install "$p@techne"; done
exit $failed
'
