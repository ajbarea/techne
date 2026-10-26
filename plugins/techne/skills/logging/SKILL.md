---
name: logging
description: Audit a repo's logging against techne's standard and fix what falls short, so a bug can be found from the logs alone, locally and in CI. Runs a check over Python, Rust, TypeScript, shell and GitHub Actions files (linter gates for logging, secrets reaching log calls, log files without a size cap, error text on stdout, CI logs not uploaded on failure, committed log files), then reviews what a script cannot judge (levels, message content, run ids across processes, where log files live). Use when the user asks to "check the logging", "are our logs any good", "set up logging", "make the logs useful for debugging", "add structured logs", "audit logs for secrets", or wants a repo brought up to the logging standard. Not for reading a finished CI run's log (techne:ci-audit) or for the cross-repo sweep (techne:sisters runs the same check as its check 16).
disable-model-invocation: false
allowed-tools: Bash(python3 *) Bash(git *) Bash(gh *) Glob Grep Read Edit Write WebSearch WebFetch
---

# Logging

`<skill-dir>` is the directory holding this SKILL.md, and `<plugin-root>` is the plugin's root directory, two levels above it.

Hold the repo's logs to the standard in [references/standard.md](references/standard.md): read
it before judging or changing anything. It says what each stack does, why, and the sources.

## Repo context

```!
echo "<!-- skill-context: $(git rev-parse --show-toplevel 2>/dev/null || pwd) -->"; cat "$(git rev-parse --show-toplevel 2>/dev/null || pwd)/.claude/skill-context.md" 2>/dev/null || echo "(no .claude/skill-context.md in this repo)"
```

If the block above appears as a command rather than its output, run it and use what it prints.

The `## logging` section, when present, holds `- ignore: <rule>, ...` (rules this repo opts out
of, each with its reason) and `- skip: <path>/, ...` (paths the check leaves out). The check
reads both itself.

## 1. Run the check

From the repo root (or pass the repo's path):

```
python3 "<skill-dir>/scripts/logcheck.py"
```

It prints `path:line: rule: message` per finding and exits 1, or prints `logging standard ✓`
and exits 0. `--format json` gives the same findings as a list; `--format github` prints them as
workflow annotations, for a CI step. Exit 2 means the path is not a git repository.

| Rule | Means |
|---|---|
| `lint-python` | ruff does not select `G` and `LOG` |
| `lint-rust` | clippy's `print_stdout`, `print_stderr`, `dbg_macro` are not `warn` |
| `lint-js` | no ESLint `no-console` or Biome `noConsole` rule is on |
| `secret-in-log` | a secret-looking name reaches a log, print or echo call |
| `unbounded-log-file` | a file handler or appender keeps growing or keeps every file |
| `stderr-for-errors` | shell error text goes to stdout; in a workflow, not as `::error::` |
| `ci-logs-not-uploaded` | a job writes a log file and uploads nothing when it fails |
| `log-file-tracked` | a `.log` file is committed |

A finding that is right for this repo anyway gets `logcheck: ignore[<rule>]` in a comment on
that line, with the reason beside it, or a `- ignore:` line in `## logging`. Never add one to
make the check pass.

## 2. Review what the check cannot judge

Read the logging setup itself: where each entry point configures logging, a sample of log calls
in the code paths that fail most (network, subprocess, parsing, file IO), and the CI workflows.
For each item, report what is missing and where:

- **Levels:** each call's level matches the table in the standard; nothing routine at WARNING,
  no failure at INFO or DEBUG only.
- **Messages:** an error names the value, the file or the command that failed and what was
  expected. An exception is logged once, where it is handled, with its traceback.
- **Output:** results on stdout, diagnostics on stderr or the log file; JSON lines in the file,
  plain lines on a terminal.
- **One id across processes:** a hook, CLI and backend that serve one run log the same
  `run_id`, `session_id` or trace id.
- **Location and cap:** log files under the OS's user log folder (or the repo's ignored `logs/`
  for development runs), rotated with a fixed number kept, `*.log` in `.gitignore`.
- **CI:** failures surface as annotations, long output sits in groups, log files are uploaded
  on failure, pytest runs with `-rs`.

A finding here cites the standard's section, not taste.

## 3. Fix

Run `python3 "<plugin-root>/_shared/repo_kind.py"`. It prints `solo: <why>` or `team: <why>`.

- **Solo repo:** fix each finding in place, check findings first, then review findings. Turning
  on a linter rule comes with fixing what it then reports, in the same change. Run the repo's
  lint and tests after each group of edits.
- **Team repo:** list the fixes with the file and line each would change and ask before
  editing.

Then prove the logs work: reproduce one real failure (a missing file, a bad config value, a
failed subprocess) and confirm the log alone names the cause, the input and where it happened,
without reading the code. Quote that log line in the report. When no failure can be reproduced
safely, say so.

## Report

```
## Logging — <repo> @ <short-sha>

Repo: <the solo/team line>

### Check (logcheck.py)
1. <path:line> <rule>: <message> → fixed | proposed | ignored (<reason>)

### Review
1. <standard section>: <what is missing, file:line> → fixed | proposed

### Proof
<the reproduced failure and the log line that names it, or why none was reproduced>

### Verdict
<"N fixed, M proposed." | "Meets the standard.">
```

## Rules

- Never weaken a gate to pass: no `logcheck: ignore`, `noqa`, `#[allow]` or `eslint-disable`
  without a reason a reviewer would accept, and never a lowered lint level.
- Never print, quote or commit a secret while fixing `secret-in-log`; quote the variable name.
- Leave `logs/` contents alone; `make clean` prunes them.
- Commit, push and PRs stay with the user, or with the session's own PR flow.
