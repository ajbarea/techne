# `techne:ci-audit`

Audits the latest GitHub Actions workflow runs on the current branch or PR for warnings, errors, failures, deprecation notices, and other log noise. Fixes what's fixable in-repo.

## When to use

- After CI finishes and before merge.
- A check is failing or noisy (Codecov, GitGuardian, Renovate, lint, tests).
- "Why did CI fail" / "check the workflow logs" / "what's wrong with the build on GitHub."
- A run is green but littered with warnings worth cleaning up.
- Deprecation warnings in actions (e.g., "node-version 12 is deprecated, use 20").

## What it does

- Pulls the most recent run for each workflow on the branch/PR via `gh run list` + `gh run view`.
- Parses logs for errors, warnings, deprecation notices, and noise patterns.
- Categorizes issues: workflow YAML fixes vs. source/test fixes vs. third-party noise.
- Identifies what's fixable in-repo: workflow YAML tweaks, config drift, source/test issues.
- Applies fixes, leaves commit + push back to you for approval.
- Surfaces unfixable issues (e.g., "Codecov rejected your coverage report") for manual triage.

## Usage

```bash
# Audit all workflows on this branch/PR
techne:ci-audit

# Audit a specific workflow
techne:ci-audit --workflow lint.yml

# Show report only, don't apply fixes
techne:ci-audit --dry-run
```

## Configuration

Optional `.claude/skill-context.md`:

```yaml
ci-audit:
  workflows_to_audit:
    - lint.yml
    - test.yml
  ignore_patterns:
    - "Warning: Node.js v14 is deprecated"
  auto_fix: true  # apply fixes without approval
```

## What it does NOT do

- Doesn't push or commit on your behalf without approval.
- Doesn't bypass failing checks; if a fix is risky, it surfaces and waits for direction.
- Doesn't silence warnings; it fixes root causes or leaves them visible.

## Troubleshooting

**"gh: not authenticated"**: Run `gh auth login` and authenticate with GitHub.

**"No runs found"**: Ensure the branch has been pushed and GitHub Actions are enabled on the repo.

**"Fix looks wrong"**: Review the proposed change in the report. Edit manually or ask the skill to refine the approach.

## See also

- [`techne:audit`](audit.md) — audit local make targets instead of GitHub Actions.
- [`techne:deslop`](deslop.md) — clean up AI-generated warnings in workflow logs and comments.

## Reads

- `gh run list` / `gh run view` output for the current branch/PR.
- `<repo>/.github/workflows/*.yml`
- Workflow log archives (downloaded on demand).
