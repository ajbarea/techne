# `techne:elenchus`

Adversarial pre-merge code review. Drives `/code-review`, then runs the three passes diff-reading skips and applies a fixed bug-class rubric.

ἔλεγχος is the Socratic cross-examination: you do not confirm what the author meant, you hunt the one input that refutes the claim the change rests on.

## When to use

- Before merging any substantive change, especially a self-authored one.
- "Review like Ben's robot." / "Hunt edge cases." / "Break this before merge." / "Is this actually mergeable?"
- Anything destructive, security-sensitive, or governance-related, at `high` or `ultra` effort.

## Usage

```
/techne:elenchus
```

## Why it exists

The model that writes a change is a poor judge of it: the author reviews what they intended, under ship-it momentum, against a mental model that hides what the code actually does. The fix is not a smarter model but an independent reader running a fixed protocol against the whole repo, reproducing as it goes.

Independence is restored mechanically, not by willpower. `/code-review` at `high` spawns independent local agents; `ultra` runs a multi-agent cloud review. Never hand-read your own diff and call it reviewed.

## The three passes

`/code-review` does not force these, so elenchus adds them:

1. **Reproduce the load-bearing claim** — run it; check the null, empty, zero-rows, and boundary cells.
2. **Trace every consumer** of every changed symbol across the whole repo.
3. **Review against `main`**, not against the `+/-` of the diff.

## The bug classes it hunts

Reachable destructive operations, unmirrored guards across parallel code paths, migration crashes, and dead features that still pass CI — the classes that are invisible in a diff and obvious the moment the code is run or its callers traced.

## Configuration

Reads optional per-repo hints from the `## elenchus` section of `.claude/skill-context.md`: known destructive operations, load-bearing surfaces, reproduce recipes, and what "the feature works" means in this repo. Falls back to `## audit`, `## theoros`, then the `Makefile`. Runs without any config.

## See also

- [`techne:catchup`](catchup.md): re-read an item's threads before reviewing it, so you review against current feedback.
- [`techne:ci-audit`](ci-audit.md): CI-side failures and log noise.
- [Conventions](../conventions.md): `.claude/skill-context.md` section layout.
