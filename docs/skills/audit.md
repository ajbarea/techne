---
description: Run the repo's make targets in dependency order and check each command's terminal output against its logs/dev archive.
---

# `techne:audit`

Run your repo's `make` targets in dependency order and reconcile terminal output against the `logs/dev-<ts>-<cmd>.log` archive convention.

Part of [techne](../plugins/techne.md): `/plugin install techne@techne`, then `/techne:setup`.

## When to use

Pre-push: validate the toolchain is clean before pushing to CI. "Is the build clean?" / "Am I ready to push?" / "Did the last refactor break anything silently?"

## Usage

Invoke by name in Claude Code:

```
/techne:audit
```

Modes are picked from natural-language phrasing. Say "run the full audit" or "fast check"; the skill reads the phase list and fast-subset from your `.claude/skill-context.md`.

The `## audit` section also names the `fast_subset` of phases for a fast check, the `stop_early` phases whose failure ends the run, and the `do_not_run` targets the skill never starts. The skill never reads `logs/dev-latest.log`. It prints one table row per command and ends with `Full audit clean.` or `Fast audit clean.` when every row passes.

## Prerequisites

This skill is opinionated. It requires:

- A `Makefile` with the phases listed in your `.claude/skill-context.md`'s `## audit` section.
- The dev-runner archive convention: each `make <target>` invocation writes `logs/dev-<UTC-timestamp>-<target>.log` ending with a `SUMMARY` block. Techne ships `scripts/dev-runner.sh` as the reference implementation.

See [Conventions](../conventions.md#section-reference) for the `## audit` keys. Without a `.claude/skill-context.md` the skill stops and points you at `/techne:setup`; it does not fall back to default phases.

## See also

- [`techne:ci-audit`](ci-audit.md): audit the cloud equivalent (GitHub Actions runs).
- [`techne:docsync`](docsync.md): audit prose claims (Makefile commands, paths) against the code.
- [Conventions](../conventions.md): the dev-runner archive convention.

## Full instructions

[`SKILL.md` on GitHub](https://github.com/ajbarea/techne/blob/main/plugins/techne/skills/audit/SKILL.md) holds the full instructions Claude follows for this skill.
