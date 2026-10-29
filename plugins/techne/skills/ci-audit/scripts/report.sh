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
# OUT is a folder of the report's own: the session may read all of it, and the
# run folder in it is replaced. A symlink anywhere in it could point that at
# another folder (a repo, a worktree), so none is allowed, and the run folder
# is removed only when it carries the mark this script left when it made it.
MARK=.ci-report-run
# A trailing slash would have -L follow a link to the folder it names.
while [[ $out == */ && $out != / ]]; do out=${out%/}; done
[[ -L $out ]] && { err "OUT is a symlink; give a real folder"; exit 2; }
if [[ -e $out ]]; then
  [[ -d $out ]] || { err "OUT is not a folder"; exit 2; }
  extra=$(find "$out" -mindepth 1 -maxdepth 1 ! -name run ! -name report.json ! -name report.md \
    ! -name claude.json ! -name claude.err -printf '%f ' 2>/dev/null)
  [[ -z $extra ]] || { err "OUT holds other files ($extra); give a new or empty folder"; exit 2; }
  links=$(find "$out" -mindepth 1 -maxdepth 1 -type l -printf '%f ' 2>/dev/null)
  [[ -z $links ]] || { err "OUT holds symlinks ($links); give a new or empty folder"; exit 2; }
  if [[ -e $out/run && ! -e $out/run/$MARK ]]; then
    err "OUT/run was not made by report.sh; give a new or empty folder"
    exit 2
  fi
fi
mkdir -p -- "$out"
out=$(cd -- "$out" && pwd -P)
raw=$out/run
if (( $# == 5 )); then
  from=$(cd -- "$5" 2>/dev/null && pwd -P) || { err "no recorded run at $5"; exit 2; }
  [[ $from != "$raw" && $from != "$raw"/* && $from != "$out" && $out != "$from"/* ]] ||
    { err "--from and OUT must not hold each other"; exit 2; }
fi
if [[ -e $raw ]]; then
  [[ -d $raw && ! -L $raw && -e $raw/$MARK ]] || { err "refusing to replace $raw"; exit 2; }
  rm -rf -- "${raw:?}"
fi
# Marked first, so a fetch that fails partway leaves a folder the next run may replace.
mkdir -- "$raw"
: >"$raw/$MARK"
if (( $# == 5 )); then
  cp -rP -- "$from/." "$raw/"
else
  python3 "$here/ci_report.py" fetch "$repo" "$run" "$raw"
fi
python3 "$here/ci_report.py" facts "$raw" >"$raw/facts.json"

# Restricted and safe mode: no settings files, CLAUDE.md, skills, plugins or hooks;
# no MCP servers; read-only tools, with Read allowed only under OUT and the skill.
prompt="Follow $skill/references/report-mode.md for the run directory $raw (classification rules: $skill/SKILL.md). Reply with the report JSON alone."
(
  cd -- "$out"
  claude -p "$prompt" \
    --model "${CI_REPORT_MODEL:-opus}" \
    --restricted --safe-mode --strict-mcp-config \
    --tools Read,Grep,Glob \
    --allowedTools "Read(/$out/**)" "Read(/$skill/**)" \
    --permission-mode dontAsk \
    --add-dir "$skill" \
    --json-schema "$(python3 "$here/ci_report.py" schema)" \
    --output-format json --no-session-persistence --max-turns 25
) >"$out/claude.json" 2>"$out/claude.err" || { err "the headless session failed: $(tail -3 "$out/claude.err")"; exit 1; }
jq -e '.structured_output // (.result | fromjson? // empty)' "$out/claude.json" >"$out/report.json" ||
  { err "no report in the session's reply ($out/claude.json)"; exit 1; }
python3 "$here/ci_report.py" check "$out/report.json" "$raw/facts.json" ||
  { err "the report breaks the schema or contradicts the run's facts"; exit 1; }
python3 "$here/ci_report.py" render "$out/report.json" >"$out/report.md"
printf '%s\n' "$out/report.json"
