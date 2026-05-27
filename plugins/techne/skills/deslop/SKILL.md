---
name: deslop
description: Scan the codebase for AI-generated slop in comments and docstrings — temporal markers, self-referential AI framing, narrative WHAT-comments, marketing padding — and propose tightened rewrites, routing claim-bearing docstrings that need a code-grounded rewrite to its sibling /techne:reslop. Use when the user wants to audit pending changes or the whole codebase for verbose, low-value commentary left by other assistants (Copilot, Gemini, GPT, etc.).
disable-model-invocation: false
allowed-tools: Bash Glob Grep Read Edit Agent
---

# Deslop

Find and remove low-value, AI-generated commentary in source files. Keep comments that explain a non-obvious *why*; trim or delete everything else.

## Repo context

```!
cat .claude/skill-context.md 2>/dev/null || echo "(no .claude/skill-context.md — skill will use generic defaults for skip paths and scan split)"
```

The injected `## scan_scope` section (if present) supplies this repo's skip-path list and subagent scan-area split. The `## slop_ground_truth` section (if present) names the repo's source of truth for performance/scale claims — used when filtering unmeasured numeric claims. Use those over the generic defaults below when available.

## What counts as slop

**Cut:**

- **Temporal markers** — "(April 2026 best-practice order)", "as of 2024", "latest version". These rot.
- **Self-referential AI framing** — "designed so an AI assistant who did not see the live terminal can reconstruct", "AI-DEBUG HINTS", "helps LLMs understand", "for model consumption".
- **Narrative WHAT-comments** — `# Now we iterate through the list`, `# Return the result`. If the identifier already tells you, the comment is dead weight.
- **Marketing language** — "robust", "comprehensive", "elegant", "best-practice", "production-ready", "seamless", "powerful", "effortlessly", "with ease", "painlessly", "simply", "just" (as filler), "out of the box", "blazingly", "lightning-fast", "battle-tested", "state-of-the-art", "cutting-edge" when describing your own code. See `${CLAUDE_PLUGIN_ROOT}/_shared/hate-words.md` for the canonical cross-skill list.
- **Unmeasured performance claims** — "10× faster", "sub-millisecond", "scales to thousands of clients", "near-zero overhead" in comments/docstrings that don't cite a measurement. The source of truth is whatever `slop_ground_truth` names in the injected skill-context; any numeric performance/scale claim not traceable there is slop — propose deletion, or a link to the measurement. See the "Unsupported quantitative / comparative claims" section in `${CLAUDE_PLUGIN_ROOT}/_shared/hate-words.md`.
- **Task-context rot** — "added for issue #123", "fix for the auth bug", `TODO(copilot):`. Belongs in the PR description, not the source.
- **Signature restatement** — docstrings that only repeat the type annotations in prose.
- **Excessive hedging** — "we might want to", "in some cases this could potentially", "it's important to note that".
- **Step-by-step narration in docstrings** — "First we do X. Then we do Y. Finally we do Z." when the function body already shows that.
- **Emoji decoration** — emoji in source comments/docstrings unless the user asked for it.

**Keep:**

- **Why-comments** — hidden constraints, subtle invariants, workarounds for specific bugs, behavior that would surprise a reader.
- **Short public-API docstrings** — one or two sentences on what a function is for, because callers don't read the body.
- **Non-obvious references** — RFC links, load-bearing issue links, citations, license headers.

Rule of thumb: if deleting the comment wouldn't confuse a future reader, delete it.

## Grep seed patterns

The canonical pattern list lives at **`${CLAUDE_PLUGIN_ROOT}/_shared/hate-words.md`** — update *that* file when adding new patterns, not this one. Subagents should `Grep` every section of the shared glossary (case-insensitive, across the scoped paths) to build a candidate list fast, then filter each hit against the Cut/Keep rules above.

A hit is *not* automatically slop — it's just a cheap starting point. "Robust" inside a user-facing error message is fine; "robust implementation" in a docstring is slop.

User-specific calibration — patterns the user flags most often from their own prompt-engineering flow:

- `best[- ]practice` — "based on April 2026 best practice"
- `PHASE ?\d` — "PHASE 1-A", "Phase 2 of the refactor"

## Workflow

1. **Scope.** Default to the whole repo minus vendored/generated paths. Use the skip-path list from the injected `scan_scope.skip` (fall back to: `.venv/`, `node_modules/`, `dist/`, `build/`, `site/`, `out/`, `__pycache__/`, `.ruff_cache/`, `.pytest_cache/`, `.hypothesis/`, `target/`, `uv.lock`, `Cargo.lock`, `docs/assets/`, `logs/`). If the user passed a path (e.g. `/techne:deslop scripts/`), restrict to that.

