---
description: "Review a change adversarially before merge: reproduce the load-bearing claim, trace every consumer, and walk a bug-class rubric."
---

# `techne:elenchus`

Adversarial pre-merge code review. Drives an independent review sized to the change's risk (a fresh reviewer, plus `/code-review` at `high` for a risky change), then runs the three passes diff-reading skips and applies a fixed bug-class rubric.

Part of [techne](../plugins/techne.md): `/plugin install techne@techne`, then `/techne:setup`.
ἔλεγχος is the Socratic cross-examination: you do not confirm what the author meant, you hunt the one input that refutes the claim the change rests on.

## When to use

- Before merging any substantive change, especially a self-authored one.
- "Review it like a hostile reviewer." / "Hunt edge cases." / "Break this before merge." / "Is this actually mergeable?"
- Anything destructive, security-sensitive, or governance-related, at the high tier (or `ultra`).

## Usage

```
/techne:elenchus
```

## Why it exists

The model that writes a change is a poor judge of it: the author reviews what they intended, under ship-it momentum, against a mental model that hides what the code actually does. The fix is not a smarter model but an independent reader running a fixed protocol against the whole repo, reproducing as it goes.

Independence is restored mechanically, not by willpower. On your own change you do not review it: elenchus dispatches a fresh reviewer that never saw the authorship story, relays its report, and runs the review loop. On someone else's change you are the independent reader and run every step yourself. The cost scales with risk. The high tier adds `/code-review` at `high`, which spawns independent local agents, for any change that is a new subsystem, touches persisted state, crosses a security, privacy, access or governance boundary, ships to a sensitive target, or adds a destructive operation or feeds one, whatever the diff's size; `ultra` runs a billed multi-agent cloud review that you launch yourself, and the skill recommends it rather than starting it. Everything else gets the light tier, the fresh reviewer alone. When unsure, the high tier. A review whose agents errored is rerun, not counted as clean. Never hand-read your own diff and call it reviewed.

## The three passes

`/code-review` does not force these, so elenchus adds them:

1. **Reproduce the load-bearing claim**: run it; check the null, empty, zero-rows, and boundary cells.
2. **Trace every consumer** of every changed symbol across the whole repo.
3. **Review against `main`**, not against the `+/-` of the diff.

## The bug-class catalog

The review walks one [catalog of bug classes](https://github.com/ajbarea/techne/blob/main/plugins/techne/skills/elenchus/references/bug-classes.md), each with its symptom, the question that catches it, the guard that prevents it, and dated incidents. Nine core classes are walked on every review, so the bugs that are invisible in a diff and obvious the moment the code runs or its callers are traced do not get skipped:

1. Destructive-op reachability (class `destructive-op-reachability`): the exact input that reaches each `rm -rf`, overwrite, `DROP`, truncate or force-push.
2. Parallel-path mirroring (class `unmirrored-parallel-guard`): whether a new path copied the guards and the regression tests, not only the structure.
3. Migration tolerance (class `migration-tolerance`): whether state saved by the old code loads under the new code.
4. Reachability to the real surface (class `unreached-surface`): whether the change landed on the registered wrapper or shipped path, not an inner copy.
5. Boundary and empty inputs (class `boundary-input`): null, empty string, zero rows, unset environment variable, missing file, the largest value a caller can pass.
6. Looks done is not done (class `looks-done-not-done`): whether the value path was run end to end, beyond green tests and lint, and whether a test mocks the very seam it claims to cover.
7. Flake versus real red (class `flake-vs-real-red`): whether a failing check belongs to the change.
8. Claim and code drift (class `claim-code-drift`): whether the PR description, comments and `Closes #N` match what the code does.
9. DRY and right altitude (class `wrong-altitude`): whether the fix is the deep one or a special-case band-aid.

The learned classes are walked where the diff touches their trigger: a hook's model of the shell (class `shell-semantics-mismatch`), a guard no test can fail (class `vacuous-guard`), an agent's own command exhausting the machine (class `unbounded-agent-resource`), and the rest. The reviewer tags every blocking or should-fix finding with its class, or `new:` with a name when none fits.

## Before you ask for review

The author walks the catalog's questions against the diff before the first round. Code that parses another language or format (bash, a regex, TOML, paths) gets a differential or property test against the real implementation, and each guard gets a mutation check: flip its condition and confirm a test goes red. Findings the author defers go in a ledger in the PR body, or in IMPL.md before a PR, which reviewers read and do not re-report.

Every finding is marked CONFIRMED when it was reproduced or PLAUSIBLE when it was reasoned but not run. The review also states what it could not verify.

## What it posts

When someone else opened the PR, elenchus posts one distilled comment as the review of record: merge verdict, then blocking and should-fix findings, then the verified-clean list. Authorship is derived live from `gh`.

On your own PR it posts nothing on the PR. The report stays in the session for you to act on, and the PR stays free of a thread of you reviewing yourself.

The comment publishes the work rather than the machinery. It never claims the review was "independent" and never names the tooling that ran it, because neither is checkable by a teammate.

Skipped when there is no open PR, or when you say to keep the review local.

## When the review loop ends

Review, fix and review again while a round has a reproduced blocking or should-fix finding on an input that a caller in the repo or a documented usage can produce. The PR's owner makes each fix, with a regression test in CI where the finding is testable. There is no fixed round count. Each round tries once to reproduce every unproven blocking or should-fix finding; one that still fails is recorded as open and holds the merge. Open findings go in the review comment on someone else's PR, or in the linked issue on your own when one exists, so a waiting PR says why it waits; "keep it local" keeps them in the session. A class that comes back in a later round is not patched again: the fix becomes structural (one shared helper, a canonical format, delegating to the real parser), with a test that sweeps the class. A long loop pauses for your go-ahead: past your budget for the reviewer's working time (three rounds when unset, unless you asked for review until clean), or when two rounds in a row find only bugs the previous fix introduced. After merge, the author adds each new class and each incident to the catalog, in the same PR or a follow-up.

## Configuration

Reads optional per-repo hints from the `## elenchus` section of `.claude/skill-context.md`: known destructive operations, load-bearing surfaces, reproduce recipes, and what "the feature works" means in this repo. Falls back to `## audit`, `## theoros`, then the `Makefile`. Runs without any config.

## See also

- [`techne:catchup`](catchup.md): re-read an item's threads before reviewing it, so you review against current feedback.
- [`techne:ci-audit`](ci-audit.md): CI-side failures and log noise.
- [Conventions](../conventions.md#section-reference): `.claude/skill-context.md` section layout.

## Full instructions

[`SKILL.md` on GitHub](https://github.com/ajbarea/techne/blob/main/plugins/techne/skills/elenchus/SKILL.md) holds the full instructions Claude follows for this skill.
