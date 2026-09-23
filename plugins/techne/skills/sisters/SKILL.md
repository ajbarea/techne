---
name: sisters
description: Cross-repo drift audit across the linked repos listed in `~/.claude/techne.toml`. Read-only inspection of CI action and toolchain pins, skill-context parity, GitHub merge settings and branch protection, open PRs, branch hygiene, and fleet conventions (Codecov, Dependabot, log retention, README header). Use for "audit the sisters", "are the sisters in sync", "check cross-repo drift", or when several sister repos are named together for a consistency check. Not for auditing one repo's own build (techne:audit) or its CI logs (techne:ci-audit).
disable-model-invocation: false
allowed-tools: Bash(gh api repos/*) Bash(gh pr list*) Bash(gh auth status) Bash(git fetch *) Bash(git for-each-ref *) Bash(git rev-list *) Bash(git branch *) Bash(grep *) Bash(awk *) Bash(sed *) Bash(sort *) Bash(uniq *) Bash(wc *) Bash(ls *) Bash(python3 *) Bash(git -C *) Bash(head *) Bash(cut *) Bash(tr *) Bash(printf *) Glob Grep Read
---

# Sisters Audit

Audit the active sister repos for cross-repo drift. Report every finding, grouped by category. Leave fixing to follow-up work or the developer — this skill observes, it does not edit.

## Config (load first)

Active sister list, workspace root, and GitHub user are read from `~/.claude/techne.toml` at runtime. Run this preamble before any audit checks below — it sets `$SISTERS`, `$TEAM_SISTERS` (active sisters marked `kind = "team"`), `$WORKSPACE`, and `$GITHUB_USER`:

```
eval "$(python3 - <<'PY'
import tomllib, os, shlex
with open(os.path.expanduser('~/.claude/techne.toml'), 'rb') as f:
    d = tomllib.load(f)
active = [s for s in d['sisters'] if s.get('status', 'active') == 'active']
sisters = ' '.join(s['name'] for s in active)
team = ' '.join(s['name'] for s in active if s.get('kind') == 'team')
ws = d['workspace_root']  # required; fails loudly with KeyError on misconfig
gu = d['github_user']     # required; fails loudly with KeyError on misconfig
print(f"SISTERS={shlex.quote(sisters)}")
print(f"TEAM_SISTERS={shlex.quote(team)}")
print(f"WORKSPACE={shlex.quote(ws)}")
print(f"GITHUB_USER={shlex.quote(gu)}")
PY
)"
```

If `~/.claude/techne.toml` is missing or yields zero active sisters, stop and tell the user — don't guess. Each sister's canonical local path is `$WORKSPACE/<name>` and its GitHub slug is `$GITHUB_USER/<name>`.

## What to check

Run all twelve, in order, using the commands in [references/checks.md](references/checks.md).
Each check reports per repo; one broken repo never aborts the others.

| # | Check | Drift means | Recommend |
|---|---|---|---|
| 1 | Action pins | One action pinned to different versions across repos | The newest pin in the set |
| 2 | Skill-context parity | A repo missing a required `##` section, or carrying one the others lack | Surface; extra sections may be deliberate |
| 3 | Merge settings | Anything but squash-only, delete-on-merge, auto-merge on | The canonical settings |
| 4 | Open PRs | Open longer than 14 days, or not mergeable | Name it; `techne:ci-audit` reads failing checks |
| 5 | Stale local branches | A branch ahead of `origin/main` that is not checked out | Surface |
| 6 | Local `main` sync | Local `main` ahead of or behind `origin/main` | Pull, or investigate unpushed commits |
| 7 | Toolchain pins | `requires-python`, ruff `target-version`, or ruff/ty/pytest specifiers differ | Newest for tools; ask the user for Python envelopes |
| 8 | Branch protection | `main` unprotected, no required check, force-push or deletion allowed | Protect it |
| 9 | Codecov config | `codecov-action` in CI without `codecov.yml` carrying `comment: false` | Add it |
| 10 | Log retention | `logs/` without a 30-day age-based prune in `make clean` | Add the prune |
| 11 | Dependabot coverage | A shipped manifest with no matching ecosystem and no documented deferral | Add the ecosystem |
| 12 | README header | A solo repo with a hero asset whose README does not open Hero → Title → tagline → Badges | Align, or confirm it is intentional |

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

### README header convention
- repo-a: centered masthead, hero before title ✓
- repo-b: no hero asset — N/A
- repo-c: hero asset present but header off-convention → align (or confirm intentional)

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

### Dependabot coverage
- All sisters: dependabot.yml covers every shipped manifest (deferrals documented) ✓
  (or list drift: "repo-c: has package.json but no npm ecosystem → add it")

### Verdict

<"N drift items to address." | "All sisters coherent.">
```

## Rules

- Read-only. Never edit files, push branches, or modify GitHub settings. If the audit surfaces something that needs fixing, say so and stop.
- If one repo is in a broken state (e.g., `.claude/skill-context.md` missing), report it and continue the other checks — don't abort.
- `gh` calls go through the user's authenticated CLI; if auth fails, surface the error and stop that check (don't retry).
- Do not invoke `techne:ci-audit` recursively. If a PR has failing checks, *name* it and tell the user to run `techne:ci-audit` separately.
- The active sister list comes from `~/.claude/techne.toml`. If the file is missing, malformed, or yields zero active sisters, stop and ask — don't invent paths.
