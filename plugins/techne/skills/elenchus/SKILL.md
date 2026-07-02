---
name: elenchus
description: Adversarial pre-merge code review — drive /code-review, then run the three passes diff-reading skips (reproduce the load-bearing claim, trace every consumer, review against the whole repo) and the bug-class rubric that catches reachable destructive ops, unmirrored parallel-path guards, migration crashes, and dead features that still pass CI. Use before merging a substantive change, when asked to "review like Ben's robot", "hunt edge cases", "break this before merge", "is this actually mergeable", or to give a self-authored change an independent pass. Reads optional per-repo hints from the `## elenchus` section of `.claude/skill-context.md`.
disable-model-invocation: false
allowed-tools: Bash Read Grep Glob Task Skill
---

# Elenchus

ἔλεγχος — the Socratic cross-examination: you do not confirm what the author meant, you hunt the one input that **refutes the claim the change rests on**. A change is innocent of nothing until you have tried to break it and failed. You are the independent adversary in the chair, never the author defending the diff.

This skill exists because the same model that writes a change is a poor judge of it: the author reviews what they *intended*, under ship-it momentum, against a mental model that hides what the code actually does. The fix is not a smarter model — it is an **independent reader running a fixed adversarial protocol against the whole repo, reproducing as it goes**. That is the entire method. Everything below operationalizes it.

## The cardinal rule: independence is mechanical

If you (or this session) authored the change under review, you are the wrong reviewer **by construction** — you cannot un-know what it was supposed to do. Restore independence with tools, not willpower:

- **Primary:** run `/code-review` at `high` (spawns independent local review agents) or `ultra` (multi-agent cloud review) so the verdict comes from a context that never wrote the code. Scale to risk: `ultra`/`high` for anything destructive, security/governance-sensitive, or shipping to a sensitive target.
- **Fallback / supplement:** dispatch a fresh review subagent (the `Task`/Agent tool) with the diff and this rubric but **no authorship narrative**.

**Never hand-read your own diff and call it reviewed.** A clean self-eyeball is not a review; it is the author agreeing with themselves.

## Repo context

```!
cat .claude/skill-context.md 2>/dev/null || echo "(no .claude/skill-context.md — elenchus still runs tier-0; infer the test/run commands from the Makefile or ask. Add an optional \`## elenchus\` block for repo-specific hints; see Scaffolding below.)"
```

Read the `## elenchus` section if present (optional tier-1 hints — known destructive ops, load-bearing surfaces, reproduce recipes, what "the feature works" means here). For the commands to actually *run* the code, fall back in order to `## audit` (lint/test targets), `## theoros` (`repl_command`), then the repo `Makefile`. Tier-0 needs no config.

## Protocol

Run these phases in order. Do not skip a phase because the change "looks small" — the highest-value bugs hide in changes that look small.

### Phase 0 — Frame the load-bearing claim
State, in one sentence, the single claim the change rests on ("this fix makes X portable", "this feature lets the model cite summaries", "this refactor is behavior-preserving"). That claim is your hypothesis to break. Everything after is an attempt to find the input, state, or path that falsifies it.

### Phase 1 — Drive the engine
Run `/code-review` (effort per the independence rule). Treat its findings as input, not verdict — you still owe the three passes below, which `/code-review` does not force.

### Phase 2 — The three passes diff-reading skips
The bugs that pure diff review loses live here. Each one is invisible in the `+/-` and surfaces only by reading or running the code *around* the change.

1. **Reproduce the load-bearing claim.** Run it. Build the input matrix and check the boundary cells: `null` / `undefined` / empty-string / zero-rows / first / last / the `>= N` edge. Re-derive any number, table, or "all green" the change claims rather than trusting it. If you cannot reproduce, say so — that is a finding.
2. **Trace every consumer.** `grep`/`glob` every call-site of every symbol the change touched, across the **whole tree**, not the diff. Ask of each: does this caller still hold? Did the change reach the surface that actually matters (the docstring the model reads, the wrapper that gets registered, the path that ships)? *(This is how a feature passes every test and still ships dead: the enriched guidance landed on the inner function, not the wrapper the harness surfaces.)*
3. **Review against `main`, not the diff.** Read the unchanged code the change now interacts with. Old persisted state, sibling code paths, and callers outside the diff are all in scope.

### Phase 3 — The rubric
Walk every cell. For each, either find the falsifying case or explicitly clear it.

### Phase 4 — Report
Emit the structured report (format below). End with an explicit merge verdict and what you are holding on, if anything.

### Phase 5 — Post the distilled summary
If an open PR exists for the branch under review, post the distilled summary (contract in **Posting the summary** below) as a **single** `gh pr comment`. This is default behavior, not opt-in — the review of record belongs on the PR. Skip only when there is no PR (local / pre-PR review → the report stays in-session) or the invoker explicitly said to keep it local.

## The rubric (load-bearing)

