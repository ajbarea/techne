# `techne:reslop`

Rewrites docstrings and comments by reading the actual implementation, call sites, and tests. Produces grounded, factual prose instead of deleting slop.

## When to use

- You want to replace overhyped or hallucinated documentation with accurate one- or two-line descriptions derived from what the code actually does.
- A function's docstring contradicts its behavior and needs a rewrite, not a delete.
- You want fresh docstrings that cite the real input/output shape, not the AI-generated wishful thinking.

## How it differs from `deslop`

| Skill | What it does |
|---|---|
| [`techne:deslop`](deslop.md) | Identifies slop, proposes tightened (or removed) rewrites. |
| `techne:reslop` | Reads the implementation and produces grounded replacement prose. |

Use `deslop` first for triage. Use `reslop` when the answer is "this needs better prose, not less prose."

## What it reads

- The function or class body.
- Call sites (who invokes it, with what arguments).
- Tests (what inputs and outputs are actually exercised).
- Adjacent docs (for tone consistency).

## What it produces

Updated docstrings as a diff. You review and commit.
