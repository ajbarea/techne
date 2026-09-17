#!/usr/bin/env bash
# techne dev-runner — wraps `make <target>` invocations and writes archives
# under logs/dev-<UTC-timestamp>-<target>.log with a SUMMARY block at the tail
# that techne:audit diffs against the terminal exit code.
#
# Usage:
#   ./scripts/dev-runner.sh <make-target>
#
# Drop-in: copy this file into your repo's scripts/ and invoke it from the
# shell. Never call it from a Makefile recipe: it runs `make` itself, so the
# recipe would recurse. The script does not edit anything outside logs/.
#
# Archive lines use the same shape as a Python scripts/dev.py runner, so
# techne:audit reads either:
#   [<local ISO-8601 time>] [OUT  ] [<target>] <merged stdout+stderr line>
#   [<local ISO-8601 time>] [ERROR] [<target>] exit <rc>
# The terminal still sees the untagged output.

set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <make-target>" >&2
  exit 64
fi

# Portable nanosecond timestamp. Falls back gracefully:
#   - python3 (works on macOS + Linux + WSL)
#   - GNU date +%s%N (Linux)
#   - Second precision via date +%s padded to ns (universal fallback)
get_ns() {
  if command -v python3 >/dev/null 2>&1; then
    python3 -c 'import time; print(time.time_ns())'
  elif date +%s%N 2>/dev/null | grep -qE '^[0-9]+$'; then
    date +%s%N
  else
    printf '%s000000000\n' "$(date +%s)"
  fi
}

# Sets STAMP rather than printing it, so tagging a line forks nothing on bash 5.
stamp() {
  if [[ -n "${EPOCHREALTIME:-}" ]]; then
    local now="${EPOCHREALTIME/,/.}"
    local frac="${now#*.}"
    printf -v STAMP '%(%Y-%m-%dT%H:%M:%S)T.%s' "${now%.*}" "${frac:0:3}"
  else
    STAMP="$(date +%Y-%m-%dT%H:%M:%S)"
  fi
}

TARGET="$1"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_DIR="logs"
ARCHIVE="${LOG_DIR}/dev-${TS}-${TARGET}.log"
LATEST="${LOG_DIR}/dev-latest.log"

mkdir -p "$LOG_DIR"

# Truncate the stable-name pointer before each run; archives are append-only.
: > "$LATEST"

START_NS="$(get_ns)"

exec 3>>"$ARCHIVE" 4>>"$LATEST"

# Echo each line untagged for the user, and tagged into both logs as it arrives.
set +e
make "$TARGET" 2>&1 | while IFS= read -r line || [[ -n "$line" ]]; do
  printf '%s\n' "$line"
  stamp
  printf -v tagged '[%s] [OUT  ] [%s] %s' "$STAMP" "$TARGET" "$line"
  printf '%s\n' "$tagged" >&3
  printf '%s\n' "$tagged" >&4
done
RC=${PIPESTATUS[0]}
set -e

END_NS="$(get_ns)"
ELAPSED_SEC="$(awk -v s="$START_NS" -v e="$END_NS" 'BEGIN { printf "%.2f", (e - s) / 1e9 }')"

STATUS="PASS"
STEPS_FAILED=0
if [[ $RC -ne 0 ]]; then
  STATUS="FAIL"
  STEPS_FAILED=1
  stamp
  printf '[%s] [ERROR] [%s] exit %d\n' "$STAMP" "$TARGET" "$RC" | tee -a "$ARCHIVE" "$LATEST" >/dev/null
fi

{
  echo ""
  echo "=============================================================================="
  echo "SUMMARY"
  echo "=============================================================================="
  echo "total elapsed : ${ELAPSED_SEC}s"
  echo "steps run     : 1"
  echo "steps failed  : ${STEPS_FAILED}"
  echo "overall rc    : ${RC}"
  echo ""
  echo "per-step:"
  printf "  %s  rc=%d  %ss  %s\n" "$STATUS" "$RC" "$ELAPSED_SEC" "$TARGET"
  echo "=============================================================================="
} | tee -a "$ARCHIVE" "$LATEST"

exec 3>&- 4>&-
exit "$RC"
