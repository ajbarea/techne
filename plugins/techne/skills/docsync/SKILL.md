---
name: docsync
description: Check a documentation file for drift against the actual codebase — CLI commands, file paths, config keys, function signatures, version numbers, environment variables — and propose corrections. Use when the user wants to audit README.md, docs/*.md, or similar for claims that no longer match reality. Drift usually comes from refactors that forgot to update the docs.
disable-model-invocation: false
allowed-tools: Bash Glob Grep Read Edit Agent
---

# Docsync

Compare documentation against the code it describes. Find where the docs say one thing and the code says another. Propose fixes grounded in current code, not in what the docs *should* have said.

## Repo context

`/techne:docsync` audits a doc that may live in a **different repo than your CWD** (e.g. `/techne:docsync ../velocity-fl/README.md`). Skill-context must therefore come from the *target's* repo, not CWD. A load-time `` !`cat .claude/skill-context.md` `` injection can't do this — it runs before the target path is parsed, so it always reads CWD. Resolve the repo root from the doc-path argument instead:

```bash
git -C "$(dirname "<target-doc>")" rev-parse --show-toplevel   # target repo root; with no path arg this resolves to the CWD repo
```

Then `Read` `<root>/.claude/skill-context.md`. Its `## repo` section names the CLI entrypoint and runner module the repo exposes (so command and `make`-target claims verify against the right code); `## slop_ground_truth` names where quantitative claims must trace. No `.claude/skill-context.md` at the target root → fall back to generic verification defaults.

## Checkable claims

- **Commands** — `uv sync`, `make lint`, `<cli-entrypoint> <cmd>` (from injected `repo.cli_entrypoint`). Verify the target exists in the Makefile / runner module / workflow.
- **File paths** — any path referenced in prose. Verify it exists.
- **Function / class signatures** — `SomeClass(config: Config, ...)`. Verify against source.
- **Config keys** — `[tool.flwr.app.config]`, `aggregation-strategy = "fedavg"`. Verify key + value against `pyproject.toml`.
- **Environment variables** — `UV_PROJECT_ENVIRONMENT`, `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24`. Verify the code actually reads them.
- **Version constraints** — Python / dependency pins. Verify against `pyproject.toml`, workflow files.
- **Internal links / anchors** — `[see strategies](strategies.md#fedavg)`. Verify target exists.
- **Exit codes and error messages** — Verify against the source that produces them.
- **Performance / comparative claims** — `45× faster`, `under 10 ms`, `scales to 100 clients`, `sub-millisecond aggregation`. Verify against the `slop_ground_truth` sources from the target repo's skill-context. If the claim is not traceable to a measurement there, it is drift — propose one of: cite the specific test, replace with the measured number, or delete. Use the "Unsupported quantitative / comparative claims" section of `${CLAUDE_PLUGIN_ROOT}/_shared/hate-words.md` as the grep-seed pattern list.

## Ignore

- Prose / marketing copy that makes **no quantitative claim** ("X orchestrates federated learning runs"). Not a checkable claim.
- BUT: prose that makes a **quantitative performance or scale claim** IS checkable — see "Performance / comparative claims" above. Don't wave those through as marketing.
- Roadmap language ("we plan to", "coming soon"). Aspirational, not drift.
- Code examples that are intentionally illustrative.
- Screenshots, images, external URLs.

## Workflow

1. **Scope.** Input is one doc file or a directory. Default if the user didn't specify: `README.md` + every tracked file under `docs/**/*.md`. For directory scope, fan out (see [Fan-out pattern](#fan-out-pattern)).

   Out of scope — hand off to `/techne:docs-site` instead: `zensical.toml` config drift, `.github/workflows/docs.yml` deploy wiring, `docs/stylesheets/` / `docs/javascripts/` asset maintenance, rendered-site link checks. `/techne:docsync` is claim verification inside markdown prose; docs-site infrastructure is a different skill.

2. **Extract claims.** For the doc in scope, list every checkable claim with its exact string and line number. Categorize by the list above.

3. **Verify.** For each claim, run the appropriate check:
   - Command → `Grep` the Makefile / CLI entrypoint module / workflow for the target.
   - Path → `Glob` or `Read`.
   - Signature → `Grep` for the definition, compare.
   - Config key → `Read` `pyproject.toml` (or the relevant config), compare value.
   - Env var → `Grep` for `os.environ` / `os.getenv` / equivalent.

4. **Report drift.** One entry per mismatch:

   ```
   README.md:42
     claim:   `pip install -e .[dev]`
     reality: dev deps live under [dependency-groups] in pyproject.toml;
              install is `uv sync` (or `make setup`)
     fix:     replace with `uv sync`
   ```

5. **Apply with care.**
   - Single-token swaps (command names, paths, signatures, config values) are safe to batch-apply on confirmation.
   - Prose rewrites get shown as a full before/after diff first — never silently reword a sentence.

## Fan-out pattern

For a whole `docs/` directory, spawn one `Explore` subagent per doc file. Each returns a drift report for its file. Main agent consolidates and presents grouped by file, then asks `apply all / apply selected / skip?`.

## Don't touch

- Doc files the user didn't name or imply.
- Generated doc output (`site/`).
- Changelog / release notes — they're historical; drift there is a feature, not a bug.
- Third-party API documentation mirrored into this repo.

## While you're in there

A doc update is also a chance to trim slop. If a fix requires rewriting a sentence, apply the `${CLAUDE_PLUGIN_ROOT}/_shared/hate-words.md` filter before you commit to the new wording — don't let the rewrite reintroduce "robust", "seamless", "effortlessly" and friends. If the file has heavy slop unrelated to the drift, mention it once and suggest running `/techne:deslop` after — don't quietly expand scope.

## Why this skill is quiet

Output is the drift report and, on confirmation, the edits. No narration of the verification process — just `claim → reality → fix`.
