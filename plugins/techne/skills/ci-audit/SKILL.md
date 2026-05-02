---
name: ci-audit
description: Audit the latest GitHub Actions workflow runs on the current branch/PR for warnings, errors, failures, deprecation notices, and other log noise — then fix what's fixable in-repo (workflow YAML, configs, source, tests). Hands commit + push back to the developer. Use after CI finishes and before merge, or whenever the user asks about failing/noisy CI — phrasings like "audit the PR", "why did CI fail", "check the workflow logs", "what's wrong with the build on GitHub", "fix the Actions warnings", "review the latest CI run", "clean up the green-with-warnings run", or names a specific check (Codecov, GitGuardian, Renovate) that's failing on the PR.
disable-model-invocation: false
allowed-tools: Bash(gh *) Bash(git branch --show-current) Bash(git rev-parse *) Bash(git log *) Glob Grep Read Edit Write
---

# CI Audit

Audit the GitHub Actions runs on the current branch. Classify every warning / error / failure / deprecation, fix what can be fixed in-repo, and leave `git add` / `commit` / `push` to the developer.

## Repo context

```!
cat .claude/skill-context.md 2>/dev/null || echo "(no .claude/skill-context.md — skill will use generic defaults)"
```

The injected `## ci_audit` section (if present) tells you which repo-side configs a CI failure can trace back to, which tools show up in error output for this repo, and any expected external PR checks (Codecov, GitGuardian, etc.). Use those instead of the generic defaults below when available.

## Scope

- **In scope:** workflow YAML under `.github/workflows/`, any config referenced from it (from the injected `ci_audit.referenced_configs`, typically `pyproject.toml`, `Makefile`, dev-runner script), and source/tests when a failure traces to code.
- **Out of scope:** committing, pushing, opening PRs, merging, re-running workflows. The developer drives git.

## Where runs live

- Current branch: `git branch --show-current`.
- Associated PR (if any): `gh pr view --json number,url,statusCheckRollup`. `statusCheckRollup[].detailsUrl` gives the run URL; the numeric id after `/runs/` is the run id you need.
- If there's no PR yet, fall back to `gh run list --branch <branch> --limit 5 --json databaseId,headSha,status,conclusion,workflowName,createdAt`.

Pick the **latest run per workflow** on the current head SHA. Don't mix SHAs — an older run against an older commit is noise.

### External PR checks (not GitHub Actions)

`statusCheckRollup` also surfaces third-party checks that aren't Actions runs — `codecov/patch`, `codecov/project`, `GitGuardian Security Checks`, `Renovate`, `DeepSource`, etc. They have `workflowName: ""` (empty) and their `detailsUrl` points off-repo (app.codecov.io, dashboard.gitguardian.com). `gh run view` does not work on them — there is no log to pull.

Treat them as first-class findings, not footnotes:

- **Codecov patch/project failures** — the uploaded `coverage.xml` is below a threshold. Repo-side fixes exist: add/tune `codecov.yml` (project + patch targets, carryforward, component flags), exclude generated/ignorable paths, install missing extras in CI so previously-skipped tests run, or add `pragma: no cover` to unreachable branches. All of these are `[FIX]` or `[PROPOSE]`, not `[DEFER]`.
- **GitGuardian / secret scanners** — if passing, `[EXPECTED]`. If failing, stop and ask before editing; the fix is usually rotating a real secret, not a repo edit.
- **Anything else** — at minimum, list it under "PR-level external checks" in the output with its conclusion. Don't silently drop.

## What to pull

For each run id:

```
gh run view <id> --json jobs,conclusion,status,workflowName,headSha
gh run view <id> --log
```

`--log` is the full concatenated log across all jobs/steps. It's the canonical source — prefer it over the web UI.

For runs with many jobs, `gh run view <id> --log-failed` narrows to failed steps only. Use it when the run failed but don't rely on it for warning-sweep (successful-but-noisy steps are exactly what you're auditing).

## Triage

Grep the log for these markers, in roughly this order of signal:

| Marker | What it usually means |
|---|---|
| `##[error]` | Actions runner reporting a step failure |
| `##[warning]` | Runner-level warning — often deprecation notices worth fixing |
| `Error:` / `error[` / `error:` | Tool-side error (extend via injected `ci_audit.tool_error_markers` — typical set: rustc, pytest, ruff, ty, pip-audit, mypy) |
| `FAIL`, `failed`, `exit 1` | Test / lint failure |
| `deprecat` (case-insensitive) | Action or API deprecation — actionable if replacement exists |
| `DeprecationWarning` | Node/Python runtime warnings — usually upstream, note but defer |
| `WARNING:` / `warning -` | Tool warnings (Codecov CLI, pip, etc.) |

A tight first pass:

```
gh run view <id> --log | grep -iE "warning|error|fail|deprecat" | head -100
```

Expand context (`grep -A3 -B1`) around any hit you can't classify from one line.

