# `techne:auto-commit`

Analyzes pending git changes and writes a structured, conventional-commit plan to `COMMITS.md` so you can review and stage commits in batches before committing.

## When to use

- You have a dirty working tree and want to group changes sensibly.
- You want a commit-message draft for a working tree before you commit.
- You want to prepare a commit plan from a diff without actually committing.
- Before pushing to main: stage logical commits instead of a single monolithic commit.

## What it does

- Reads the working-tree diff (staged and unstaged changes).
- Groups changes into logical, conventional-commit-style buckets (feat, fix, refactor, docs, test, chore).
- Writes the plan to `COMMITS.md` at the repo root.
- Leaves `COMMITS.md` for you to review; nothing is staged or committed automatically.
- After you approve, the skill can execute the full chain: stage → commit → push → PR.

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

## Usage

```bash
# Draft commit plan from working tree
techne:auto-commit

# Review the generated COMMITS.md, then:
# 1. Edit if needed
# 2. Ask Claude: "go" or "commit these"
# The skill will then stage, commit, push, and optionally create a PR
```

## Configuration

Optional `.claude/skill-context.md` overrides:

```yaml
auto-commit:
  conventional_types:
    - feat
    - fix
    - refactor
    - docs
    - test
    - chore
  create_pr: true  # auto-create PR after push
  target_branch: main
```

## Troubleshooting

**"COMMITS.md already exists"**: The skill won't overwrite it. Move the old file (`git rm COMMITS.md`) or rename it, then re-run.

**"Grouping doesn't make sense"**: Edit `COMMITS.md` manually before saying "go". The skill respects your edits.

**"I want to split a commit further"**: Edit the markdown, separate with `---`, and the skill will stage each section independently.

## Notes

- `COMMITS.md` is local-only by convention; don't `git add` it.
- The skill doesn't run `git commit` itself until you approve via "go". You stage and commit in batches.
- Say `go` after reviewing the plan and the skill will execute the full branch → commits → push → PR chain.

## See also

- [`techne:deslop`](deslop.md) — clean up AI-generated slop in commit messages and comments.
- [`techne:docsync`](docsync.md) — verify git claims (e.g., file paths in commit messages) match reality.
