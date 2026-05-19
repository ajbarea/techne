---
name: audit
description: Run the repo's make targets in dependency order (setup → lint → test → end-to-end) and verify each command's terminal output against its `logs/dev-<ts>-<cmd>.log` archive. Supports a full audit and a fast variant. Use whenever the user wants to validate the toolchain is clean, run lint+test locally before pushing, or reconcile terminal output against the dev-runner log archives — phrasings like "run the audit", "is the build clean", "check my toolchain", "am I ready to push", "make sure CI will pass", "verify make targets". Requires the `logs/dev-<ts>-<cmd>.log` archive convention; see `docs/conventions.md`.
disable-model-invocation: false
allowed-tools: Bash Glob Read Grep
---

# Audit

Run the full `make` audit in phases. Each phase builds on the previous; the ordering matters because the dev runner writes one archive per invocation, and granular runs must happen *before* their combined counterparts so you keep diffable per-tool logs.

## Repo context

```!
cat .claude/skill-context.md 2>/dev/null || echo "(no .claude/skill-context.md — abort and direct the user to \`docs/conventions.md\` in the techne docs for the canonical scaffolding template)"
```

The injected content above is the source of truth for this repo's toolchain. Read the `## audit` section (and `## repo` for context) and use those phases — do not fall back to hardcoded defaults. Specifically, expect it to supply:

- **Full-audit phase list** — ordered `make` targets, one per step, with a note on what each produces.
- **Fast-audit subset** — which subset of phases is the "am I ready to push" probe.
- **Stop-early phase** — which phase(s) aborting the rest if they fail.
- **Log archive format** — glob and summary-block origin (e.g. `logs/dev-<ts>-<cmd>.log`, `SUMMARY` block).
- **Do-not-run targets** — long-running / expensive targets the audit must skip.

## Modes

- **Full audit (default)** — every phase from the injected list. Run when the user says "run the full audit" or didn't specify.
- **Fast audit** — the fast subset from the injected list. Run when the user says "quick check", "fast audit", or only wants to know if lint + unit tests pass.

Pick the mode up front and stick with it — don't silently promote a fast audit to a full one mid-run.

## Run order

Follow the phase list from the injected `## audit` section, in order. Each phase writes one log archive. Run sequentially, not in parallel — commands share state (`.venv`, build artifacts, log files) and archives need clean separation.

## Per-command verification

Each invocation writes a timestamped archive under the log path from the injected context (typically `logs/dev-<YYYYMMDDTHHMMSS>-<cmd>.log`) plus a stable pointer at `logs/dev-latest.log`. The archive ends with a `SUMMARY` block:

```
==============================================================================
SUMMARY
==============================================================================
total elapsed : 3.96s
steps run     : 1
steps failed  : 0
overall rc    : 0

per-step:
  PASS  rc=0     3.93s  lint
==============================================================================
```

For each command:

1. Record the terminal exit code.
2. `Glob` `logs/dev-*-<command>.log`, sort by mtime, take the newest — that's this run's archive. (The glob deliberately skips `dev-latest.log` because it has no timestamp and gets overwritten every invocation.)
3. `Read` the tail (~30 lines) for the `SUMMARY` block.
4. Confirm:
   - Terminal exit code = 0
   - `overall rc    : 0` in SUMMARY
   - `steps failed  : 0` in SUMMARY
5. Note `total elapsed` and the per-step lines for the matrix.

If any check fails, mark the row FAIL and pull the failing step name(s) from the `per-step:` block. Subprocess output is captured as `[OUT  ]`-tagged lines earlier in the archive — grep by step name to isolate the failure.

**Do not read `logs/dev-latest.log`.** It is truncated at the start of every invocation, so after the final step it only reflects the most recent command. Use the timestamped archives.

**Timing sanity check.** If the phase list includes a combined end-to-end target (e.g. `make ci`) plus its granular sub-targets, compare the combined elapsed against the sum of the granulars. If the combined is significantly shorter (e.g. < 60% of the sum), something cached between runs and the granular numbers aren't independent measurements. Not a failure — but mention it in the verdict so the user knows the timing matrix is warm-cache, not cold.

## Cross-archive sweep

After all runs, one `Grep` across the fresh archives for error markers:

```
Grep pattern="\[ERR|FAIL|Traceback|exit 1|error\[" path="logs/" glob="dev-<today-prefix>*"
```

Zero hits = clean. Any hits = dump file:line for triage.

## Output format

A markdown table, then a verdict:

```
| # | Command | Terminal | Archive SUMMARY | Steps | Elapsed |
|---|---|---|---|---|---|
| 1 | `make clean` | 0 | rc=0 | 1 | 1.2s |
| 2 | `make check-env` | 0 | rc=0 | 1 | 0.3s |
| ... |

Full audit clean.
```

If the phase list has a distinguished end-to-end target with per-step detail (e.g. `make ci`), include its per-step block under the table so the user sees what CI would exercise. Match the verdict line to the mode: `Full audit clean.` / `Fast audit clean.` / `"N failures — rows X, Y — see logs/dev-<ts>-<cmd>.log"`. No preamble, no narration.

## Stop-early rules

- If the stop-early phase fails (per injected context — typically the setup phase), stop and report. The rest won't produce meaningful results.
- If a later phase fails, keep going — the user wants the full matrix even with some red rows.

## Scope

- Runs `make` targets from the injected phase list only.
- Reads only files under `logs/`.
- Never edits source, config, or docs.
- Never commits, pushes, or changes git state.
- Never runs do-not-run targets from the injected list (typically long-running servers, Docker stacks, or expensive baselines).
