# `techne:auto-commit`

Analyze pending git changes and write a structured commit plan to `COMMITS.md` so you can review and stage commits in batches before anything lands.

## When to use

- Dirty working tree: group logically-related changes into conventional commits before pushing.
- "Draft commit messages for my changes" / "Group these changes into sensible commits."
- Before opening a PR: produce a reviewable plan, then execute it in one step.

## Usage

Invoke by name in Claude Code:

```
/techne:auto-commit
```

The skill produces a `COMMITS.md` at the repo root grouped by change type, then prints one line: `Plan at COMMITS.md. Say 'go' to execute (branch → commits → push → PR), or edit the file first.`

Saying "go" (or "ship it", "execute the plan") triggers the full branch-commit-push-PR chain against the current plan. The skill refuses to execute a stale plan if the working tree has drifted since the scan.

## See also

- [`techne:ci-audit`](ci-audit.md): audit CI after the branch lands.
- [`techne:deslop`](deslop.md): clean up comments before committing.
- [Conventions](../conventions.md): working-docs convention (`COMMITS.md` is never committed).
