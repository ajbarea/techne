# techne:paper-review — skill design

**Date:** 2026-06-14 · **Status:** accepted (autonomy-default, solo repo) · **Author:** AJ Barea

## Context

`papers/` now scaffolds first-author drafts (`techne:paper`). The lever the `LINEAGE.md`
record flagged next is a **pre-submission novelty + reviewer pass**: before
`velocity-fl-systems` goes to the advisor, each contribution must be shown distinct, missed
related work caught, and the overlap with the lab's in-review PID-MADE line disclosed cleanly.
Naive LLM review hallucinates citations and under-weights novelty (the documented failure
mode); this skill grounds every judgment in a *retrieved* paper.

## What it does

One core action: **review a scaffolded paper for novelty + reviewer-readiness**, grounding
every judgment in retrieved prior work. Given `<name>` (+ optional `--from <repo>`), produce
`papers/<name>/novelty-review.md` with four sections:

1. **Novelty** — per contribution: novel / incremental / overlaps-with, each with the closest
   retrieved paper (cited) + a verbatim evidence snippet.
2. **Related-work gaps** — retrieved papers absent from `references.bib` that should be cited.
3. **Claim-support** — each flag-claim ("first to", "N×", "outperforms") → supported /
   unsupported / overclaim; first-ness via retrieval, quantitative via the `--from` repo's
   harvest output.
4. **Lab-overlap (surface, do not adjudicate)** — adjacency to the lab line in `LINEAGE.md`
   plus a COPE disclosure checklist; the solo-vs-lab verdict is explicitly deferred to the
   author + advisor.

Advisory only — never edits the paper.

## Grounding invariant (the load-bearing rule)

Following OpenNovelty (arXiv 2601.01576): a citation in the report is valid only if it traces
to a retrieval result logged in this run, paired with a verbatim snippet. A novelty verdict
with no retrieved record + snippet is downgraded to "unverified". Hallucinated citations are
the #1 failure mode the skill exists to prevent — the analogue of `techne:paper`'s "never
hand-type result numbers".

## Privacy posture

Drafts are private (double-blind + scoop). Only derived keyword queries leave the machine —
never the paper text or PDF. No upload to any third-party review service.

## Config contract

Reads `## paper-review` from `<repo>/.claude/skill-context.md`: `lab_line` (default
`LINEAGE.md`), `retrieval` (default Semantic Scholar + OpenAlex, web backstop), `mailto`
(OpenAlex polite pool), `report` (default `papers/<name>/novelty-review.md`). Sensible
defaults if absent. Building this adds a `## paper-review` block to
`papers/.claude/skill-context.md`.

## Structure (progressive disclosure)

- `plugins/techne/skills/paper-review/SKILL.md` — lean instructions; third-person,
  trigger-only description.
- `templates/novelty-review.md.tmpl` — the four-section report skeleton + provenance appendix.
- `references/retrieval.md` — Semantic Scholar + OpenAlex query recipes (endpoints, fields,
  rate limits, `jq` parsing) kept out of the lean SKILL.md.

## ADRs

- **Retrieval substrate: OpenAlex primary; Semantic Scholar secondary (key-gated); web
  backstop.** Live-tested 2026-06-14 — keyless Semantic Scholar returns HTTP 429 (shared-pool
  rate limit), so it cannot be primary without an API key; it is used only to enrich when
  `S2_API_KEY` is set. OpenAlex (`title_and_abstract.search` + `relevance_score` sort +
  `mailto` polite pool, abstract reconstructed from its inverted index) is keyless, reliable,
  and returns DOI + citation counts. *Walk-back:* the brief and my first design said "Semantic
  Scholar + OpenAlex" with S2 leading; the live 429 flipped primary to OpenAlex. Rejected:
  web-search-only (less structured, harder to reproduce); HF/arXiv-only (narrower than ML).
- **Lab-overlap surfaces, does not adjudicate.** The rail says the solo-vs-lab boundary is
  agreed with the advisor; a machine verdict would usurp that. The flag lists adjacency + the
  disclosure checklist and defers.
- **Inline 4-phase pipeline; subagent fan-out deferred.** OpenNovelty's phases run inline;
  per-contribution retrieval fans out to subagents only when a paper has many contributions
  (YAGNI — not built in v1).
- **Instruction-skill + `templates/` + `references/`** (house pattern, mirrors `techne:paper`).
  Rejected: a bundled generator script (over-engineered; techne skills are instruction-based).

## Registration + verification

- Add `docs/skills/paper-review.md`, a row in `docs/skills/index.md` + the README table; add
  `paper-review` to the README "how it fits" tree and the `zensical.toml` nav (and repair the
  pre-existing omissions there: `paper` is missing from the nav, `paper`/`research-grounded`
  from the tree).
- **Verify:** baseline review WITHOUT the skill (RED — confirm ungrounded assertions + missed
  lab overlap), then run the skill on `velocity-fl-systems` (GREEN) and confirm: four sections
  present, every novelty verdict carries a retrieved citation + snippet, related-work gaps
  cross-checked against `references.bib`, claim-support flags the ~135× number, §4 surfaces
  PID-MADE with no verdict.
