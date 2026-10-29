#!/bin/bash
# The daily elenchus fold-back: turn the findings ledger into one catalog PR to techne, and
# open a "Mechanical check: <class>" issue for each catalogued class found in three or more
# PRs this week. Usage: foldback.sh <techne clone>. Run by a systemd user timer
# (docs/skills/elenchus.md). The curation session only reads and edits; commits, pushes, the
# PR and the issues happen here, and nothing is pushed unless the catalog is the only file
# changed, its tests pass and the private-name scan ran and found nothing.
set -euo pipefail

repo="${1:?usage: foldback.sh <techne clone>}"
gh_repo="${ELENCHUS_GH_REPO:-ajbarea/techne}"
owner="${gh_repo%%/*}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
state="${XDG_STATE_HOME:-$HOME/.local/state}/elenchus"
mkdir -p "$state"
log="$state/foldback.log"
if [ -f "$log" ] && [ "$(stat -c %s "$log")" -gt 1048576 ]; then
    mv -f "$log" "$log.1"
fi
exec >>"$log" 2>&1
exec 9>"$state/foldback.lock"
flock -n 9 || { echo "== $(date -Is) another fold-back is running: stop"; exit 0; }
echo "== $(date -Is) fold-back starts"

day="$(date +%F)"
branch="chore/catalog-fold-$day"
wt="$repo/.claude/worktrees/catalog-fold-$day"
catalog="plugins/techne/skills/elenchus/references/bug-classes.md"
since="$(cat "$state/last-fold" 2>/dev/null || date -u -d '1 day ago' -Is)"
until="$(date -u -Is)"

# An open fold PR holds the window: the next fold waits for it, so no finding is lost to a
# PR closed unmerged and no two fold PRs conflict.
open_prs="$(gh pr list -R "$gh_repo" --state open --author "@me" --limit 200 --json headRefName \
    --jq '[.[] | select(.headRefName | startswith("chore/catalog-fold-"))] | length')"
if [ "$open_prs" != 0 ]; then
    echo "a catalog fold-back PR is still open; the window stays at $since"
    exit 0
fi

git -C "$repo" fetch -q origin
if [ -d "$wt" ] || git -C "$repo" rev-parse -q --verify "refs/heads/$branch" >/dev/null; then
    echo "$wt or branch $branch exists from an earlier run today: look at it, then remove both"
    exit 1
fi
current="$state/catalog-$day.md"
git -C "$repo" show "origin/main:$catalog" >"$current"
plan="$state/plan-$day.json"
python3 "$here/ledger.py" fold --catalog "$current" --since "$since" --until "$until" >"$plan"

# Catalogued, unretired classes found in three or more PRs this week: one issue each.
slugs="$(python3 -c '
import json, re, sys
for cls, v in json.load(open(sys.argv[1]))["ladder"].items():
    if v["rung"] == "mechanical" and re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", cls):
        print(cls)
' "$plan")"
for cls in $slugs; do
    title="Mechanical check: $cls"
    have="$(gh issue list -R "$gh_repo" --state open --limit 200 --search "\"$title\" in:title" \
        --json title --jq "[.[] | select(.title == \"$title\")] | length")"
    if [ "$have" = 0 ]; then
        gh issue create -R "$gh_repo" --label enhancement --title "$title" --body \
"Reviewers found class \`$cls\` in three or more PRs this week (elenchus ledger, $day). Per the escalation ladder, it gets a mechanical check (a lint rule, a test or a hook) so no review round is spent on it again. When the check lands and this issue is closed as completed, the next fold marks the class retired in the catalog."
    fi
done

# Mechanical-check issues the owner closed as completed inside this window.
retired="$(gh issue list -R "$gh_repo" --state closed --author "$owner" --limit 200 \
    --search '"Mechanical check:" in:title' --json title,stateReason,closedAt |
    python3 -c '
import json, sys
since = sys.argv[1]
out = [i["title"].split(": ", 1)[1] for i in json.load(sys.stdin)
       if i.get("stateReason") == "COMPLETED" and i.get("closedAt", "") >= since
       and i["title"].startswith("Mechanical check: ")]
print(json.dumps(out))
' "$since")"
records="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["records"])' "$plan")"
if [ "$records" = 0 ] && [ "$retired" = "[]" ]; then
    echo "no new findings or retirements since $since"
    echo "$until" >"$state/last-fold"
    exit 0
fi
python3 - "$plan" "$retired" <<'PY'
import json, sys
p = json.load(open(sys.argv[1]))
# A class found again after its check closed is not retired yet: the check did not hold.
p["retired"] = [c for c in json.loads(sys.argv[2]) if c not in p["retired_but_found"]]
json.dump(p, open(sys.argv[1], "w"), indent=1)
PY

git -C "$repo" worktree add -q "$wt" -b "$branch" origin/main
pushed=0
cleanup() {
    git -C "$repo" worktree remove --force "${wt:?}" 2>/dev/null || true
    [ "$pushed" = 1 ] || git -C "$repo" branch -D "${branch:?}" >/dev/null 2>&1 || true
}
trap cleanup EXIT
public="$(gh repo list "$owner" --visibility public --limit 300 --json name --jq '[.[].name] | join(", ")')"
prompt="$(sed -e "s|{plan}|$plan|" -e "s|{public}|$public|" "$here/curate.md")"
# Restricted: no user settings, hooks, plugins or MCP servers; file tools stay in the worktree
# and the plan's folder; no Bash, so nothing the session writes can run.
(cd "$wt" && timeout 1800 claude -p "$prompt" --model claude-opus-5-5 --restricted \
    --tools "Read,Edit,Glob,Grep" --strict-mcp-config --add-dir "$state" \
    --permission-mode acceptEdits --max-turns 60 --no-session-persistence \
    --output-format text) || {
    echo "curation session failed or timed out"
    exit 1
}
changed="$(git -C "$wt" status --porcelain)"
if [ -z "$changed" ]; then
    echo "curation changed nothing"
    echo "$until" >"$state/last-fold"
    exit 0
fi
if [ "$changed" != " M $catalog" ]; then
    echo "curation changed more than the catalog; nothing pushed:"
    echo "$changed"
    exit 1
fi
(cd "$wt" && uv sync -q && uv run pytest -q tests/test_bug_classes.py) || {
    echo "catalog tests failed; nothing pushed"
    exit 1
}
# The scan skips (exit 0, SKIP on stderr) when gh cannot list private repos: unattended,
# a skipped scan is a failed one.
scan="$(cd "$wt" && uv run python scripts/check_private_names.py 2>&1)" || {
    echo "private-name scan failed; nothing pushed"
    echo "$scan"
    exit 1
}
if grep -q '^SKIP' <<<"$scan"; then
    echo "private-name scan skipped; nothing pushed: $scan"
    exit 1
fi
git -C "$wt" add "$catalog"
git -C "$wt" commit -q -m "docs(elenchus): fold the findings ledger into the catalog ($day)"
git -C "$wt" push -q -u origin "$branch"
pushed=1
gh pr create -R "$gh_repo" --head "$branch" --base main --label documentation \
    --assignee "$owner" --title "docs(elenchus): catalog fold-back, $day" --body \
"The daily fold of the elenchus findings ledger from $since to $until: incidents for catalogued classes, new classes seen in two or more PRs, and classes whose mechanical check landed. Review the catalog diff before merging; the next fold waits until this PR is merged or closed."
echo "$until" >"$state/last-fold"
echo "== $(date -Is) fold-back done"
