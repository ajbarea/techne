# `techne:audit`

Runs your repo's `make` targets in dependency order and reconciles terminal output against `logs/dev-*.log` archives.

## When to use

- Pre-PR check: validate the toolchain is clean before pushing.
- "Is the build clean?" / "Am I ready to push?"
- Verify make targets actually emit what their `logs/dev-<ts>-<cmd>.log` archives claim.
- After refactoring toolchain: detect silent failures or missing log lines.

## What it does

- Walks the repo's `Makefile` dependency graph (`setup` → `lint` → `test` → end-to-end).
- Runs each target and captures terminal output.
- Diffs the live terminal output against the most recent `logs/dev-*-<target>.log` archive.
- Surfaces any drift: silent failures, missing log lines, or commands that fall through dependencies.
- Reports pass/fail for each target with clear summaries.

Two modes:

| Mode | Use when |
|---|---|
| **full audit** | Pre-push or when reconciling stale logs. |
| **fast variant** | Quick lint+test sanity check. |

## Usage

```bash
# Full audit across all make targets
techne:audit

# Fast mode (lint + test only)
techne:audit --fast

# Audit a specific target
techne:audit --target test
```

After running, check the output summary. Green ✓ means the live output matches the archive. Red ✗ means drift detected — the skill will surface which lines diverged.

## Configuration

The skill reads two sources:

1. **`Makefile` dependency graph**: autodetected from the repo
2. **`.claude/skill-context.md`** (optional): override target order, skip targets, or specify custom log paths

Example skill context:

```yaml
audit:
  skip_targets:
    - docker-build  # skip if Docker not available
  target_order:
    - setup
    - lint
    - test
  log_directory: logs/
```

## Troubleshooting

**"No Makefile found"**: The skill requires `<repo>/Makefile`. For non-Make repos, create a thin Makefile wrapper that delegates to your actual build system.

**"Stale logs don't match live output"**: Archive logs are read-only. Regenerate them with `make <target> 2>&1 | tee logs/dev-$(date +%s)-<target>.log` to reset the baseline.

**"Target X failed but logs say it passed"**: This is the drift the skill is designed to catch. Review the failed target, fix it, and re-run.

## See also

- [`techne:ci-audit`](ci-audit.md) — audit GitHub Actions instead of local make targets.
- [`techne:docsync`](docsync.md) — verify docs claims (Makefile commands, paths) against reality.

## Reads

- `<repo>/Makefile`
- `<repo>/logs/dev-*.log`
- `<repo>/.claude/skill-context.md` (optional repo-local overrides)
