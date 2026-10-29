---
description: Audit the latest GitHub Actions runs on the current branch or PR for warnings, failures and noise, and fix what is fixable in the repo; or report on one run by id, read-only and unattended.
---

# `techne:ci-audit`

Audit the latest GitHub Actions workflow runs on the current branch or PR for warnings, errors, failures, and deprecation notices. Fix what's fixable in-repo; hand commit and push back to you.

Part of [techne](../plugins/techne.md): `/plugin install techne@techne`, then `/techne:setup`.

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

The skill pulls the most recent run per workflow on the current head SHA via the PR's `statusCheckRollup` (falling back to `gh run list` when there is no PR), reads each run with `gh run view`, lists external PR checks such as Codecov and GitGuardian, classifies every finding, applies in-repo fixes (workflow YAML, config, source), and outputs a verdict: `N fixed, M proposed, K deferred.` A finding with a repo-side fix that needs a choice between paths is `[PROPOSE]`: on a solo repo the skill takes the option the evidence supports and applies it, naming the others; on a team repo it lists the options for you to pick. See [Solo and team repos](../conventions.md#solo-and-team-repos).

The skill does not commit, push, or merge. Run `/techne:auto-commit` to group and commit the fixes.

## Report mode

A watcher that has a run id and no one at the terminal runs the report script:

```bash
bash plugins/techne/skills/ci-audit/scripts/report.sh OWNER/REPO RUN_ID OUT_DIR
```

It works in three steps:

1. It records the run with read-only `gh api` calls: the run, its jobs and steps, each job's log and the check-run annotations. The job-log endpoint serves every job, while `gh run view --log` returns nothing for some runs on older gh.
2. `ci_report.py facts` computes what a script can settle: each failing step with its error lines and their file:line locations, each step that succeeded with an `##[error]` in it, and the warnings and deprecations, deduplicated.
3. A headless `claude -p` session judges the facts in restricted and safe mode: Read, Grep and Glob only, Read allowed only under the output folder and the skill, and no settings files, CLAUDE.md, plugins, hooks or MCP servers. It treats log text as data, never instructions, and the script refuses a report that contradicts the facts (a failing step reported as anything but a failure, a swallowed error reported clean).

The session replies with JSON that a schema checks (`ci_report.py schema`). The script writes `report.json` and `report.md` with:

- the verdict.
- the failing step, its root cause and its file:line.
- each finding in the same buckets as the interactive audit.
- whether the log names the cause, per the [logging standard](logging.md).

It fixes, commits and posts nothing. `/techne:ci-audit report OWNER/REPO RUN_ID` runs the same from a session. The evals `behavior-ci-audit-report-*` (`make evals-bash`) score it on three recorded runs: a real failure, a green run with a dependency's deprecation, and a success that swallowed an error behind a log line that tries to steer the verdict.

## See also

- [`techne:audit`](audit.md): audit local `make` targets instead of GitHub Actions.
- [`techne:auto-commit`](auto-commit.md): group and commit the fixes the audit produced.
- [Conventions](../conventions.md#section-reference): `.claude/skill-context.md` `## ci_audit` section for repo-specific config.

## Full instructions

[`SKILL.md` on GitHub](https://github.com/ajbarea/techne/blob/main/plugins/techne/skills/ci-audit/SKILL.md) holds the full instructions Claude follows for this skill.
