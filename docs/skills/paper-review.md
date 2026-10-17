---
description: Run a pre-submission novelty and reviewer pass on a draft, with every verdict grounded in prior work retrieved this run.
---

# `graphe:paper-review`

A pre-submission novelty and reviewer pass for a draft paper. It checks whether each contribution
is actually new, what related work the draft misses, whether its claims hold up, and whether it
overlaps a lab or co-author line that must be disclosed. Every judgment is grounded in a real
retrieved paper, never asserted from memory.

Part of [graphe](../plugins/graphe.md): `/plugin install graphe@techne`, then `/graphe:setup`.

## When to use

- A first-author draft is approaching submission: "review `<name>` for novelty", "what related
  work am I missing", "is this contribution new".
- NOT for copy-editing prose or for a paper with no stated contributions yet; scaffold first
  with [`graphe:paper`](paper.md).

## Usage

```
/graphe:paper-review <name | path/to/doc.tex> [--from <repo>]
```

Reads the `## paper-review` section of `.claude/skill-context.md` (`lab_line`, the overlap source of truth;
`retrieval`; `mailto`, for OpenAlex's polite pool and also read from `OPENALEX_MAILTO`; and `report`, the report path), extracts the draft's contributions, retrieves comparable
prior work from OpenAlex (web-search backstop; Semantic Scholar only with `S2_API_KEY`; `OPENALEX_API_KEY` raises OpenAlex's budget). Only derived keyword queries leave the machine, never the paper text, and writes
`papers/<name>/novelty-review.md` (or `<stem>.novelty-review.md` beside a `.tex` path): citation integrity, novelty per contribution, related-work
gaps, claim-support, a lab-overlap disclosure section, and a provenance log of every query. Advisory only: it never edits the
draft.

## What it grounds

A mandatory pre-check (§0) first verifies the draft's *own* citations against authoritative
records (arXiv API / OpenAlex / DOI): a fabricated id, an id that resolves to a different paper,
or a mischaracterized claim about a cited work is a stop-ship finding. Then every novelty verdict
cites a paper retrieved that run with a verbatim snippet, logged in a
provenance appendix so the search is re-runnable. A verdict with no retrieved record is marked
**unverified**. The lab-overlap section surfaces adjacency and a COPE disclosure checklist but
renders no verdict, since the solo-vs-lab boundary is a human agreement.

Claim-support also runs the *Claims* checks in `_shared/plain-prose.md`: numbers against the code or data behind them, method descriptions against the code, summaries of cited papers against their full text where open access, and a proposal's promises against the time it has. A manuscript missing the sections its venue expects, such as Related Work or References, is a stop-ship finding.

The pass also applies `_shared/paper-quality.md`: the every-sentence test, a comparison against the venue conventions sheet, an audit of `CUTS.md` against the call's required elements, integrity guards (ethics or IRB claims, restricted data, "not in a published figure" promises), and registered-report tense. Reviewer lenses find weaknesses; a finding counts only if fixing it makes the paper clearer, more rigorous or more concise.

## See also

- [`graphe:paper`](paper.md): scaffolds the draft this skill reviews.
- [Conventions](../conventions.md).

## Full instructions

[`SKILL.md` on GitHub](https://github.com/ajbarea/techne/blob/main/plugins/graphe/skills/paper-review/SKILL.md) holds the full instructions Claude follows for this skill.
