# `techne:auto-commit`

Analyzes pending git changes and writes a structured, conventional-commit plan to `COMMITS.md` so you can review and stage commits in batches before committing.

## When to use

- You have a dirty working tree and want to group changes sensibly.
- You want a commit-message draft for a working tree before you commit.
- You want to prepare a commit plan from a diff without actually committing.

## What it does

- Reads the working-tree diff.
- Groups changes into logical, conventional-commit-style buckets.
- Writes the plan to `COMMITS.md` at the repo root.
- Leaves `COMMITS.md` for you to review; nothing is staged or committed automatically.

## Output shape

```markdown
## Commit 1 — feat: add language selector to footer
- app/components/layout/TheFooter.vue
- app/data/locales.ts

## Commit 2 — chore: bump axe-core/playwright to 4.12
- package.json
- package-lock.json
```

## Notes

- `COMMITS.md` is local-only by convention; don't `git add` it.
- The skill doesn't run `git commit` itself — you stage and commit in batches.
