# `techne:docsync`

Verifies documentation claims (CLI commands, file paths, config keys, function signatures, version numbers, environment variables) against the actual code, and proposes corrections.

## When to use

- Auditing `README.md`, `docs/*.md`, or similar for claims that no longer match reality.
- After a refactor that forgot to update the docs.
- Before publishing a release where stale claims would be embarrassing.

## What it checks

- **CLI commands** — does `make foo` still exist?
- **File paths** — does the doc claim a file lives where it actually does?
- **Config keys** — `zensical.toml`, `pyproject.toml`, `*.yaml` keys referenced in docs.
- **Function signatures** — Python/TS function references in docs vs actual definitions.
- **Version numbers** — pinned versions, badges, "requires X+" claims.
- **Environment variables** — `.env` keys referenced in docs.

## What it produces

A drift report grouped by file, with proposed corrections you can accept individually.

## Sibling

[`techne:docs-site`](docs-site.md) covers site mechanics (nav, links, assets). `docsync` covers prose accuracy.

## Reads

- `<repo>/README.md`, `<repo>/docs/**/*.md`
- The actual source files referenced.
