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
6. Looks done is not done (class `looks-done-not-done`): whether the value path was run end to end, beyond green tests and lint, whether a test mocks the very seam it claims to cover, and whether each gate has been seen to fire.
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

Each round is a fresh reader, handed the diff and the open findings, never a resumed one. Review, fix and review again while a round has a reproduced blocking or should-fix finding on an input that a caller in the repo or a documented usage can produce. The PR's owner makes each fix, with a regression test in CI where the finding is testable. Each round tries once to reproduce every unproven blocking or should-fix finding; one that still fails is recorded as open and holds the merge. Open findings go in the review comment on someone else's PR, or in the linked issue on your own when one exists, so a waiting PR says why it waits; "keep it local" keeps them in the session. A class that comes back in a later round is not patched again: the fix becomes structural (one shared helper, a canonical format, delegating to the real parser), with a test that sweeps the class. A long loop pauses for your go-ahead: past the budget you set, in rounds or reviewer working time (unset, it follows the stakes: three rounds for docs and small edits, the first clean round within five for substantive code and paper changes, until clean for registered study rules, governance, security, destructive operations and whatever you ask; fixes made after the last round get one verify round), or when two rounds in a row find only bugs the previous fix introduced. After merge, the catalog learns from the review without anyone folding it in by hand (next section).

## The findings ledger

Every reader appends each blocking or should-fix finding (class, repo, PR, round, one line) to a machine-wide, append-only ledger, `~/.local/state/elenchus/findings.jsonl`, so every session on the machine learns from every other one. It never leaves the machine, so it may name private repos.

- **Before review**, `ledger.py checklist` lists the classes reviewers found in two or more PRs in the last week. The author walks those first.
- **Once a day**, `foldback.sh` reads what the ledger gained and opens one catalog PR to techne. It adds a dated incident for each finding of a catalogued class, and a full entry for each `new:` class found in two or more PRs, deduplicated against the classes already there. It keeps each incident's source (`repo#PR rN`, date), and writes only what tests and `make guards` pass.
- **Three PRs in a week** opens a "Mechanical check: <class>" issue for a lint rule, test or hook (catalogued classes only, so no free-text name reaches a public issue). When it is closed as completed, the next fold marks the class **Retired**, and readers stop spending attention on it.
- **Safety.** The curation session runs restricted, with no shell, settings, hooks or MCP servers, and edits only the catalog. The job pushes only when the catalog is the sole changed file, its tests pass and the private-name scan ran clean. While a fold PR is open, the next fold waits.

The design follows shared lesson banks for code agents ([LessonL](https://arxiv.org/pdf/2505.23946)). Each memory carries its source, because stale memories were the main risk in [GitHub Copilot's cross-agent memory](https://github.blog/2026-01-09-building-an-agentic-memory-system-for-github-copilot). Curation is a separate pass that dedupes rather than appends ([SAP](https://arxiv.org/pdf/2608.00122): about half of raw contributions survive; [Spark](https://arxiv.org/pdf/2511.08301)).

To run the fold daily, install two systemd user units, then `systemctl --user enable --now elenchus-foldback.timer`:

```ini
# ~/.config/systemd/user/elenchus-foldback.service
[Unit]
Description=Fold the elenchus findings ledger into one techne catalog PR
After=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/bin/bash -lc 'exec bash "$(ls -td "$HOME"/.claude/plugins/cache/techne/techne/*/skills/elenchus/scripts | head -1)/foldback.sh" "$HOME/<your techne clone>"'
```

```ini
# ~/.config/systemd/user/elenchus-foldback.timer
[Unit]
Description=Fold the elenchus findings ledger daily

[Timer]
OnCalendar=*-*-* 06:30
Persistent=true

[Install]
WantedBy=timers.target
```

The job logs to `~/.local/state/elenchus/foldback.log`. It needs `gh` signed in, `uv` and `claude`.

## Configuration

Reads optional per-repo hints from the `## elenchus` section of `.claude/skill-context.md`: known destructive operations, load-bearing surfaces, reproduce recipes, and what "the feature works" means in this repo. Falls back to `## audit`, `## theoros`, then the `Makefile`. Runs without any config.

## See also

- [`techne:catchup`](catchup.md): re-read an item's threads before reviewing it, so you review against current feedback.
- [`techne:ci-audit`](ci-audit.md): CI-side failures and log noise.
- [Conventions](../conventions.md#section-reference): `.claude/skill-context.md` section layout.

## Full instructions

[`SKILL.md` on GitHub](https://github.com/ajbarea/techne/blob/main/plugins/techne/skills/elenchus/SKILL.md) holds the full instructions Claude follows for this skill.
