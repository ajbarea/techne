#!/usr/bin/env bash
# report.sh OWNER/REPO RUN_ID OUT [--from DIR]: ci-audit's report mode, unattended.
# Records the run with read-only gh api calls (or copies a recorded one from DIR),
# computes its facts, has a headless Claude Code session judge them with read-only
# tools confined to OUT, and writes OUT/report.json and OUT/report.md. Prints the
# report's path; exits non-zero when no valid report came back.
# CI_REPORT_MODEL picks the model (default opus).
set -euo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
skill=$(dirname "$here")
err() { printf 'error: %s\n' "$*" >&2; }
[[ $# == 3 || ($# == 5 && $4 == --from) ]] || { err "usage: report.sh OWNER/REPO RUN_ID OUT [--from DIR]"; exit 2; }
repo=$1 run=$2 out=$3
[[ $repo =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ && $run =~ ^[0-9]+$ ]] || { err "a repo is OWNER/NAME and a run id is a number"; exit 2; }
mkdir -p -- "$out"
out=$(cd -- "$out" && pwd)
raw=$out/run
if (( $# == 5 )); then
  rm -rf -- "${raw:?}"
  cp -r -- "$5" "$raw"
else
  python3 "$here/ci_report.py" fetch "$repo" "$run" "$raw"
fi
python3 "$here/ci_report.py" facts "$raw" >"$raw/facts.json"

# Read-only tools, allowed only under OUT; no user settings, hooks, plugins or MCP servers.
prompt="Follow $skill/references/report-mode.md for the run directory $raw (classification rules: $skill/SKILL.md). Reply with the report JSON alone."
(
  cd -- "$out"
  claude -p "$prompt" \
    --model "${CI_REPORT_MODEL:-opus}" \
    --setting-sources "" --strict-mcp-config \
    --tools Read,Grep,Glob \
    --allowedTools "Read(/$out/**)" "Read(/$skill/**)" "Grep(/$out/**)" "Glob(/$out/**)" \
    --permission-mode dontAsk \
    --add-dir "$skill" \
    --json-schema "$(python3 "$here/ci_report.py" schema)" \
    --output-format json --no-session-persistence --max-turns 25
) >"$out/claude.json" 2>"$out/claude.err" || { err "the headless session failed: $(tail -3 "$out/claude.err")"; exit 1; }
jq -e '.structured_output // (.result | fromjson? // empty)' "$out/claude.json" >"$out/report.json" ||
  { err "no report in the session's reply ($out/claude.json)"; exit 1; }
python3 "$here/ci_report.py" check "$out/report.json" || { err "the report breaks the schema"; exit 1; }
python3 "$here/ci_report.py" render "$out/report.json" >"$out/report.md"
printf '%s\n' "$out/report.json"
