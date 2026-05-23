---
name: sisters
description: Cross-repo drift audit across linked repos listed in `~/.claude/techne.toml` (configurable per-user). Read-only inspection of CI action pins, toolchain pins in pyproject.toml, skill-context structural parity, GitHub merge settings, open PRs, and branch hygiene. Triggers on phrases like "audit the sisters", "are the sisters in sync", "check cross-repo drift", or when multiple sister repos are mentioned together for a consistency check.
disable-model-invocation: false
allowed-tools: Bash(gh api repos/*) Bash(gh pr list*) Bash(gh auth status) Bash(git fetch *) Bash(git for-each-ref *) Bash(git rev-list *) Bash(git branch *) Bash(grep *) Bash(awk *) Bash(sed *) Bash(sort *) Bash(uniq *) Bash(wc *) Bash(ls *) Bash(python3 *) Bash(cd *) Glob Grep Read
---

# Sisters Audit

Audit the active sister repos for cross-repo drift. Report every finding, grouped by category. Leave fixing to follow-up work or the developer — this skill observes, it does not edit.

## Config (load first)

Active sister list, workspace root, and GitHub user are read from `~/.claude/techne.toml` at runtime. Run this preamble before any audit checks below — it sets `$SISTERS`, `$WORKSPACE`, and `$GITHUB_USER`:

```
eval "$(python3 - <<'PY'
import tomllib, os, shlex
with open(os.path.expanduser('~/.claude/techne.toml'), 'rb') as f:
    d = tomllib.load(f)
sisters = ' '.join(s['name'] for s in d['sisters'] if s.get('status', 'active') == 'active')
ws = d['workspace_root']  # required; fails loudly with KeyError on misconfig
gu = d['github_user']     # required; fails loudly with KeyError on misconfig
print(f"SISTERS={shlex.quote(sisters)}")
print(f"WORKSPACE={shlex.quote(ws)}")
print(f"GITHUB_USER={shlex.quote(gu)}")
PY
)"
```

If `~/.claude/techne.toml` is missing or yields zero active sisters, stop and tell the user — don't guess. Each sister's canonical local path is `$WORKSPACE/<name>` and its GitHub slug is `$GITHUB_USER/<name>`.

## What to check

### 1. Action-pin drift

For every `.github/workflows/*.yml` across the active sisters, extract `uses: <actor>/<action>@<version>` pins.

```
for repo in $SISTERS; do
  grep -hE '^\s*uses:' $WORKSPACE/$repo/.github/workflows/*.yml 2>/dev/null \
    | sed -E 's/^\s*uses:\s*//; s/\s*$//' \
    | awk -v r="$repo" '{print r "\t" $0}'
done | sort
```

Compute drift: any action (the `actor/action` part) pinned to *different* versions across repos. Report the action, each repo's pin, and which is newest. The newest pin in the set is the recommended target — unless the user has said otherwise.

Don't flag per-action when all repos pin the same version, even if that version is behind upstream — that's a separate "upgrade" question, not drift. The skill's job is to catch *inconsistency*, not to evaluate absolute freshness.

### 2. Skill-context structural parity

Each repo has `.claude/skill-context.md`. Required top-level sections across all sisters:

- `## repo`
- `## audit`
- `## ci_audit`
- `## slop_ground_truth`
- `## scan_scope`
- `## docs_site`

Verify by grep:

```
for repo in $SISTERS; do
  echo "--- $repo ---"
  grep -E '^## ' $WORKSPACE/$repo/.claude/skill-context.md
done
```

Report any repo missing a required section, and any repo that has sections the others lack (not necessarily bad — could be a legitimate per-repo addition — but worth surfacing for review).

### 3. GitHub merge-setting drift

Expected uniform settings (this is the canonical pin — if you're unsure, re-run this audit):

- `allow_squash_merge: true`
- `allow_merge_commit: false`
- `allow_rebase_merge: false`
- `delete_branch_on_merge: true`
- `allow_auto_merge: true` — needed so `gh pr merge --auto` works; without it every PR has to be hand-merged after CI flips green

```
for repo in $SISTERS; do
  echo "--- $repo ---"
  gh api "repos/$GITHUB_USER/$repo" --jq '{sq:.allow_squash_merge, mc:.allow_merge_commit, rb:.allow_rebase_merge, del:.delete_branch_on_merge, am:.allow_auto_merge}'
done
```

Report any repo that drifts from the canonical expectation.

### 4. Open PRs rollup

```
for repo in $SISTERS; do
  gh pr list --repo "$GITHUB_USER/$repo" --state open --json number,title,headRefName,createdAt,isDraft,mergeable \
    --jq ".[] | [\"$repo\", (.number|tostring), .title, .headRefName, .mergeable, .createdAt] | @tsv"
done
```

For each PR, note age (`createdAt` → days-ago), mergeability, and whether the check rollup is clean. Flag any PR open longer than 14 days — that's a rot signal, not necessarily a bug.

Don't pull full check details for every PR — that's the job of `techne:ci-audit`. Link to the PR URL and let the user drill down.

### 5. Stale local branches

For each repo, list branches that are **ahead** of `origin/main` and **not** the currently checked-out branch or `main` itself:

```
for repo in $SISTERS; do
  echo "--- $repo ---"
  (cd $WORKSPACE/$repo && git fetch --quiet origin && \
    git for-each-ref --format='%(refname:short) %(upstream:track)' refs/heads/ \
    | grep -v '^main ' \
    | grep -v '\[gone\]' \
    | awk '$2 ~ /ahead/ { print $0 }')
done
```

Report each stale branch: repo, branch name, ahead-by count. Stale branches are work-in-progress that didn't ship — not automatically bad, but worth knowing about before a session.

### 6. Local `main` divergence from `origin/main`

Fast check: is any repo's local `main` out of sync with `origin/main`?

```
for repo in $SISTERS; do
  cd $WORKSPACE/$repo
  git fetch --quiet origin
  behind=$(git rev-list --count main..origin/main 2>/dev/null)
  ahead=$(git rev-list --count origin/main..main 2>/dev/null)
  echo "$repo: ahead=$ahead behind=$behind"
done
```

Report any non-zero ahead/behind. Behind = pull to catch up. Ahead = unpushed commits, investigate before continuing work.

### 7. Toolchain pin drift in `pyproject.toml`

Only inspect the *root* `pyproject.toml` of each repo — that's where the shared toolchain decisions live. Do not descend into workspace members (e.g., `<repo>/agents/*/pyproject.toml`); those are package-level, not toolchain-level, and would generate noise.

Extract four pins per repo:

- `requires-python` — the Python version envelope the project accepts.
- `[tool.ruff] target-version` — which Python features ruff assumes when linting / autofixing.
- Dev-dep specifier for `ruff` (in `[project.optional-dependencies.dev]` or `[dependency-groups.dev]`).
- Dev-dep specifier for `ty`.
- Dev-dep specifier for `pytest`.

```
for repo in $SISTERS; do
  f=$WORKSPACE/$repo/pyproject.toml
  echo "--- $repo ---"
  grep -E '^requires-python\s*=' "$f"
  awk '/^\[tool\.ruff\]$/{flag=1; next} /^\[/{flag=0} flag && /^target-version/' "$f"
  grep -hE '"(ruff|ty|pytest)[">=<~!]' "$f" | sort -u
done
```

Compute drift the same way as check 1 (action pins):

- **`requires-python` drift** — differing lower bounds or upper caps across the sisters is drift. A repo with `>=3.9` while the others are `>=3.12,<3.14` is running on a looser envelope than its siblings and may regress on features the others use freely.
- **`target-version` drift** — this must be consistent with `requires-python`'s lower bound. Flag both cross-repo drift and intra-repo mismatch (e.g., `requires-python = ">=3.12"` but `target-version = "py39"`).
- **`ruff` / `ty` / `pytest` specifier drift** — any tool with different minimums across repos (`ruff>=0.8` vs `ruff>=0.9`) or that is unbounded in one repo (`"ruff"`) while bounded in another (`"ruff>=0.9"`) is drift.

Unlike action pins, the newest pin is **not** automatically the target. `requires-python` lower bounds often encode a support commitment that's deliberate per repo — raising a repo's lower bound can break users on older Python. Report the drift, then either:

- **Tooling pins (ruff / ty / pytest)** → the newest pin is the default recommendation; these have no support-contract cost.
- **`requires-python` / `target-version`** → surface the drift but do not recommend; ask the user which envelope they want to converge on.

### 8. Branch protection on `main`

Every sister should have branch protection on `main` with at least one required status check, no force-pushes, and no branch deletions. Sisters drifted past this once already (ldqis 2026-05-23, found by the audit and fixed inline). Don't require a specific number of contexts — that varies by repo's CI shape — just check that at least one is wired and that force-push/deletion are blocked.

```
for repo in $SISTERS; do
  raw=$(gh api "repos/$GITHUB_USER/$repo/branches/main/protection" 2>&1)
  if echo "$raw" | grep -q '"Branch not protected"'; then
    echo "$repo: main NOT protected -> enable protection with required CI checks"
    continue
  fi
  printf '%s' "$raw" | python3 -c '
import json, sys
d = json.load(sys.stdin)
ctx = (d.get("required_status_checks") or {}).get("contexts") or []
fp = (d.get("allow_force_pushes") or {}).get("enabled", False)
ad = (d.get("allow_deletions") or {}).get("enabled", False)
issues = []
if not ctx: issues.append("no required checks")
if fp: issues.append("force-pushes allowed")
if ad: issues.append("deletions allowed")
status = "drift: " + ", ".join(issues) if issues else f"protected, {len(ctx)} required check(s) ✓"
print(f"'"$repo"': {status}")
'
done
```

Report any sister whose `main` is unprotected, has zero required checks, or has `allow_force_pushes` / `allow_deletions` set. `enforce_admins` stays optional — AJ intentionally leaves admin override on so audit fixes can ship the same session.

### 9. Codecov config presence + bot-comment silencing

Any sister whose CI workflows invoke `codecov/codecov-action` should also carry a `codecov.yml` (or `.codecov.yml`) at the repo root with `comment: false`. Without the config, the bot posts an inline PR comment on every push — pure noise once the patch-coverage status check is visible. Sisters drifted past this once already (ldqis 2026-05-23).

```
for repo in $SISTERS; do
  uses_codecov=0
  if grep -rq 'codecov/codecov-action' $WORKSPACE/$repo/.github/workflows/ 2>/dev/null; then
    uses_codecov=1
  fi
  [ $uses_codecov -eq 0 ] && { echo "$repo: no codecov-action — skip"; continue; }
  cfg=""
  for candidate in codecov.yml .codecov.yml; do
    [ -f "$WORKSPACE/$repo/$candidate" ] && { cfg=$candidate; break; }
  done
  if [ -z "$cfg" ]; then
    echo "$repo: uses codecov-action but has no codecov.yml -> add one (sister convention: comment: false + target auto/2% + informational)"
  elif ! grep -q '^comment:[[:space:]]*false' $WORKSPACE/$repo/$cfg; then
    echo "$repo: $cfg present but missing 'comment: false' -> bot comments will spam PRs"
  else
    echo "$repo: codecov-action + $cfg with comment: false ✓"
  fi
done
```

Report any sister that uses `codecov/codecov-action` but is missing `codecov.yml`, or has the config but doesn't set `comment: false`. Sisters not using codecov-action are silently skipped — this is a conditional check.

### 10. `make clean` log-retention policy

Every sister with a `logs/` directory should implement age-based pruning of `dev-*-*.log` archives instead of wiping `logs/` wholesale (or doing nothing). Canonical threshold: **30 days** (standard hot-tier log retention). The `*-latest.log` active handle must be preserved.

Detection covers both implementation shapes:

- **Python-script-delegated clean** (phalanx-fl, vFL, kourai-khryseai): `LOG_ARCHIVE_MAX_AGE_DAYS = N` constant in `scripts/clean_build.py` or `scripts/dev.py`.
- **Makefile-inline clean** (ldqis): `find logs … -mtime +N -delete` recipe line.

```
for repo in $SISTERS; do
  [ -d "$WORKSPACE/$repo/logs" ] || { echo "$repo: no logs/ dir — skip"; continue; }
  py_thr=$(grep -hE 'LOG_ARCHIVE_MAX_AGE_DAYS[[:space:]]*=[[:space:]]*[0-9]+' \
             $WORKSPACE/$repo/scripts/*.py 2>/dev/null \
           | grep -oE '[0-9]+' | head -1)
  mf_thr=$(grep -hE '\-mtime[[:space:]]+\+[0-9]+' \
             "$WORKSPACE/$repo/Makefile" 2>/dev/null \
           | grep -oE '\+[0-9]+' | tr -d '+' | head -1)
  threshold="${py_thr:-$mf_thr}"
  if [ -z "$threshold" ]; then
    echo "$repo: logs/ present, no age-based prune -> add 30-day prune to clean"
  else
    echo "$repo: ${threshold}-day age-based log prune ✓"
  fi
done
```

Report:

- Any sister with `logs/` but no age-based prune (wholesale-wipe or no-op is drift).
- Any sister whose threshold differs from 30 days (the canonical pin) — flag the value and ask whether to converge.
- Sisters with no `logs/` dir are silently skipped — this is a conditional check.

## Output format

A single block, no preamble (concrete repo names below are illustrative — substitute the actual entries from `$SISTERS`):

```
## Sisters audit — <UTC timestamp>

### Merge settings
- repo-a: squash-only, delete-on-merge, auto-merge ✓
- repo-b: ...
- repo-c: auto-merge disabled → `gh api -X PATCH repos/$GITHUB_USER/repo-c -f allow_auto_merge=true`

### Skill-context parity
- All sisters have required sections. ✓
  (or list drift: "repo-a missing `## docs_site`")

### Action-pin drift
- `astral-sh/setup-uv`: repo-a@v8.1.0, repo-b@v8.1.0, repo-c@v8.0.0 → bump repo-c
- (else: "No drift — all pins consistent across repos.")

### Toolchain pin drift (`pyproject.toml`)
- `ruff`: repo-a unbounded, repo-b `>=0.8`, repo-c `>=0.9` → bump repo-a + repo-b to `>=0.9`
- `requires-python`: repo-a `>=3.11,<3.14`, repo-b `>=3.9`, repo-c `>=3.12,<3.14` → surfaced for user (support-contract drift, no automatic target)
- (else: "No drift — all toolchain pins consistent.")

### Open PRs
- repo-a: 0 open
- repo-b: 1 open (#12, 3d old, mergeable)
- repo-c: 2 open (#14 mergeable; #15 has failing checks → run /techne:ci-audit)

### Stale branches
- repo-c: `feat/experiment-xyz` (ahead 3)
- (else: "Clean.")

### Local main sync
- All sisters: ahead=0 behind=0. ✓

### Branch protection
- All sisters: protected with required checks, no force-push, no deletions ✓
  (or list drift: "repo-c: main NOT protected → enable protection")

### Codecov config
- repo-a: codecov-action + codecov.yml with comment: false ✓
- repo-b: no codecov-action — skip
- repo-c: uses codecov-action but missing codecov.yml → add one (sister convention)

### Clean log-retention policy
- repo-a: 30-day age-based log prune ✓
- repo-b: no logs/ dir — skip
- repo-c: logs/ present, no age-based prune → add 30-day prune to clean

### Verdict

<"N drift items to address." | "All sisters coherent.">
```

## Rules

- Read-only. Never edit files, push branches, or modify GitHub settings. If the audit surfaces something that needs fixing, say so and stop.
- If one repo is in a broken state (e.g., `.claude/skill-context.md` missing), report it and continue the other checks — don't abort.
- `gh` calls go through the user's authenticated CLI; if auth fails, surface the error and stop that check (don't retry).
- Do not invoke `techne:ci-audit` recursively. If a PR has failing checks, *name* it and tell the user to run `techne:ci-audit` separately.
- The active sister list comes from `~/.claude/techne.toml`. If the file is missing, malformed, or yields zero active sisters, stop and ask — don't invent paths.