**Cross-reference `##[error]` with step `conclusion`.** A step with `conclusion: success` but an `##[error]` line in its output means `continue-on-error: true` swallowed a real failure. The runner still reported the error; the job is green only because of the policy flag. Don't file it under `[EXPECTED]` — the error is genuine, the step is just non-blocking. Surface it as `[FIX]` with the caveat that the step policy let the job pass. The user needs to know so they can either fix the underlying cause (usually), or promote the step to blocking once clean.

## Classify every finding

Put every finding into one of five buckets:

1. **`[FIX]` — Fix now, in this repo.** Workflow YAML referencing a deprecated action, a lint/test failure, a missing file, a misconfigured flag, a ty/mypy error that config should cover. Edit and verify.
2. **`[BUMP]` — Fix now, upstream-version bump.** An action is deprecated and the repo pins an old major — bump the pin after checking the upstream changelog.
3. **`[PROPOSE]` — Repo-side fix exists, needs your input.** Use this when there's a real fix inside this repo but the choice between paths is a product decision, not a mechanical one. Example: `codecov/patch` failing because new code has no coverage — options are (a) install missing extras in CI so skipped tests run, (b) add `codecov.yml` with a lower patch threshold, (c) add `pragma: no cover` on the uncovered branch. Enumerate all viable options in one line each; don't pick silently. This bucket exists so `[DEFER]` stops being a cargo-culted cop-out for anything that requires a second of thought.
4. **`[DEFER]` — No repo-side fix exists.** Node-runtime `DeprecationWarning: punycode` from an Actions transitive dep; library teardown noise from a third-party package; `xcrun is not installed` on Linux runners. If you can name a file in this repo that would change the output, it is not DEFER — it is PROPOSE or FIX. Cite the finding, say why no repo-side lever exists.
5. **`[EXPECTED]` — Ran as designed.** `continue-on-error` steps that exit 0 cleanly. Note that they ran; they are not findings. See also the `##[error]` cross-reference rule — a non-blocking step that *did* emit an error is `[FIX]`, not `[EXPECTED]`.

Rule of thumb: before marking anything `[DEFER]`, ask "is there a file in this repo whose edit would change the CI output?" If yes, it's `[FIX]` or `[PROPOSE]`. If no, `[DEFER]`. Every deferred item still gets one line in the verdict with *why*, so the user can overrule.

## Fixing

For bucket 1/2 items:

- **Deprecated action** → check the action's README / release notes for the replacement (WebFetch the repo's README). Migrate inputs carefully; parameter names sometimes change (`report-type` vs `report_type`, `file` vs `files`). Verify the new input names against current docs, don't guess.
- **Version pin bump** → prefer the latest stable major. Don't pin to floating `@main` or `@v<major>` without a SHA unless the rest of the repo already does.
- **Lint/test failure** → read the traceback, find the file, fix the root cause. Don't suppress unless the user asks.
- **Workflow misconfig** → keep the diff minimal. A missing `fail_ci_if_error`, a wrong `files:` path, a stray newline at EOF. One concern per edit.

After each edit, if the change is locally verifiable (a pytest change, a ruff config tweak, a `Makefile` target), run it. Workflow YAML changes can only be verified by the next CI run — say so explicitly in the verdict.

## Output format

A single block, no preamble:

```
## CI audit — <branch> @ <short-sha>

Runs reviewed:
- <workflowName> #<id> → <conclusion>  (<detailsUrl>)
- ...

PR-level external checks (omit section if none):
- <checkName> → <conclusion>  (<detailsUrl>)
- ...

### Findings

1. [FIX] <one-line summary> — <file:line> → edited.  Verified: <local check or "next CI run">.
2. [BUMP] <action> <old>→<new> — <file:line> → edited.
3. [PROPOSE] <one-line summary>. Options: (a) <option one>; (b) <option two>; (c) <option three>. Pick one.
4. [DEFER] <one-line summary>.  Why: <no repo-side lever — upstream or cosmetic>.
5. [EXPECTED] <step name> — `continue-on-error: true`, exited 0.

### Verdict

<"N fixed, M proposed, K deferred. Run `/techne:auto-commit` to group and commit the fixes." | "All runs clean; N items deferred with reasons.">
```

Numbered findings, one per item. Keep each line tight — link to the file, not the log. If any findings are `[PROPOSE]`, name them explicitly in the verdict ("M proposed — pick a path") so the user doesn't miss them.

## Rules

- Do not run `git add`, `git commit`, `git push`, `gh pr merge`, or `gh run rerun`. That's the developer's call. The verdict line points at `/techne:auto-commit` for the handoff — don't duplicate its job.
- Do not edit `logs/` — those are `/techne:audit`'s territory and come from local make runs, not CI.
- Do not open or modify PRs / issues. Reading PR metadata via `gh pr view` is fine; writing is not.
- If a finding requires a destructive or high-blast-radius change (removing a check, disabling a gate, force-pushing), stop and ask. Don't paper over a real failure.
- If the latest run is still `in_progress`, say so and stop — don't audit a partial log.
- If a secret scanner (GitGuardian, gitleaks, trufflehog) is failing, stop and ask. The fix is almost always a real secret that needs rotating, not a repo edit.
