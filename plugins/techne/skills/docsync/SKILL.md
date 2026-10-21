---
name: docsync
description: Check a documentation file for drift against the actual codebase (CLI commands, file paths, config keys, function signatures, version numbers, environment variables) and correct it: applied directly on a solo repo, proposed for confirmation on a team repo. Use when the user wants to audit README.md, docs/*.md, or similar for claims that no longer match reality. Drift usually comes from refactors that forgot to update the docs.
disable-model-invocation: false
allowed-tools: Bash Glob Grep Read Edit Agent WebSearch WebFetch
---

# Docsync

`<plugin-root>` is the plugin's root directory, two levels above the directory holding this SKILL.md.

Compare documentation against the code it describes. Find where the docs say one thing and the code says another. Fixes are grounded in current code (or, for a claim about something outside the repo, a cited web source), not in what the docs *should* have said.

## Repo context

`/techne:docsync` audits a doc that may live in a **different repo than your CWD** (e.g. `/techne:docsync ../velocity-fl/README.md`), so read skill-context from the target's repo:

```bash
bash "<plugin-root>/_shared/skill_context.sh" <target-doc>   # with no path arg this reads the CWD repo
```

The output is headed by the repo root it read. Its `## repo` section names the CLI entrypoint and runner module the repo exposes (so command and `make`-target claims verify against the right code); `## slop_ground_truth` names where quantitative claims must trace. No `.claude/skill-context.md` at the target root → fall back to generic verification defaults.

## Checkable claims

- **Commands** — `uv sync`, `make lint`, `<cli-entrypoint> <cmd>` (from injected `repo.cli_entrypoint`). Verify the target exists in the Makefile / runner module / workflow.
- **File paths** — any path referenced in prose. Verify it exists.
- **Function / class signatures** — `SomeClass(config: Config, ...)`. Verify against source.
- **Config keys** — `[tool.flwr.app.config]`, `aggregation-strategy = "fedavg"`. Verify key + value against `pyproject.toml`.
- **Environment variables** — `UV_PROJECT_ENVIRONMENT`, `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24`. Verify the code actually reads them.
- **Version constraints** — Python / dependency pins. Verify against `pyproject.toml`, workflow files.
- **Internal links / anchors** — `[see strategies](strategies.md#fedavg)`. Verify target exists.
- **Exit codes and error messages** — Verify against the source that produces them.
- **Performance / comparative claims**: `45× faster`, `under 10 ms`, `scales to 100 clients`, `sub-millisecond aggregation`. Verify against the `slop_ground_truth` sources from the target repo's skill-context. If the claim is not traceable to a measurement there, it is drift. The fix is one of: cite the specific test, replace with the measured number, or delete. On a solo repo (step 5), apply the first two when the test or measurement exists; a claim with no measurement anywhere is listed as unresolved, never deleted unasked. Use the "Unsupported quantitative / comparative claims" section of `<plugin-root>/_shared/hate-words.md` as the grep-seed pattern list.

## Silence

A user-visible surface no doc mentions is drift too: the claim is missing, not wrong. Inventory the surface from the code, then look for each item in the docs in scope:

- commands and their flags (`bin/` scripts, `--help`, Makefile targets meant for users), exit codes and the error lines a user acts on
- config files and keys, environment variables the code reads, files the tool writes on the user's machine (privacy-relevant ones first)
- for a Claude Code plugin: every skill, MCP tool, hook or mod behavior, and `userConfig` key

A doc that links a file holding the detail covers that detail: a skill page that links its `SKILL.md` covers the skill's internal steps, and a page that quotes `--help` covers the flags it lists. Propose the link, not a paraphrase, since a second copy drifts. Report each gap with the surface's source `file:line` and the doc where it belongs. Test-only knobs and internal helpers are not user surface.

## Ignore

- Prose / marketing copy that makes **no quantitative claim** ("X orchestrates federated learning runs"). Not a checkable claim.
- BUT: prose that makes a **quantitative performance or scale claim** IS checkable — see "Performance / comparative claims" above. Don't wave those through as marketing.
- Roadmap language ("we plan to", "coming soon"). Aspirational, not drift.
- Code examples that are intentionally illustrative.
- Screenshots, images, external URLs.
- **Static-site-generator pretty-URLs.** Docs built with MkDocs / Zensical / Docusaurus link to directory-style built URLs (`topic/`), not the source `.md`. A link to `topic/` for a `topic.md` source resolves on the built site; "correcting" it to `topic.md` would 404. Verify against the build's URL convention, not the source filename.
- **Plugin-namespaced slash commands.** For a Claude Code plugin command defined in `commands/<name>.md`, the canonical invocation is `/<plugin>:<name>` (e.g. `/myplugin:config`). The bare `/<name>` or the filename is not the reference, and the `/<plugin>:` prefix is not drift.

## Workflow

1. **Scope.** Input is one doc file or a directory. Default if the user didn't specify: `README.md` + every tracked file under `docs/**/*.md`. For directory scope, fan out (see [Fan-out pattern](#fan-out-pattern)).

   Out of scope — hand off to `/techne:docs-site` instead: `zensical.toml` config drift, `.github/workflows/docs.yml` deploy wiring, `docs/stylesheets/` / `docs/javascripts/` asset maintenance, rendered-site link checks. `/techne:docsync` is claim verification inside markdown prose; docs-site infrastructure is a different skill.

2. **Extract claims.** For the doc in scope, list every checkable claim with its exact string and line number. Categorize by the list above.

   Then take the user-visible surface inventory from the code (see [Silence](#silence)) and mark each item the docs in scope never mention.

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

5. **Apply.** Run `python3 "<plugin-root>/_shared/repo_kind.py" <path>` once for each repo the audited docs live in, passing one audited doc's path in that repo (with the default scope, the target repo's `README.md`). It prints `solo: <why>` or `team: <why>`, and anything it cannot settle reads as team. Put that line at the top of the drift report, so the act-or-ask choice is visible.
   - **Solo repo: act, don't ask.** In the same turn, apply every fix the evidence settles: the current code, config, lockfile or test, or, for a claim about a tool, version or service outside the repo, a web source you fetched and cite in the report. That covers single-token swaps and prose rewrites alike; the report shows each prose change as before and after, with its evidence. A claim that neither the code nor research settles stays as written and is listed as unresolved, with what you checked. It is not a question for the user.
   - **Team repo: ask.** Single-token swaps (command names, paths, signatures, config values) batch-apply on the user's confirmation. Prose rewrites are shown as a full before/after diff first; never silently reword a sentence.

## Fan-out pattern

For a whole `docs/` directory, spawn one `Explore` subagent per doc file. Each returns a drift report for its file. Main agent consolidates and presents grouped by file, then applies per step 5: on a solo repo it applies, on a team repo it asks `apply all / apply selected / skip?`.

## Don't touch

- Doc files the user didn't name or imply.
- Generated doc output (`site/`).
- Changelog / release notes — they're historical; drift there is a feature, not a bug.
- Third-party API documentation mirrored into this repo.

## While you're in there

A doc update is also a chance to trim slop. If a fix requires rewriting a sentence, apply the `<plugin-root>/_shared/hate-words.md` filter before you commit to the new wording — don't let the rewrite reintroduce "seamless", "effortlessly" and friends. If the file has heavy slop unrelated to the drift, mention it once and suggest running `/techne:deslop` after — don't quietly expand scope.

## Why this skill is quiet

Output is the drift report and the edits (on a team repo, after confirmation). No narration of the verification process, just `claim → reality → fix`.
