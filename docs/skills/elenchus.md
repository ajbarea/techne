# `techne:elenchus`

Adversarial pre-merge code review. Drives `/code-review`, then runs the three passes diff-reading skips and applies a fixed bug-class rubric.

ἔλεγχος is the Socratic cross-examination: you do not confirm what the author meant, you hunt the one input that refutes the claim the change rests on.

## When to use

- Before merging any substantive change, especially a self-authored one.
- "Review it like a hostile reviewer." / "Hunt edge cases." / "Break this before merge." / "Is this actually mergeable?"
- Anything destructive, security-sensitive, or governance-related, at `high` or `ultra` effort.

## Usage

```
/techne:elenchus
```

## Why it exists

The model that writes a change is a poor judge of it: the author reviews what they intended, under ship-it momentum, against a mental model that hides what the code actually does. The fix is not a smarter model but an independent reader running a fixed protocol against the whole repo, reproducing as it goes.

Independence is restored mechanically, not by willpower. `/code-review` at `high` spawns independent local agents; `ultra` runs a billed multi-agent cloud review that you launch yourself, and the skill recommends it rather than starting it. Never hand-read your own diff and call it reviewed.

## The three passes

`/code-review` does not force these, so elenchus adds them:

1. **Reproduce the load-bearing claim** — run it; check the null, empty, zero-rows, and boundary cells.
2. **Trace every consumer** of every changed symbol across the whole repo.
3. **Review against `main`**, not against the `+/-` of the diff.

## The rubric

The review is held to a nine-cell rubric, so the classes that are invisible in a diff and obvious the moment the code is run or its callers traced do not get skipped:

1. Destructive-op reachability: the exact input that reaches each `rm -rf`, overwrite, `DROP`, truncate or force-push.
2. Parallel-path mirroring: whether a new path copied the guards and the regression tests, not only the structure.
3. Migration tolerance: whether state saved by the old code loads under the new code.
4. Reachability to the real surface: whether the change landed on the registered wrapper or shipped path, not an inner copy.
5. Boundary and empty inputs: null, empty string, zero rows, unset environment variable, missing file.
6. Looks-done is not is-done: whether the value path was checked end to end, beyond green tests and lint.
7. Flake versus real red: whether a failing check belongs to the change.
8. Claim and code drift: whether the PR description, comments and `Closes #N` match what the code does.
9. DRY and right altitude: whether the fix is the deep one or a special-case band-aid.

Every finding is marked CONFIRMED when it was reproduced or PLAUSIBLE when it was reasoned but not run. The review also states what it could not verify.

## What it posts

When someone else opened the PR, elenchus posts one distilled comment as the review of record: merge verdict, then blocking and should-fix findings, then the verified-clean list. Authorship is derived live from `gh`.

On your own PR it posts nothing. The report stays in the session for you to act on, and the PR stays free of a thread of you reviewing yourself.

The comment publishes the work rather than the machinery. It never claims the review was "independent" and never names the tooling that ran it, because neither is checkable by a teammate.

Skipped when there is no open PR, or when you say to keep the review local.

## Configuration

Reads optional per-repo hints from the `## elenchus` section of `.claude/skill-context.md`: known destructive operations, load-bearing surfaces, reproduce recipes, and what "the feature works" means in this repo. Falls back to `## audit`, `## theoros`, then the `Makefile`. Runs without any config.

## See also

- [`techne:catchup`](catchup.md): re-read an item's threads before reviewing it, so you review against current feedback.
- [`techne:ci-audit`](ci-audit.md): CI-side failures and log noise.
- [Conventions](../conventions.md): `.claude/skill-context.md` section layout.