| # | Cell | The question that finds the bug |
| --- | --- | --- |
| 1 | **Destructive-op reachability** | For every `rm -rf` / overwrite / `DROP` / `truncate` / force-push, name the **exact input or invocation** that reaches it. Don't assume it's unreachable — find the user command that makes the source resolve under the wipe. |
| 2 | **Parallel-path mirroring** | When a path mirrors an existing one, were the **guards _and_ the regression tests** mirrored too — or only the structure? Find the cell the new path leaves untested. |
| 3 | **Migration tolerance** | Does state persisted by the **old** code load under the **new** code? `dict["k"]` where the rest of the loader uses `.get(k, default)` is a silent reopen crash across an upgrade. |
| 4 | **Reachability to the real surface** | Did the change reach the surface that actually runs — the registered wrapper, the shipped path, the docstring the model/user sees — or only an inner copy the diff happened to touch? |
| 5 | **Boundary & empty inputs** | null / undefined / "" / 0 rows / unset env / missing file. Which one throws, mis-buckets, or silently no-ops? |
| 6 | **Looks-done ≠ is-done** | Local-green ≠ CI-green ≠ the feature actually working. Did you verify the **value path end to end**, or just that tests and lint pass? A green build can ship a dead feature. |
| 7 | **Flake vs real red** | Is a red check the change's fault or a pre-existing flake? Attribute it (touches no relevant code ⇒ likely flake), but **never merge on red**, and never blame the change for an unrelated failure. |
| 8 | **Claim ↔ code drift** | Do the PR description, docstrings, comments, and `Closes #N` match what the code does? A `Closes` that auto-retires a still-open gap is a defect of record. |
| 9 | **DRY / right altitude** | Is this the deep fix folded into the existing tolerance, or a band-aid special-case? Does a near-duplicate path want consolidation? |

## Honesty discipline

- Mark every finding **CONFIRMED** (you reproduced it) or **PLAUSIBLE** (reasoned, not run). Never launder a guess as a fact.
- State plainly what you **could not** verify or reproduce — that gap is information, not weakness.
- On re-review, do a **fresh full pass** — do not merely check your prior points were addressed. The worse bug is often the one the fix newly opens. Correct your own earlier findings when reproduction contradicts them.
- Sign off **positively** on the surface you scrutinized and cleared ("the read-only viewer cannot throw — every dereference is guarded", "the engine is byte-identical, this is a pure reframe"). Naming what is safe is what makes the review trustworthy.

## Output format

Severity-ranked, most-actionable first. Each finding:

- **Severity** — Blocking / Should-fix / Minor / Informational
- **Anchor** — `path/to/file.py:LINE`
- **Verdict** — CONFIRMED | PLAUSIBLE
- **Failure scenario** — concrete inputs/state → wrong output/crash, and the reachable path to it
- **Fix** — the deep fix, with a regression test that locks it

Close with: a one-line **merge verdict** (mergeable / hold on finding #N / not mergeable + why), and a **Verified clean** list of what you checked and cleared.

## Posting the summary (Phase 5)

Default: after emitting the in-session report, post a **single** distilled comment to the PR. Write the body to a temp file and post with `gh pr comment <N> --body-file <file>` (a file, not inline `--body`, so multi-line Markdown survives). One comment per run — never inline per-line comments, never a multi-comment dump. Post even on a clean pass; the record that an independent adversarial pass ran is the point.

Guard: only when `gh pr view --json number,url` resolves an **open** PR for the current branch. No PR (local or pre-PR review) → skip posting, keep the report in-session. Honor an explicit "keep it local" from the invoker.

Distill — the comment is the verdict and the actionable core, not the full transcript:
- **Merge verdict** — one line: mergeable / hold on finding #N / not mergeable + why.
- **Findings** — Blocking and Should-fix only, each as: `path:line` — one-line failure scenario — the fix. Drop Minor/Informational (they stay in-session) unless nothing else remains.
- **Verified clean** — the one-line list of what was scrutinized and cleared.
- **No signature or AI-attribution footer** — post as a plain review comment.
- **Account-owner voice** — the comment publishes under the invoking developer's GitHub account, so write it as that person speaking: first person ("I reproduced...", "I'd hold on..."), teammates addressed as peers by name. Never refer to the account owner in third person or as "you" ("AJ prefers...", "the preference of you and Ben" are both wrong), and no assistant framing ("the review found..." is fine; "I ran this for AJ" is not). Same rule for any follow-up comment posted in the same thread after the review.

Clean-pass shape: verdict `mergeable`, a `Findings: none blocking` line, and the Verified-clean list — a few lines, not a placeholder wall.

## Scaffolding `## elenchus` into a repo (optional, tier-1)

Tier-0 needs nothing. To give the skill repo-specific aim, add to `.claude/skill-context.md`:

````markdown
## elenchus

```yaml
test_command: <how to run the suite, e.g. make test / uv run pytest -q>
run_command: <how to exercise the running thing, if not already in ## theoros>
destructive_ops:
  - <path:line or description of an irreversible op reviewers must trace to its inputs>
load_bearing_surfaces:
  - <the registered wrapper / shipped path / docstring the harness actually surfaces>
feature_works_means:
  - <what "the feature actually works" looks like end-to-end in this repo, beyond green CI>
```
````

All fields optional — each one you add sharpens a phase. `destructive_ops` feeds rubric cell 1, `load_bearing_surfaces` feeds Phase 2 pass 2 / cell 4, `feature_works_means` feeds cell 6.

## Why "elenchus"

Greek ἔλεγχος: the Socratic method of refutation — cross-examine a claim by seeking the case that breaks it, until what survives is what's true. The review's job is not to agree with the change; it is to try, in good faith and with the system actually running, to refute the claim it rests on. What survives the elenchus is mergeable.