2. **Fan out with Explore subagents in parallel.** One subagent per area, all dispatched in a single message. Use the split from the injected `scan_scope.areas` — typical shape:
   - Core package (e.g. `<package>/**/*.py`)
   - Scripts (`scripts/**/*.py`)
   - Tests (`tests/**/*.py`)
   - Native / other-language code if applicable (`<crate>/src/**/*.rs`, etc.)
   - Frontend (`frontend/**/*.{ts,tsx,js,jsx,vue,svelte}`) — only if the repo has one
   - Config/build (`pyproject.toml`, `Makefile`, `.github/workflows/**`, `Cargo.toml`, `zensical.toml`, etc.)
   - Docs (only if user asks — docs prose is a different genre): `docs/**/*.md`

   Brief each subagent with the slop/keep lists, the grep seed patterns, and the calibration examples below. Tell it to start with the grep pass for recall, then read surrounding context to confirm each hit against the Cut/Keep filter before reporting. Ask for a compact report: `file:line` + the offending text + a proposed replacement (or `delete`). Cap each report at ~30 findings so context stays cheap.

3. **Consolidate.** Merge findings grouped by file. Drop duplicates and obvious false positives. If two subagents disagree on the same line, prefer the less aggressive edit.

4. **Present, then apply on request.** Default: show the list, then ask `apply all / apply selected / skip?`. If the user invoked the skill with `--apply` or clearly said "just fix them", skip the confirmation and run `Edit` directly. Claim-bearing docstrings that need a code-grounded rewrite are routed to reslop first — see **Handoff** below.

## Handoff to /techne:reslop

Each hit gets one of three verdicts: **delete** (the name already says it), **trim in place** (the prose is accurate, just wordy — compress it on surface patterns), or **keep** (load-bearing why). A fourth case is reslop's, not deslop's:

- A keep-worthy docstring whose **claims can't be verified from the comment alone** — behavioral assertions ("thread-safe", "idempotent"), perf/scale numbers, or vague marketing wrapped around a real function. Surface-trimming would just relabel an unchecked claim; the honest fix is reslop's code-grounded rewrite (read the implementation + call sites + tests, then state what's true).

Route those, gated on scope:

- **Path-scoped run** (`/techne:deslop <path>`) → hand the grounding candidates to reslop: invoke `/techne:reslop <files>`, or follow `../reslop/SKILL.md` directly (read each target's implementation + call sites + tests; obey its hard rules), then fold the rewrites into the consolidated diff. Whether they auto-apply follows the same `--apply` / "just fix them" rule as deslop's own edits.
- **Whole-repo / fleet sweep** (no path) → do **not** fire reslop; list the candidates as a `/techne:reslop <files>` to-do so the cheap sweep stays cheap.
- **Count guard:** even when path-scoped, if more than ~10 docstrings need grounding, report the count and confirm before running them all — a deep read per symbol adds up.

The reverse already holds: when reslop lands on something that should just be deleted, it hands back here rather than inventing filler.

## Don't touch

- Comments the user has already reviewed and kept in prior turns.
- License headers, SPDX identifiers, shebangs, `# noqa`/`# type: ignore`/`# pragma` directives.
- Test fixtures that intentionally contain sample text.
- `.pyi` stub files — terse headers are expected there.
- Anything under the skip paths listed above.

## Calibration examples

Use these to tune your threshold.

**Slop (removed):**

- `Tooling (April 2026 best-practice order):` → `Tooling:`
- `"The log is designed so an AI assistant who did not see the live terminal can reconstruct what happened..."` → trimmed to a factual description of what the log contains
- `AI-DEBUG HINTS` section header → `DEBUG HINTS`, body shortened
- `"# Lightning-fast aggregation, sub-millisecond per round."` → delete (unmeasured; no matching entry in the repo's `slop_ground_truth`). If a number is load-bearing, replace with the measured figure and cite the specific test.

**Kept (not slop):**

- `# The handle intentionally outlives this method (one file per session), so a context-manager pattern doesn't fit — atexit closes it instead.` — non-obvious design choice.
- `# Fixers may legitimately return non-zero when nothing can be fixed.` — explains why `except`-continue is correct.
- `# ty has no auto-fix; it runs in the check phase only.` — explains asymmetric tool behavior.

## Output format

When presenting findings, group by file, show line number, offending text, and proposed edit:

```
scripts/<runner>.py
  L55   # ANSI colours; Windows 10+ terminals handle these fine, but fall back gracefully.
    →   # ANSI colour codes with a no-color fallback.

<package>/simulation_runner.py
  L12   # ---------------------------------------------------------------------------
  L13   # Lazy-loaded strategy resolver so the package is still importable even
  L14   # if optional strategies fail to import at module load time.
  L15   # ---------------------------------------------------------------------------
    →   delete (explained by the function name _load_strategy)
```

Then one line: `Apply all / apply selected (say which) / skip?`

## Why this skill is quiet

The output is the findings and the edits. Don't narrate "I looked at the file and noticed…" — show `file:line → replacement`. If a finding is borderline, one short phrase next to it ("borderline — kept for now") is enough. No preamble, no summary paragraph.
