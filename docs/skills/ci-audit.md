# `techne:ci-audit`

Audit the latest GitHub Actions workflow runs on the current branch or PR for warnings, errors, failures, and deprecation notices. Fix what's fixable in-repo; hand commit and push back to you.

## When to use

- After CI finishes and before merge.
- "Why did CI fail?" / "Check the workflow logs." / "Clean up the green-with-warnings run."
- A specific check is failing (Codecov, GitGuardian, Renovate) and you want to know why.
- Deprecation notices in action steps worth cleaning up before they become blocking.

## Usage

Invoke by name in Claude Code:

```
/techne:ci-audit
```

The skill pulls the most recent run per workflow on the current branch via `gh run list` and `gh run view`, classifies every finding, applies in-repo fixes (workflow YAML, config, source), and outputs a verdict: `N fixed, M proposed, K deferred.`

The skill does not commit, push, or merge. Run `/techne:auto-commit` to group and commit the fixes.

## See also

- [`techne:audit`](audit.md): audit local `make` targets instead of GitHub Actions.
- [`techne:auto-commit`](auto-commit.md): group and commit the fixes the audit produced.
- [Conventions](../conventions.md): `.claude/skill-context.md` `## ci_audit` section for repo-specific config.
