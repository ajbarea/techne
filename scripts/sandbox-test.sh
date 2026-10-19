#!/usr/bin/env bash
# make test-sandboxed: the unit tests inside Anthropic's sandbox-runtime (srt).
# Usage: sandbox-test.sh <private-temp-dir>   (run from the repo root, via the Makefile)
set -euo pipefail

[ "$(uname -s)" = Linux ] || { echo "test-sandboxed is Linux only (srt uses bubblewrap here)"; exit 1; }
[ "$#" -eq 1 ] || { echo "usage: $0 <private-temp-dir>"; exit 2; }
tmp=$1
command -v npm >/dev/null || { echo "npm not on PATH (comes with Node)"; exit 1; }
srt=scripts/srt/node_modules/.bin/srt
# srt names any missing system package (bubblewrap, socat, ripgrep) itself.
[ -x "$srt" ] || npm ci --ignore-scripts --prefix scripts/srt

# A private temp folder: ours, mode 700, never a symlink.
if [ -L "$tmp" ] || { [ -e "$tmp" ] && [ ! -O "$tmp" ]; }; then
    echo "refusing $tmp: a symlink or not owned by you"
    exit 1
fi
install -d -m 700 "$tmp"
[ -O "$tmp" ] || { echo "refusing $tmp: not owned by you"; exit 1; }

# Only the sandbox's own uv cache and venv, warmed with the network open and reused inside.
export UV_CACHE_DIR=$tmp/uv-cache UV_PROJECT_ENVIRONMENT=$tmp/venv UV_LINK_MODE=copy
make --no-print-directory sandbox-warm

sed "s|@SANDBOX_TMP@|$tmp|g" scripts/sandbox-test.json >"$tmp/settings.json"

# A cleaned environment: tokens (OPENALEX_API_KEY, S2_API_KEY, CLAUDE_CODE_*) never reach the tests.
allow=(PATH HOME USER LANG TERM SHELL)
while IFS= read -r name; do
    case $name in LC_* | TECHNE_NO_*) allow+=("$name") ;; esac
done < <(compgen -e)
pass=()
for name in "${allow[@]}"; do
    [ -n "${!name+x}" ] && pass+=("$name=${!name}")
done
UV_OFFLINE=1 "$srt" --settings "$tmp/settings.json" -- \
    env -i "${pass[@]}" TMPDIR="$tmp" TMUX_TMPDIR="$tmp" UV_CACHE_DIR="$UV_CACHE_DIR" \
    UV_PROJECT_ENVIRONMENT="$UV_PROJECT_ENVIRONMENT" UV_LINK_MODE=copy UV_OFFLINE=1 \
    make --no-print-directory test-unit
