# `techne:paper-review`

A pre-submission novelty and reviewer pass for a draft paper — checks whether each contribution
is actually new, what related work the draft misses, whether its claims hold up, and whether it
overlaps a lab or co-author line that must be disclosed. Every judgment is grounded in a real
retrieved paper, never asserted from memory.

## When to use

- A first-author draft is approaching submission: "review `<name>` for novelty", "what related
  work am I missing", "is this contribution new".
- NOT for copy-editing prose or for a paper with no stated contributions yet — scaffold first
  with [`techne:paper`](paper.md).

## Usage

```
/techne:paper-review <name> [--from <repo>]
```

Reads the `## paper-review` section of `.claude/skill-context.md` (overlap source of truth,
retrieval substrate, report path), extracts the draft's contributions, retrieves comparable
prior work from OpenAlex (web-search backstop; Semantic Scholar only with a key), and writes
`papers/<name>/novelty-review.md` with four sections: novelty per contribution, related-work
gaps, claim-support, and a lab-overlap disclosure section. Advisory only — it never edits the
draft.

## What it grounds

A mandatory pre-check (§0) first verifies the draft's *own* citations against authoritative
records (arXiv API / OpenAlex / DOI): a fabricated id, an id that resolves to a different paper,
or a mischaracterized claim about a cited work is a stop-ship finding. Then every novelty verdict
cites a paper retrieved that run with a verbatim snippet, logged in a
provenance appendix so the search is re-runnable. A verdict with no retrieved record is marked
**unverified**. The lab-overlap section surfaces adjacency and a COPE disclosure checklist but
renders no verdict — the solo-vs-lab boundary is a human agreement.

## See also

- [`techne:paper`](paper.md): scaffolds the draft this skill reviews.
- [Conventions](../conventions.md).
