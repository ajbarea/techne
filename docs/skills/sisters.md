# `techne:sisters`

Cross-repo drift audit across the sister repos listed in `~/.claude/techne.toml`. Read-only inspection: CI action pins, toolchain pins in `pyproject.toml`, skill-context structural parity, GitHub merge settings, open PRs, and branch hygiene.

## When to use

- "Audit the sisters." / "Are the sisters in sync?" / "Check cross-repo drift."
- Before a coordinated multi-repo refactor or release.
- Spotting inconsistencies in action version pins, Python version envelopes, or merge settings across repos.

## Usage

Invoke by name in Claude Code:

```
/techne:sisters
```

The skill reads the active sister list from `~/.claude/techne.toml`, runs all checks in parallel, and outputs a single audit block grouped by category: merge settings, skill-context parity, action-pin drift, toolchain-pin drift, open PRs, stale branches, and local main sync.

The skill is read-only. It surfaces findings; it does not edit files, push branches, or change GitHub settings.

## Prerequisites

`~/.claude/techne.toml` must exist and list at least one active sister repo. If the file is missing or yields zero active sisters, the skill stops and explains.

See [Conventions](../conventions.md) for the `techne.toml` format.

## See also

- [`techne:ci-audit`](ci-audit.md): drill into a specific PR's failing checks after the sisters audit names it.
- [`techne:audit`](audit.md): audit a single repo's local `make` targets.
- [Conventions](../conventions.md): `techne.toml` configuration reference.
