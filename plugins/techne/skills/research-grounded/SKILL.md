---
name: research-grounded
description: Audit a plan's design decisions — library, framework, pattern, and architecture choices in IMPL.md / ROADMAP.md — for missing `# research(YYYY-MM):` provenance, then web-search to ground them. Use when you want architectural choices verified against current best practice before they harden into code, rather than resting on training-cutoff recall. Catches committed decisions stated as fact but never checked — the class of miss that becomes revertable work.
disable-model-invocation: false
allowed-tools: Bash Glob Grep Read Edit WebSearch WebFetch Agent
---

# Research-grounded

Catch design decisions that were made without checking current best practice — *before* they become code. A planning doc that says "we'll use X" with no provenance is a bet on training-cutoff recall; the convention `# research(YYYY-MM): <tradeoff> <source>` records that the bet was checked against reality. This skill finds the bets that weren't.

## Repo context

`/techne:research-grounded` audits docs in the CWD repo by default, or a path you name (which may live in another repo). Resolve the repo root from the argument:

```bash
git -C "$(dirname "<target-doc>")" rev-parse --show-toplevel   # no path arg → CWD repo root
```

The target's `.claude/skill-context.md` isn't required, but its `## repo` section helps you tell a genuine technology choice from incidental prose.

## What needs provenance

A **committed design decision** — a choice with real alternatives, where picking wrong is expensive to undo:

- **Library / framework / tool** — "MapLibre + PMTiles", "Playwright over Cypress", "switched from JWT to server sessions".
- **Pattern / technique** — "event delegation over per-node listeners", "stale-while-revalidate", "container queries for card internals".
- **Architecture / protocol** — "A2A `Message.metadata` instead of text tags", "OPFS for tile storage".
- **Version / API-surface bets stated as fact** — "ElevenLabs v3 supports SSML break tags" (the miss that cost 5 revertable PRs: a capability asserted, never verified against the target's docs).

Each of these, when committed in IMPL/ROADMAP, should carry an adjacent `# research(YYYY-MM): <one-line tradeoff> <source>`. Negative-space decisions ("we did **not** do X because…") need provenance too.

## Ignore

- **Descriptive implementation prose.** "reads the metrics object instead of re-reading constants", "returns a structured fallback instead of a retry loop" — uses decision words but picks no technology or pattern. Not research-worthy.
- **Hypotheticals & aspirations.** "what if we used sessions instead of JWT", "we plan to", "coming soon" — not yet a commitment (mirrors how `/techne:docsync` waves through roadmap language).
- **Already grounded.** A decision with a `research(...)` tag on the same bullet or within a few lines — even a terse one.
- **Bugfixes, renames, mechanical changes** — no alternative space to research.
- **Settled house conventions** — the fleet's own recorded standards (SHA-pinning, squash-merge). Don't re-flag every mention.

## Workflow

1. **Scope.** Default: `IMPL.md` + `ROADMAP.md` in the target repo. Accept a named file or a directory (e.g. `planning/`). For multiple files, fan out — one `Explore` subagent per file (see [Fan-out](#fan-out-pattern)).

2. **Find candidate decisions.** Seed with a grep, then *read around each hit* — the grep finds candidates; judgment decides which are research-worthy per the lists above.

   ```bash
   grep -nEi 'chose|switched|adopted|replaced|opted for|we use|picked|migrated|over [A-Za-z.-]+ \(|instead of' ROADMAP.md IMPL.md
   ```

   **Don't trust the grep.** Most `instead of` hits are descriptive prose, not technology choices — classify per-hit, not per-match.

3. **Check provenance.** For each genuine decision, look for a `research(YYYY-MM):` (or `# research:`) tag on the same bullet or within a few lines. Present → grounded, skip. Absent → gap.

4. **Report gaps.** One entry per un-grounded decision:

   ```
   ROADMAP.md:88
     decision: "embed offline maps with MapLibre + PMTiles"
     gap:      no research provenance — grounded in 2026 offline-map options, or recall?
     action:   web-search current PMTiles/MapLibre tradeoffs → add `# research(2026-05): <tradeoff> <source>`
   ```

5. **Ground or flag (on confirmation).**
   - **Ground it** (the point of the skill — close the loop, don't just flag): web-search the decision's current best practice, then add `# research(YYYY-MM): <tradeoff> <source>` capturing what you actually found.
   - **Flag only:** if grounding needs the user's domain context a quick search can't supply, leave a one-line note to ground it *before* it hardens into code.
   - **Never invent a citation.** A `research()` tag with a fabricated or unread source is worse than no tag.

## Fan-out pattern

For a directory (e.g. `planning/`), spawn one `Explore` subagent per file; each returns a gap report for its file. Consolidate, present grouped by file, then ask `ground all / ground selected / skip?`.

## Don't touch

- Docs the user didn't name or imply; git history / changelogs (historical, not live bets).
- `research()` tags that already exist — don't reword a grounded decision unprompted.
- Decisions already shipped as code with no alternative left to research — audit the plan, not the past.

## Why this skill is quiet

Output is the gap report and, on confirmation, the web-searched `research()` tags. No narration of the scan — just `decision → gap → action`. Sibling of `/techne:docsync` (claims vs code); this is decisions vs evidence.
