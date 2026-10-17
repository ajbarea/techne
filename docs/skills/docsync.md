---
description: "Check a documentation file for drift against the code: commands, paths, config keys, signatures, versions and environment variables."
---

# `techne:docsync`

Compare documentation against the code it describes. Surface where the docs say one thing and the code says another, then propose corrections grounded in current code.

Part of [techne](../plugins/techne.md): `/plugin install techne@techne`, then `/techne:setup`.

## When to use

- After a refactor that forgot to update the docs.
- "Audit README.md for stale claims."
- Before a release where outdated CLI commands or file paths would confuse users.
- Checking that config keys, function signatures, and environment variables in docs still match.

## Usage

Invoke by name in Claude Code:

```
/techne:docsync
```

Default scope is `README.md` plus every tracked file under `docs/**/*.md`. Narrow scope by naming a file:

```
/techne:docsync docs/getting-started.md
```

The skill extracts checkable claims (commands, paths, signatures, config keys, version numbers, env vars), verifies each against the source, and outputs a drift report grouped by file. It also lists user-visible surface no doc mentions: commands, flags, exit codes, config keys, env vars, files written on your machine, and a plugin's skills, MCP tools and hooks. A page that links the file holding the detail, such as a skill's `SKILL.md`, covers it. Single-token swaps are safe to batch-apply on confirmation; prose rewrites are shown as full before/after diffs first.

## See also

- [`techne:docs-site`](docs-site.md): site mechanics (nav, deploy workflow, link integrity).
- [`techne:deslop`](deslop.md): slop in documentation prose unrelated to factual drift.
- [Conventions](../conventions.md#section-reference): `## repo` section in `.claude/skill-context.md` for CLI entrypoint and runner module.

## Full instructions

[`SKILL.md` on GitHub](https://github.com/ajbarea/techne/blob/main/plugins/techne/skills/docsync/SKILL.md) holds the full instructions Claude follows for this skill.
