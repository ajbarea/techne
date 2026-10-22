---
name: elenchus
description: Adversarial pre-merge code review — drive an independent review sized to the change's risk (a fresh reviewer, plus /code-review high for risky changes) whose reader runs the three passes diff-reading skips (reproduce the load-bearing claim, trace every consumer, review against the whole repo) and the bug-class rubric that catches reachable destructive ops, unmirrored parallel-path guards, migration crashes, and dead features that still pass CI. Use before merging a substantive change, when asked to "review it like a hostile reviewer", "hunt edge cases", "break this before merge", "is this actually mergeable", or to give a self-authored change an independent pass. Reads optional per-repo hints from the `## elenchus` section of `.claude/skill-context.md`.
disable-model-invocation: false
allowed-tools: Bash Read Grep Glob Agent Skill
---

# Elenchus

`<plugin-root>` is the plugin's root directory, two levels above the directory holding this SKILL.md.

ἔλεγχος — the Socratic cross-examination: you do not confirm what the author meant, you hunt the one input that **refutes the claim the change rests on**. A change is innocent of nothing until you have tried to break it and failed. You are the independent adversary in the chair, never the author defending the diff.

This skill exists because the same model that writes a change is a poor judge of it: the author reviews what they *intended*, under ship-it momentum, against a mental model that hides what the code actually does. The fix is not a smarter model — it is an **independent reader running a fixed adversarial protocol against the whole repo, reproducing as it goes**. That is the entire method. Everything below operationalizes it.

## The cardinal rule: independence is mechanical

If you (or this session) authored the change under review, you are the wrong reviewer **by construction** — you cannot un-know what it was supposed to do. Restore independence with tools, not willpower.

