---
name: reslop
description: Rewrite docstrings and comments by reading the actual implementation, call sites, and tests — produce grounded, factual prose instead of deleting slop. Sibling of /techne:deslop. Use when the user wants to replace overhyped or hallucinated documentation with accurate one- or two-line descriptions derived from what the code actually does.
disable-model-invocation: false
allowed-tools: Bash Glob Grep Read Edit Agent
---

# Reslop

Generative sibling of `/techne:deslop`. Where `/techne:deslop` deletes low-value prose, `/techne:reslop` *rewrites* it — grounded in the code, not in marketing instincts. On a path-scoped `/techne:deslop <path>` run, deslop auto-routes claim-bearing docstrings here; on a bare whole-repo sweep it lists them for you to run this directly.

## Repo context

```!
cat .claude/skill-context.md 2>/dev/null || echo "(no .claude/skill-context.md — rewrites will use conservative defaults for grounding numeric claims)"
```

The injected `## slop_ground_truth` section (if present) names the files or docs that ground quantitative claims for this repo. Never introduce a numeric claim that can't trace to one of those sources.

## Hard rules

1. **Never invent behavior.** If the code doesn't show it, don't claim it. No "thread-safe" unless the code actually synchronizes. No "idempotent" unless it demonstrably is. No "future-proof" ever.
2. **Never invent performance claims.** Rewrites must not introduce numeric speedups, throughput figures, latency bounds, or scale claims unless they are cited in the repo's `slop_ground_truth` (per injected context). If the original prose said "10× faster" and you can't find a measurement that supports it, strike the claim — don't rephrase it. The "Unsupported quantitative / comparative claims" section of `${CLAUDE_PLUGIN_ROOT}/_shared/hate-words.md` is the pattern list.
3. **No hate-words.** See `${CLAUDE_PLUGIN_ROOT}/_shared/hate-words.md` — the rewrite must not reintroduce slop you came to fix.
4. **Don't restate the signature.** Type annotations already tell the reader the types. Docstring prose is for purpose and non-obvious constraints.
5. **Prefer shorter.** One sentence beats three. If nothing needs saying, say nothing — hand the target back to `/techne:deslop` to delete outright.
6. **Match surrounding style.** If the module's other docstrings are one-liners, yours is too. If they use Google-style `Args:` / `Returns:`, match that — only if the arguments genuinely need explanation beyond their types.

## Workflow

1. **Scope.** Default to the file(s) the user named, or pending-change files if they said "rewrite the docstrings in my changes". Never touch files outside scope.

2. **For each target (function, class, module docstring):**
   - `Read` the implementation in full.
   - `Grep` for call sites inside the repo to see how it's actually used.
   - Check the adjacent test file for invariants the tests enforce.
   - Draft a docstring grounded in those three sources — no extra sources.

3. **Fan out only when scope is large.** If the target list spans >5 files, dispatch parallel `Explore` subagents — one per file. Brief each with the hard rules, the hate-words glossary, and the three read sources. Each subagent returns proposed rewrites as old→new diffs. Main agent consolidates.

4. **Present.** Group diffs by file, ask `apply all / apply selected / skip?`. On `--apply` or clearly "just do it", write directly with `Edit`.

## What triggers a rewrite

- Docstrings that trip the hate-word glossary.
- Docstrings that only restate the signature or repeat type annotations.
- Comments narrating WHAT a line does when the name already says.
- Module docstrings talking about "phases", "best practices", or AI-assistant audiences.
- Anything the user points at explicitly.

## What to leave alone

- Accurate docstrings under ~2 lines that don't use hate-words.
- Load-bearing WHY comments (same Keep list as `/techne:deslop`).
- Generated/stub files (`*.pyi`, protobuf output).
- Tests — their names are the documentation; don't over-describe.
- License headers, SPDX identifiers, shebangs.

## Output format

```
<package>/simulation_runner.py:120  _load_strategy
  old: """Robust strategy loader that elegantly handles all edge cases
         and seamlessly integrates with the federated simulation pipeline.
         Under the hood it imports the strategy module and instantiates it."""
  new: """Import a simulation strategy by name; raise ValueError if unknown."""
  why: original used marketing prose ("robust", "elegantly", "seamlessly") and restated mechanism the function body already shows.
```

Include the `why:` line only when the edit is borderline — skip it for obvious cuts.

## When to hand off to /techne:deslop

If the "fix" is just deleting the docstring entirely (because nothing about the function needs explaining and the name is clear), say so and let `/techne:deslop` handle it. Don't invent a rewrite to fill the slot.

## Why this skill is quiet

Output is the diffs. Don't narrate "I read the code and realized…" — show old → new, one `why:` line when borderline, nothing else.
