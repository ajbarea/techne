# `techne:ci-audit`

Audits the latest GitHub Actions workflow runs on the current branch or PR for warnings, errors, failures, deprecation notices, and other log noise. Fixes what's fixable in-repo.

## When to use

- After CI finishes and before merge.
- A check is failing or noisy (Codecov, GitGuardian, Renovate, lint, tests).
- "Why did CI fail" / "check the workflow logs" / "what's wrong with the build on GitHub."
- A run is green but littered with warnings worth cleaning up.

## What it does

- Pulls the most recent run for each workflow on the branch/PR via `gh run list` + `gh run view`.
- Parses logs for errors, warnings, deprecation notices, and noise patterns.
- Identifies what's fixable in-repo: workflow YAML tweaks, config drift, source/test issues.
- Applies fixes, leaves commit + push back to you.

## What it does NOT do

- Doesn't push or commit on your behalf.
- Doesn't bypass failing checks; if a fix is risky, it surfaces and waits for direction.

## Reads

- `gh run list` / `gh run view` output for the current branch/PR.
- `<repo>/.github/workflows/*.yml`
- Workflow log archives (downloaded on demand).