Restoring it means a fresh review subagent (the `Agent` tool, never a fork, which inherits the author's context) runs this protocol. Its cost scales with the change's risk, not with habit; independence comes from a context that never wrote the code, not from how many agents run.

**Your role decides what you run:**

- **Author** (you or this session wrote the change): do not run Phases 2 to 4 yourself. Pick the tier, run Phase 1, which dispatches the review, then relay its report as Phase 4 and carry on with Phase 5. You own the review loop (**When the review loop ends**).
- **Dispatched reader** (an author's session started you with this file): run Phases 0 to 4 once (Phase 1 only takes the findings you were handed) and return the report. State the tier the change deserves; if it is higher than the one run, say so first, and the author reruns at that tier. Do not dispatch another reviewer, post, or run the loop; the author's session does those.
- **Independent reader** (someone else's change, such as a teammate's PR): run every phase yourself, Phase 1's `/code-review` included when the high tier applies, and own the loop.

**Tiers:**

- **High tier** when any of these holds, whatever the size of the diff: a new subsystem; a change that adds a destructive operation, or whose output reaches an existing one (class `destructive-op-reachability`: a path, a glob, a list that feeds an `rm -rf`, an overwrite, a `DROP`); a change to persisted state or its format (class `migration-tolerance`); a security, privacy, access or governance boundary; a change shipping to a sensitive target. Phase 1 runs `/code-review` at `high` on the change (`/code-review high <PR number>`, or `/code-review high <branch>` before a PR exists), which spawns independent finder agents. `ultra` (a billed multi-agent cloud review) is also worth recommending; it is user-triggered, so name it to the user rather than trying to launch it.
- **Light tier** only when none of those holds: no `/code-review`; for an author, the dispatched reader alone.
- **Unsure** means high.
- **A failed review is not a clean one.** When the dispatched reader or any finder agent errored (rate limit, API failure, timeout), zero findings means unverified, not clean: rerun that review before reporting it.

**Never hand-read your own diff and call it reviewed.** A clean self-eyeball is not a review; it is the author agreeing with themselves.

## The bug-class catalog

[references/bug-classes.md](references/bug-classes.md) holds every class of bug already paid for once: the nine core rubric classes and the classes learned since, each with its symptom, the question that catches it, the guard that prevents it, and dated incidents. Authors walk it before review, readers walk it during review, and the loop adds to it after merge. A loop that relearns a catalogued class has wasted a round.

## Before you ask for review

The author's pre-flight, before the first round:

1. **Walk the catalog against the diff.** Ask every core class's question, and each learned class's question wherever the diff touches its trigger. Fix what it finds before a reader spends a round on it.
2. **Code that parses another language or format** (bash, a regex, TOML, YAML, paths, a URL, a CLI's argv) gets a differential or property test against the real implementation: generated inputs fed to both your parser and the real one (bash, `tomllib`, `os.path.realpath`, the program itself), failing on any disagreement. A hand-picked example list only proves the cases its author thought of (class `shell-semantics-mismatch`).
3. **Mutation-check the guards.** Flip each guard condition in turn (invert it, drop a branch, widen an allow-list) and confirm a test goes red; restore it after. mutmut (Python) or Stryker (JS and TS) automate this; a handful of conditions can be flipped by hand. A guard no test can fail is unguarded (class `vacuous-guard`).
4. **Start the deferred-findings ledger** in the PR body, or in IMPL.md before a PR exists: one line per finding the author chose not to fix in this change, with its class, why, and the issue that tracks it. Readers read it and do not re-report its items.

## Repo context

```!
echo "<!-- skill-context: $(git rev-parse --show-toplevel 2>/dev/null || pwd) -->"; cat "$(git rev-parse --show-toplevel 2>/dev/null || pwd)/.claude/skill-context.md" 2>/dev/null || echo "(no .claude/skill-context.md in this repo)"
```

If the block above appears as a command rather than its output, run it and use what it prints.

No context file: elenchus still runs with no hints; infer the test and run commands from the Makefile or ask. Add an optional `## elenchus` block for repo-specific hints; see Scaffolding below. The header names the repo it came from, which is the current directory's. When the target is a path in another repo, run `bash "<plugin-root>/_shared/skill_context.sh" <target-path>` and use that output instead.

Read the `## elenchus` section if present (optional hints — known destructive ops, load-bearing surfaces, reproduce recipes, what "the feature works" means here). For the commands to actually *run* the code, fall back in order to `## audit` (lint/test targets), `## theoros` (`repl_command`), then the repo `Makefile`. With no hints it needs no config.

## Protocol

Run the phases your role covers (see **The cardinal rule**), in order. Do not skip one because the change "looks small" — the highest-value bugs hide in changes that look small.

### Phase 0 — Frame the load-bearing claim
State, in one sentence, the single claim the change rests on ("this fix makes X portable", "this feature lets the model cite summaries", "this refactor is behavior-preserving"). That claim is your hypothesis to break. Everything after is an attempt to find the input, state, or path that falsifies it.

### Phase 1 — Drive the engine
- **Author:** in the high tier, run `/code-review high` on the change first. Then dispatch the reader with `model: "opus"` set explicitly (an unset model inherits the author's session model; review is the step that most needs the strongest reasoner), this prompt, and the `/code-review` findings, if any, and **no authorship narrative**: "You are the dispatched reader for techne:elenchus. Read <path to this SKILL.md>, then its bug-class catalog. Review <PR number or branch> as the dispatched reader. Tier run: <high or light>. Deferred-findings ledger: <where it is, or none>. Classes found in earlier rounds: <slugs, or none>. Run Phases 0 to 4 once and return the report. Do not dispatch another reviewer, post, or run a review loop." Relay its report as Phase 4.
- **Dispatched reader:** read the catalog and the deferred-findings ledger before the diff. Take the findings you were handed as input, not verdict; you still owe the three passes below, which `/code-review` does not force.
- **Independent reader:** in the high tier, run `/code-review high` on the change yourself, then treat its findings the same way.

### Phase 2 — The three passes diff-reading skips
The bugs that pure diff review loses live here. Each one is invisible in the `+/-` and surfaces only by reading or running the code *around* the change.

1. **Reproduce the load-bearing claim.** Run it. Build the input matrix and check the boundary cells: `null` / `undefined` / empty-string / zero-rows / first / last / the `>= N` edge. Re-derive any number, table, or "all green" the change claims rather than trusting it. If you cannot reproduce, say so — that is a finding.
2. **Trace every consumer.** `grep`/`glob` every call-site of every symbol the change touched, across the **whole tree**, not the diff. Ask of each: does this caller still hold? Did the change reach the surface that actually matters (the docstring the model reads, the wrapper that gets registered, the path that ships)? *(This is how a feature passes every test and still ships dead: the enriched guidance landed on the inner function, not the wrapper the harness surfaces.)*
3. **Review against `main`, not the diff.** Read the unchanged code the change now interacts with. Old persisted state, sibling code paths, and callers outside the diff are all in scope.

### Phase 3 — The catalog
Walk the [bug-class catalog](references/bug-classes.md): every core class (1 to 9), and each learned class whose trigger the diff touches. For each, either find the falsifying case or explicitly clear it. A ledgered deferred finding is not re-reported unless this change makes it worse or reaches it by a new path.

### Phase 4 — Report
Emit the structured report (format below). End with an explicit merge verdict and what you are holding on, if anything.

### Phase 5 — Post the distilled summary
If an open PR exists for the branch under review **and someone else opened it**, post the distilled summary (contract in **Posting the summary** below) as a **single** `gh pr comment`. This is default behavior, not opt-in — the review of record belongs on the PR. Skip when there is no PR, when the account owner opened it, or when the invoker explicitly said to keep it local; the report then stays in-session (Blocking or Should-fix findings still open when the review loop ends go to its linked issue, when one exists; see **When the review loop ends**).

Derive authorship before posting — never assume.

## The rubric (load-bearing)

The rubric is the catalog's core section, nine classes walked on every review: destructive-op reachability, parallel-path mirroring, migration tolerance, reachability to the real surface, boundary and empty inputs, looks done is not done, flake versus real red, claim and code drift, and DRY at the right altitude. Their questions, guards and incidents live in [references/bug-classes.md](references/bug-classes.md), so the rubric and the classes learned since stay one list.

## Honesty discipline

- Mark every finding **CONFIRMED** (you reproduced it) or **PLAUSIBLE** (reasoned, not run). Never launder a guess as a fact.
- State plainly what you **could not** verify or reproduce — that gap is information, not weakness.
- On re-review, do a **fresh full pass** — do not merely check your prior points were addressed. The worse bug is often the one the fix newly opens. Correct your own earlier findings when reproduction contradicts them.
- Sign off **positively** on the surface you scrutinized and cleared ("the read-only viewer cannot throw — every dereference is guarded", "the engine is byte-identical, this is a pure reframe"). Naming what is safe is what makes the review trustworthy.

## Output format

Severity-ranked, most-actionable first. Each finding:

- **Severity** — Blocking / Should-fix / Minor / Informational
- **Class** — the catalog slug, such as `unmirrored-parallel-guard`, or `new: <short name>` when no class fits; required on every Blocking and Should-fix finding
- **Anchor** — `path/to/file.py:LINE`
- **Verdict** — CONFIRMED | PLAUSIBLE
- **Failure scenario** — concrete inputs/state → wrong output/crash, and the reachable path to it
- **Fix** — the deep fix, with a regression test that locks it

Close with: a one-line **merge verdict** (mergeable / hold on finding #N / not mergeable + why), and a **Verified clean** list of what you checked and cleared.

## When the review loop ends

A change often takes several rounds: review, fix, review again. The author's session (or the independent reader) owns the loop: it re-dispatches, counts the time, decides to stop and writes the stop down. A dispatched reader runs one round and writes nowhere. The PR's owner fixes each finding, with a regression test that runs in CI wherever the finding is testable. On someone else's PR a round ends with the Phase 5 comment, and the next round starts when the owner pushes. When a PR exists, start each round by re-reading its comments and reviews. The loop has no fixed round count. It ends on what the last round found.

- **Reproduce before reporting.** Before a round's report, the reader makes one attempt to reproduce each Blocking or Should-fix finding not yet reproduced. One that still fails stays PLAUSIBLE and is recorded as open: it holds the merge, but does not by itself keep the loop going. Open means any Blocking or Should-fix finding not fixed when the loop stops or pauses.
- **Keep going** while the round has a reproduced Blocking or Should-fix finding (see Output format) on a reachable input: one that a caller in the repo, or a documented usage, can produce, unless a pause below applies.
- **Stop** in every other case: what remains is Minor, Informational, unreachable, or recorded as open.
- **Write the stop down.** Open Blocking or Should-fix findings go in the Phase 5 comment on someone else's PR. On a PR the account owner opened, they go in its linked issue when one exists (the issue its body names with `Closes #N` or `Fixes #N`; with several, the first), under the same contract as the Phase 5 comment (account owner's voice, no provenance); with no linked issue, tell the user the PR waits on them. Minor findings stay in-session, and "keep it local" keeps everything in-session.
- **A class that recurs escalates.** When a Blocking or Should-fix finding's class already had a finding in an earlier round of this loop, do not patch the new instance: name the structural fix (one shared helper every parallel path calls, a canonical format instead of a wider regex, delegating to the real parser instead of modelling it) and make it, with a test that sweeps the class: differential, property-based or mutation (see **Before you ask for review**). The reader names the recurrence and the structural fix in its report.
- **Deferred findings are ledgered, not re-reported.** A finding the author defers goes in the ledger (PR body, or IMPL.md before a PR) with its class, why, and its tracking issue. Readers read the ledger and leave its items out of their report unless the change made one worse.
- **Pause when it runs long.** Count the reviewer's own working time across rounds, not time spent waiting for the owner. Stop and report when that passes the budget the user set, or when two rounds in a row find only bugs the previous fix introduced (then the fix approach is the problem); resume only on the user's go-ahead. With no budget set, the budget is three rounds: after the third, report what is open instead of starting a fourth, unless the user asked for the change to be reviewed until clean.

## After merge

The author adds to the catalog, in the same PR or a follow-up: each `new:` class from the loop as a full entry, and each finding of an existing class as a dated incident on that entry (`repo#PR rN (YYYY-MM-DD): what happened`). A class that cost a round belongs in the catalog before the next change can relearn it.

## Posting the summary (Phase 5)

Default: after emitting the in-session report, post a **single** distilled comment to the PR. Write the body to a temp file and post with `gh pr comment <N> --body-file <file>` (a file, not inline `--body`, so multi-line Markdown survives). One comment per run — never inline per-line comments, never a multi-comment dump. Post even on a clean pass; the record that the change was scrutinized is the point.

Guard: only when `gh pr view --json number,url` resolves an **open** PR for the current branch. No PR (local or pre-PR review) → skip posting, keep the report in-session. Honor an explicit "keep it local" from the invoker.

### Only on someone else's PR

The comment publishes under the invoking developer's GitHub account, so the account owner is the one speaking. Derive authorship live — no config file, and no assuming from the repo you are standing in:

```bash
gh api user --jq .login                              # the account the comment posts as
gh pr view <N> --json author --jq .author.login      # who opened the PR
```

**Author == account owner → do not post.** The report stays in-session for the account owner to act on (Blocking or Should-fix findings still open when the review loop ends go to its linked issue, when one exists; see **When the review loop ends**): fix the findings on the branch, and let the squash carry the result. A review comment on your own PR is the author talking to themselves in front of the reviewer, who reads the final diff, not the branch's history; it clutters the thread, and a verdict there pre-empts the human reviewer this entire method depends on.

**Author ≠ account owner** — the comment is, in order:

1. **Merge verdict** — one line: mergeable / hold on finding #N / not mergeable + why.
2. **Findings** — Blocking and Should-fix only, each as: `path:line` — one-line failure scenario — the fix.
3. **Verified clean** — the one-line list of what was scrutinized and cleared.

### Never publish the review's provenance

Publish the **work**, which anyone can check, never how it was run.

- Never write "independent", "adversarial pass", "hostile review", or any variant describing the review itself.
- Never name the machinery: `/code-review`, `/techne:elenchus`, "review agents", "subagent", "effort level". Teammates cannot run it, so it is not evidence to them — it is jargon.
- Say what was done instead: "reproduced on a fresh clone under numpy 2.5.3", "traced every call site of `load_train` across the tree", "exercised CRLF, BOM, empty-file and arbitrary-cwd inputs".

### Every comment

- **Account-owner voice** — write as that person speaking: first person ("I reproduced...", "I'd hold on..."), teammates addressed as peers by name. Never refer to the account owner in third person or as "you" ("the author prefers...", "the preference of you and the reviewer" are both wrong), and no assistant framing ("the review found..." is fine; "I ran this for the account owner" is not). Same rule for any follow-up comment in the same thread.
- **No signature or AI-attribution footer** — post as a plain review comment.
- **Keep it about the code.** No account or personal state (API credit, billing, subscription tier, what a local machine has installed). If it explains a gap, say the gap: "not exercised end to end" rather than why.
- Drop Minor/Informational findings — they stay in-session — unless nothing else remains.

Clean-pass shape: the verdict, the Findings line reading `none blocking`, and the Verified-clean list — a few lines, not a placeholder wall.

## Scaffolding `## elenchus` into a repo (optional)

With no hints it needs nothing. To give the skill repo-specific aim, add to `.claude/skill-context.md`:

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

All fields optional — each one you add sharpens a phase. `destructive_ops` feeds class `destructive-op-reachability`, `load_bearing_surfaces` feeds Phase 2 pass 2 and class `unreached-surface`, `feature_works_means` feeds class `looks-done-not-done`.

## Why "elenchus"

Greek ἔλεγχος: the Socratic method of refutation — cross-examine a claim by seeking the case that breaks it, until what survives is what's true. The review's job is not to agree with the change; it is to try, in good faith and with the system actually running, to refute the claim it rests on. What survives the elenchus is mergeable.
