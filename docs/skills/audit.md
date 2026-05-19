# `techne:audit`

Run your repo's `make` targets in dependency order and reconcile terminal output against the `logs/dev-<ts>-<cmd>.log` archive convention.

## When to use

Pre-push: validate the toolchain is clean before pushing to CI. "Is the build clean?" / "Am I ready to push?" / "Did the last refactor break anything silently?"

## Usage

Invoke by name in Claude Code:

```
/techne:audit
```

Modes are picked from natural-language phrasing. Say "run the full audit" or "fast check"; the skill reads the phase list and fast-subset from your `.claude/skill-context.md`.

## Prerequisites

This skill is opinionated. It requires:

- A `Makefile` with the phases listed in your `.claude/skill-context.md`'s `## audit` section.
- The dev-runner archive convention: each `make <target>` invocation writes `logs/dev-<UTC-timestamp>-<target>.log` ending with a `SUMMARY` block. Techne ships `scripts/dev-runner.sh` as the reference implementation.

See [Conventions](../conventions.md) for the setup walkthrough.

## See also

- [`techne:ci-audit`](ci-audit.md): audit the cloud equivalent (GitHub Actions runs).
- [`techne:docsync`](docsync.md): audit prose claims (Makefile commands, paths) against the code.
- [Conventions](../conventions.md): the dev-runner archive convention.
