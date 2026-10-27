---
description: Check a repo's logging against techne's standard and fix what falls short, so a bug can be found from the logs alone.
---

# `techne:logging`

Hold a repo's logs to one standard, so a failure can be found from the logs alone, on your machine and in a CI run. The skill runs a check over Python, Rust, TypeScript, shell and GitHub Actions files, reviews what a script cannot judge, fixes what falls short, then reproduces one real failure to show the log names its cause.

Part of [techne](../plugins/techne.md): `/plugin install techne@techne`, then `/techne:setup`.

## When to use

- Before relying on a repo's logs to debug: "are our logs any good?"
- Setting up logging in a new repo, or bringing an old one up to the standard.
- Checking that no secret reaches a log call.

## Usage

```
/techne:logging
```

The check also runs on its own, from any repo, with no Claude session:

```
python3 <techne>/plugins/techne/skills/logging/scripts/logcheck.py [--format text|github|json] [REPO]
```

It reads tracked files only, skips vendored and build folders, and exits 0 when clean, 1 with findings, 2 when the path is not a git repository. `--format github` prints each finding as a workflow annotation, for a CI step.

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

Code-level rules (f-strings in log calls, root-logger calls, stray prints) are left to each stack's linter, which already runs in `make lint` and CI; the check makes sure those rules are on.

A line with `logcheck: ignore[<rule>]` in a comment is skipped. A repo opts out of a rule (including the repo-wide `lint-*` and `log-file-tracked`), or skips a path, in the `## logging` section of `.claude/skill-context.md`:

```
## logging
- ignore: lint-js (the site ships no runtime JavaScript logging)
- skip: legacy/
```

## The standard

[`references/standard.md`](https://github.com/ajbarea/techne/blob/main/plugins/techne/skills/logging/references/standard.md) holds the standard with its sources: levels and what belongs at each, structured files and readable terminals, where log files live on Windows, Linux and WSL, rotation and caps, keeping secrets and personal data out, one id across processes, and logs a CI audit can read (annotations, groups, uploaded artifacts).

It is its own skill, beside `deslop` (comments), `docsync` (documentation) and `audit` (tests), because a logging review reads source, linter configs and workflows on any branch before CI runs. [`techne:sisters`](sisters.md) runs the same check across every sister as its check 16, and [`techne:ci-audit`](ci-audit.md) points at the standard when a failed run's log does not name the cause.

## See also

- [`techne:ci-audit`](ci-audit.md): read a finished CI run's log.
- [`techne:sisters`](sisters.md): the same check across every linked repo.
- [Conventions](../conventions.md#section-reference): the `## logging` section.

## Full instructions

[`SKILL.md` on GitHub](https://github.com/ajbarea/techne/blob/main/plugins/techne/skills/logging/SKILL.md) holds the full instructions Claude follows for this skill.
