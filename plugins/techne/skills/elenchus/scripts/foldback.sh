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
# ELENCHUS_DRY_RUN=1 runs everything but the writes to GitHub, and keeps the window.
dry="${ELENCHUS_DRY_RUN:-}"
advance() { [ -n "$dry" ] || echo "$1" >"$state/last-fold"; }
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

# The last fold PR, now closed: merged moves the window to its end; closed unmerged keeps it.
if [ -f "$state/pending" ]; then
    read -r pend_until pend_branch <"$state/pending" || true
    if [ -z "${pend_branch:-}" ]; then
        echo "$state/pending is empty or damaged: look at it, then remove it"
        exit 1
    fi
    pend_state="$(gh pr view "$pend_branch" -R "$gh_repo" --json state --jq .state)" || {
        echo "could not read the state of the last fold PR ($pend_branch); pending kept"
        exit 1
    }
    if [ "$pend_state" = MERGED ]; then
        advance "$pend_until"
        since="$pend_until"
    fi
    [ -n "$dry" ] || rm -f -- "${state:?}/pending"
fi
find "${state:?}" -maxdepth 1 \( -name 'catalog-*.md' -o -name 'plan-*.json' \) -mtime +14 -delete

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
    # Any issue with this title, open or closed, means the class was escalated once already.
    have="$(gh issue list -R "$gh_repo" --state all --limit 200 --search "\"$title\" in:title" \
        --json title --jq "[.[] | select(.title == \"$title\")] | length")"
    if [ "$have" = 0 ] && [ -n "$dry" ]; then
        echo "dry run: would open issue '$title'"
    elif [ "$have" = 0 ]; then
        gh issue create -R "$gh_repo" --label enhancement --title "$title" --body \
"Reviewers found class \`$cls\` in three or more PRs this week (elenchus ledger, $day). Per the escalation ladder, it gets a mechanical check (a lint rule, a test or a hook) so no review round is spent on it again. When the check lands and this issue is closed as completed, the next fold marks the class retired in the catalog."
    fi
done

# Mechanical-check issues the owner closed as completed inside this window (REST search:
# gh issue list has no stateReason before gh 2.5x).
retired="$(gh api -X GET search/issues --paginate \
    -f q="repo:$gh_repo is:issue is:closed reason:completed author:$owner \"Mechanical check:\" in:title" \
    --jq '.items[] | [.title, .closed_at] | @tsv' |
    python3 -c '
import json, sys
since, until = sys.argv[1], sys.argv[2]
out = [t.split(": ", 1)[1] for t, closed in (l.rstrip("\n").split("\t") for l in sys.stdin if l.strip())
       if t.startswith("Mechanical check: ") and since <= closed < until]
print(json.dumps(out))
' "$since" "$until")"
records="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["records"])' "$plan")"
if [ "$records" = 0 ] && [ "$retired" = "[]" ]; then
    echo "no new findings or retirements since $since"
    advance "$until"
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
cleanup() {
    rm -rf -- "${state:?}/curate-${day:?}"
    git -C "$repo" worktree remove --force "${wt:?}" 2>/dev/null || true
    # The pushed branch lives on GitHub for its PR; the local copy is not kept.
    git -C "$repo" branch -D "${branch:?}" >/dev/null 2>&1 || true
}
trap cleanup EXIT
public="$(gh repo list "$owner" --visibility public --limit 300 --json name --jq '[.[].name] | join(", ")')"
# The curator reads a copy of the plan in a folder of its own, never the ledger or window.
cur="$state/curate-$day"
mkdir -p "$cur"
cp "$plan" "$cur/plan.json"
prompt="$(sed -e "s|{plan}|$cur/plan.json|" -e "s|{public}|$public|" "$here/curate.md")"
# Restricted: no user settings, hooks, plugins or MCP servers; file tools stay in the worktree
# and the plan's folder; no Bash, so nothing the session writes can run.
(cd "$wt" && timeout 1800 claude -p "$prompt" --model claude-opus-5-5 --restricted \
    --tools "Read,Edit,Glob,Grep" --strict-mcp-config --add-dir "$cur" \
    --permission-mode acceptEdits --max-turns 60 --no-session-persistence \
    --output-format text) || {
    echo "curation session failed or timed out"
    exit 1
}
changed="$(git -C "$wt" status --porcelain --ignored)"
if [ -z "$changed" ]; then
    echo "curation changed nothing"
    advance "$until"
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
if [ -n "$dry" ]; then
    echo "dry run: would commit, push and open a PR with:"
    git -C "$wt" diff --stat
    exit 0
fi
# check_private_names.py knows only the owner's private repos; any repo in the plan that is
# not public (an org's or a teammate's) must not appear in the added lines either.
words="$(git -C "$repo" rev-parse --git-common-dir)/info/private-words"
leaked="$(git -C "$wt" diff -U0 -- "$catalog" |
    python3 "$here/ledger.py" scan --plan "$plan" --public "$public" --private-words "$words")" || true
if [ -n "$leaked" ]; then
    echo "the catalog edit names a repo that is not public; nothing pushed: $leaked"
    exit 1
fi
git -C "$wt" add "$catalog"
git -C "$wt" commit -q -m "docs(elenchus): fold the findings ledger into the catalog ($day)"
git -C "$wt" push -q -u origin "$branch"
gh pr create -R "$gh_repo" --head "$branch" --base main --label documentation \
    --assignee "$owner" --title "docs(elenchus): catalog fold-back, $day" --body \
"The daily fold of the elenchus findings ledger from $since to $until: incidents for catalogued classes, new classes seen in two or more PRs, and classes whose mechanical check landed. Review the catalog diff before merging; the next fold waits until this PR is merged or closed."
# The window moves only when this PR merges (checked at the next run), so findings in a
# fold PR closed unmerged are folded again.
[ -f "$state/last-fold" ] || echo "$since" >"$state/last-fold"
printf '%s %s\n' "$until" "$branch" >"$state/pending"
echo "== $(date -Is) fold-back done"
