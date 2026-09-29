---
name: sisters
description: Cross-repo drift audit across the linked repos listed in `~/.claude/techne.toml`. Read-only inspection of CI action and toolchain pins, skill-context parity, GitHub merge settings and branch protection, open PRs, branch/worktree/stash hygiene, and fleet conventions (Codecov, Dependabot, log retention, README header, shared docs-site files). A clean mode removes finished branches and worktrees after the user approves the list. Use for "audit the sisters", "are the sisters in sync", "check cross-repo drift", "comb the sisters", "clean up branches and worktrees across the repos", or when several sister repos are named together for a consistency check. Not for auditing one repo's own build (techne:audit) or its CI logs (techne:ci-audit).
disable-model-invocation: false
allowed-tools: Bash(gh api repos/*) Bash(gh pr list*) Bash(gh auth status) Bash(git fetch *) Bash(git for-each-ref *) Bash(git rev-list *) Bash(git branch *) Bash(grep *) Bash(awk *) Bash(sed *) Bash(sort *) Bash(uniq *) Bash(wc *) Bash(ls *) Bash(python3 *) Bash(git -C *) Bash(head *) Bash(cut *) Bash(tr *) Bash(printf *) Glob Grep Read
---

# Sisters Audit

Audit the active sister repos for cross-repo drift. Report every finding, grouped by category. Leave fixing to follow-up work or the developer: the audit observes, it does not edit. The one exception is [clean mode](#clean-mode), which removes finished branches and worktrees the user has approved.

## Config (load first)

Active sister list, workspace root, and GitHub user are read from `~/.claude/techne.toml` at runtime. Run this preamble before any audit checks below; it sets `$SISTERS`, `$TEAM_SISTERS` (active sisters marked `kind = "team"`), `$WORKSPACE`, and `$GITHUB_USER`:

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

Run all fourteen, in order, using the commands in [references/checks.md](references/checks.md).
Each check reports per repo; one broken repo never aborts the others.

| # | Check | Drift means | Recommend |
|---|---|---|---|
| 1 | Action pins | One action pinned to different versions across repos | The newest pin in the set |
| 2 | Skill-context parity | A repo missing a required `##` section, or carrying one the others lack | Surface; extra sections may be deliberate |
| 3 | Merge settings | Anything but squash-only, delete-on-merge, auto-merge on | The canonical settings |
| 4 | Open PRs | Open longer than 14 days, or not mergeable | Name it; `techne:ci-audit` reads failing checks |
| 5 | Branch and worktree hygiene | A branch, worktree or stash left behind: judged by its PR's state, not by ahead counts, which squash merges make meaningless | Offer [clean mode](#clean-mode) for the safe-to-remove items |
| 6 | Local `main` sync | Local `main` ahead of or behind `origin/main` | Pull, or investigate unpushed commits |
| 7 | Toolchain pins | `requires-python`, ruff `target-version`, or ruff/ty/pytest specifiers differ | Newest for tools; ask the user for Python envelopes |
| 8 | Branch protection | `main` unprotected, no required check, force-push or deletion allowed | Protect it |
| 9 | Codecov config | `codecov-action` in CI without `codecov.yml` carrying `comment: false` | Add it |
| 10 | Log retention | `logs/` without a 30-day age-based prune in `make clean` | Add the prune |
| 11 | Dependabot coverage | A shipped manifest with no matching ecosystem and no documented deferral | Add the ecosystem |
| 12 | README header | A solo repo with a hero asset whose README does not open Hero → Title → tagline → Badges | Align, or confirm it is intentional |
| 13 | Worktree ignore | `.claude/worktrees/` not ignored by a committed `.gitignore` (unignored, or only in `.git/info/exclude`) | Add `.claude/worktrees/` to `.gitignore` |
| 14 | Docs-site shared files | A site's copy of a shared docs-site file differs from techne's, or a `docs/` page is missing from the nav | Fix techne's copy and sync it; list or move the page |

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

### Branch and worktree hygiene
- repo-a: clean ✓
- repo-b: safe to remove: worktree `.claude/worktrees/docs` (PR #50 merged), local-branch `fix/x` (PR #41 merged)
- repo-c: needs a look: local-branch `wip` (no PR; 3 commit(s) not in main); info: stash@{0} 12d old
- (end with: "N items safe to remove; say "clean them up" to review and remove them.")

### Local main sync
- All sisters: ahead=0 behind=0. ✓

### README header convention
- repo-a: centered masthead, hero before title ✓
- repo-b: no hero asset, convention N/A
- repo-c: hero asset present but header off-convention → align (or confirm intentional)

### Branch protection
- All sisters: protected with required checks, no force-push, no deletions ✓
  (or list drift: "repo-c: main NOT protected → enable protection")

### Codecov config
- repo-a: codecov-action + codecov.yml with comment: false ✓
- repo-b: no codecov-action, skip
- repo-c: uses codecov-action but missing codecov.yml → add one (sister convention)

### Clean log-retention policy
- repo-a: 30-day age-based log prune ✓
- repo-b: no logs/ dir, skip
- repo-c: logs/ present, no age-based prune → add 30-day prune to clean

### Dependabot coverage
- All sisters: dependabot.yml covers every shipped manifest (deferrals documented) ✓
  (or list drift: "repo-c: has package.json but no npm ecosystem → add it")

### Worktree ignore
- repo-a: ignored by .gitignore ✓
- repo-b: ignored only by .git/info/exclude (machine-local) → add `.claude/worktrees/` to .gitignore
- repo-c: not ignored → add `.claude/worktrees/` to .gitignore

### Docs-site shared files
- repo-a: shared files match ✓
- repo-b: overrides/main.html differs → fix techne's copy, sync, PR
- repo-c: docs/notes.md published but not in the nav → list it or move it out of docs/

### Verdict

<"N drift items to address." | "All sisters coherent.">
```

## Clean mode

For "comb the sisters", "clean up the branches", or a yes to the offer at the end of check 5.

1. Survey and write the plan to a file of this run's own, since other sessions may be cleaning too: `PLAN=$(mktemp -t sisters-plan.XXXXXX) && python3 ${CLAUDE_SKILL_DIR}/scripts/hygiene.py --plan-out "$PLAN"` (add `--repo <name>` to narrow it).
2. Show the user the **Safe to remove** list exactly as printed, and ask for approval. Show **Needs a look** beside it, unchanged: those are the user's calls, never the script's.
3. On approval, run `python3 ${CLAUDE_SKILL_DIR}/scripts/hygiene.py --apply "$PLAN"` and relay every line it prints.

What the script counts as safe, and what it never touches:

- A branch is finished when its PR merged into the default branch and the tip is the PR's head or inside it, or, for a local branch with no PR, when the tip is already in the default branch. Commits added after the merge, a PR merged into another branch, a closed-unmerged PR, or no PR with unmerged commits all go to **Needs a look**.
- A worktree is removed only when its branch is finished and it is unlocked, idle for two hours, holds no uncommitted or untracked file, no ignored file other than build output (`.venv`, `site`, caches), and no worktree of its own, and no live process has its working directory inside it (`/proc`, or `lsof` on macOS; when neither can say, the worktree is held). These are checked again just before removal. Another session's worktree fails at least one of them while that session is working.
- A remote branch is deleted only from the user's own PR, merged into the default branch. A remote branch with no PR is never deleted: it may be a long-lived branch or a teammate's.
- Stashes and uncommitted changes are reported, never removed.
- The default branch comes from GitHub, not the clone's `origin/HEAD`, which goes stale.
- `--apply` surveys again and removes only items still safe at the same tip, deleting with compare-and-delete (`update-ref -d <sha>`, `--force-with-lease`), and removes worktrees without `--force`. Anything that moved is kept and named.

## Rules

- Read-only, except clean mode's `--apply` after the user approves the list. Never edit files, push branches, or modify GitHub settings. If the audit surfaces something that needs fixing, say so and stop.
- If one repo is in a broken state (e.g., `.claude/skill-context.md` missing), report it and continue the other checks — don't abort.
- `gh` calls go through the user's authenticated CLI; if auth fails, surface the error and stop that check (don't retry).
- Do not invoke `techne:ci-audit` recursively. If a PR has failing checks, *name* it and tell the user to run `techne:ci-audit` separately.
- The active sister list comes from `~/.claude/techne.toml`. If the file is missing, malformed, or yields zero active sisters, stop and ask — don't invent paths.
