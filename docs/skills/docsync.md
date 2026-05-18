# `techne:docsync`

Verifies documentation claims (CLI commands, file paths, config keys, function signatures, version numbers, environment variables) against the actual code, and proposes corrections.

## When to use

- Auditing `README.md`, `docs/*.md`, or similar for claims that no longer match reality.
- After a refactor that forgot to update the docs.
- Before publishing a release where stale claims would be embarrassing.
- Detecting drift between doc examples and actual API signatures.

## What it checks

- **CLI commands**: does `make foo` still exist? Is `techne:audit` the right syntax?
- **File paths**: does the doc claim a file lives where it actually does?
- **Config keys**: `zensical.toml`, `pyproject.toml`, `*.yaml` keys referenced in docs match the actual files?
- **Function signatures**: Python/TS function references in docs vs actual definitions (parameters, return types).
- **Version numbers**: pinned versions, badges, "requires Python 3.9+" claims.
- **Environment variables**: `.env` keys referenced in docs exist and are documented.
- **Code blocks**: example code snippets actually run without syntax errors.

## Usage

```bash
# Full doc sync audit
techne:docsync

# Check specific file(s)
techne:docsync docs/getting-started.md docs/api.md

# Generate report only, don't fix
techne:docsync --report-only
```

## Configuration

Optional `.claude/skill-context.md`:

```yaml
docsync:
  docs_paths:
    - "docs/**/*.md"
    - "README.md"
  check_code_blocks: true
  check_versions: true
  ignore_patterns:
    - "v*.*.*"  # skip version patterns
```

## What it produces

A drift report grouped by file, with proposed corrections you can accept individually:

```
docs/getting-started.md:42
  ❌ Config key "site_author" → should be "author"
  ✓ Fix: update to "author"

docs/configuration.md:15
  ❌ CLI command "techne:audit --verbose" → no such flag
  ✓ Fix: remove "--verbose" (not supported)
```

## Troubleshooting

**"False positives"**: Some dynamic code (e.g., `subprocess` calls, generated configs) may be flagged. Review each and ignore if needed.

**"Code block failed"**: The skill tries to parse code blocks as executable examples. Mark non-executable blocks with `{.no-test}` to skip.

## See also

- [`techne:docs-site`](docs-site.md) — covers site mechanics (nav, links, assets).
- [`techne:deslop`](deslop.md) — cleans up AI-generated slop in documentation prose.

## Reads

- `<repo>/README.md`, `<repo>/docs/**/*.md`
- The actual source files referenced (Makefile, config files, Python/TS code)
