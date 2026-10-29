#!/bin/bash
# The daily elenchus fold-back: turn the findings ledger into one catalog PR to techne, and
# open a "Mechanical check: <class>" issue for each class found in three or more PRs this week.
# Usage: foldback.sh <techne clone>. Run by a systemd user timer (docs/skills/elenchus.md).
# Commits, pushes, the PR and the issues happen here, never in the curation session, which
# only edits the catalog. Nothing is pushed unless the catalog tests and the guards pass.
set -euo pipefail

repo="${1:?usage: foldback.sh <techne clone>}"
gh_repo="${ELENCHUS_GH_REPO:-ajbarea/techne}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
state="${XDG_STATE_HOME:-$HOME/.local/state}/elenchus"
mkdir -p "$state"
log="$state/foldback.log"
exec >>"$log" 2>&1
echo "== $(date -Is) fold-back starts"

day="$(date +%F)"
branch="chore/catalog-fold-$day"
wt="$repo/.claude/worktrees/catalog-fold-$day"
catalog="plugins/techne/skills/elenchus/references/bug-classes.md"
since="$(cat "$state/last-fold" 2>/dev/null || date -u -d '1 day ago' -Is)"
now="$(date -u -Is)"

git -C "$repo" fetch -q origin
if [ -d "$wt" ]; then
    echo "a fold worktree for $day exists ($wt); a run is in progress or failed: stop"
    exit 1
fi
plan="$state/plan-$day.json"
python3 "$here/ledger.py" fold --catalog <(git -C "$repo" show "origin/main:$catalog") \
    --since "$since" >"$plan"

# Classes found in three or more PRs this week: one open issue each, never a duplicate.
python3 - "$plan" <<'PY' | while IFS= read -r cls; do
import json, sys
plan = json.load(open(sys.argv[1]))
for cls, v in plan["ladder"].items():
    if v["rung"] == "mechanical":
        print(cls)
PY
    title="Mechanical check: $cls"
    if [ -z "$(gh issue list -R "$gh_repo" --state open --search "\"$title\" in:title" --json number --jq '.[].number')" ]; then
        gh issue create -R "$gh_repo" --label enhancement --title "$title" --body \
"Reviewers found class \`$cls\` in three or more PRs this week (elenchus ledger, $day). Per the escalation ladder, it gets a mechanical check (a lint rule, a test or a hook) so no review round is spent on it again. When the check lands, the next fold marks the class retired in the catalog."
    fi
done

retired="$(gh issue list -R "$gh_repo" --state closed --search '"Mechanical check:" in:title' \
    --json title --jq '[.[].title | sub("^Mechanical check: "; "")]')"
records="$(python3 -c 'import json,sys; p=json.load(open(sys.argv[1])); print(p["records"])' "$plan")"
if [ "$records" = 0 ] && [ "$retired" = "[]" ]; then
    echo "no new findings since $since"
    echo "$now" >"$state/last-fold"
    exit 0
fi
python3 - "$plan" "$retired" <<'PY'
import json, sys
p = json.load(open(sys.argv[1]))
p["retired"] = json.loads(sys.argv[2])
json.dump(p, open(sys.argv[1], "w"), indent=1)
PY

git -C "$repo" worktree add -q "$wt" -b "$branch" origin/main
cleanup() { git -C "$repo" worktree remove --force "${wt:?}" 2>/dev/null || true; }
trap cleanup EXIT
public="$(gh repo list "${gh_repo%%/*}" --visibility public --limit 300 --json name --jq '[.[].name] | join(", ")')"
prompt="$(sed -e "s|{plan}|$plan|" -e "s|{public}|$public|" "$here/curate.md")"
(cd "$wt" && uv sync -q && claude -p "$prompt" --model claude-opus-5-5 \
    --allowedTools "Read Edit Glob Grep Bash(uv run pytest *)" --permission-mode acceptEdits \
    --max-turns 60 --no-session-persistence --output-format text) || {
    echo "curation session failed"
    exit 1
}
if git -C "$wt" diff --quiet; then
    echo "curation changed nothing"
    echo "$now" >"$state/last-fold"
    exit 0
fi
(cd "$wt" && uv run pytest -q tests/test_bug_classes.py && make guards) || {
    echo "catalog tests or guards failed; nothing pushed ($wt kept for a look)"
    trap - EXIT
    exit 1
}
git -C "$wt" add "$catalog"
git -C "$wt" commit -q -m "docs(elenchus): fold the findings ledger into the catalog ($day)"
git -C "$wt" push -q -u origin "$branch"
gh pr create -R "$gh_repo" --head "$branch" --base main --label documentation \
    --assignee "${gh_repo%%/*}" --title "docs(elenchus): catalog fold-back, $day" --body \
"The daily fold of the elenchus findings ledger since $since: incidents for catalogued classes, new classes seen in two or more PRs, and retired classes. Plan: \`$plan\` on the machine that ran it. Review the catalog diff before merging."
echo "$now" >"$state/last-fold"
echo "== $(date -Is) fold-back done"
