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
feat(auth): add JWT refresh token rotation

- Added rotating refresh tokens with 7-day expiry
- Wired new endpoint into the auth router
- Covered rotation edge cases in tests

Files: src/auth/tokens.py, src/auth/routes.py, tests/auth/test_tokens.py

---

fix(parser): handle trailing whitespace in CSV headers

- Stripped whitespace before column-name comparison
- Added regression test for the original bug

Files: src/parser/csv.py, tests/parser/test_csv.py
```

## Notes

- `COMMITS.md` is local-only by convention; don't `git add` it.
- The skill doesn't run `git commit` itself. You stage and commit in batches.
- Say `go` after reviewing the plan and the skill will execute the full branch → commits → push → PR chain.
