---
name: paper-review
description: Use when a draft research paper needs a pre-submission novelty and reviewer pass — whether its contributions are actually new, what related work it misses, whether its claims hold up, and whether it overlaps a lab or co-author line that must be disclosed. Triggers include "review my paper for novelty", "is this contribution novel", "novelty check before submitting", "what related work am I missing", "verify my citations are real", "paper-review <name>".
disable-model-invocation: false
allowed-tools: Bash Glob Grep Read Edit WebSearch WebFetch Agent
---

# Paper Review

## Overview

A pre-submission **novelty + reviewer pass** that grounds every judgment in a *retrieved* paper.
Naive LLM review asserts novelty from memory and invents citations; this skill retrieves real
prior work, quotes it, and cross-checks the draft's bibliography — then surfaces (without
adjudicating) any overlap with a lab or co-author line that has to be disclosed.

**Core principle:** a novelty claim is only as good as the paper it is checked against. Every
verdict cites a record retrieved this run with a verbatim snippet, or it is marked
**unverified** — the analogue of `techne:paper`'s "never hand-type a result number".

## When to use

- A first-author draft is approaching submission and needs a distinctness + related-work check.
- "Review `<name>` for novelty", "what am I missing", "is C2 actually new".
- NOT for copy-editing prose; NOT for a paper with no stated contributions yet (scaffold first
  with `techne:paper`).

## Inputs

- `<name>` — the paper directory under `papers/` (e.g. `velocity-fl-systems`).
- `--from <repo>` (optional) — the source code repo; grounds quantitative claims against its
  harvest output.

## Config

Read `## paper-review` from `<repo>/.claude/skill-context.md`: `lab_line` (overlap source of
truth, default `LINEAGE.md`), `retrieval` (default OpenAlex + web; Semantic Scholar only if
`S2_API_KEY` is set), `mailto` (OpenAlex polite pool, default `git config user.email`), `report`
(default `papers/<name>/novelty-review.md`). Sensible defaults if absent.

## Procedure

Refuse if `papers/<name>/` does not exist. Locate `main.tex` and its `\input` files. Then run a
mandatory citation-integrity gate, then OpenNovelty's four-phase pipeline (arXiv 2601.01576):

0. **Citation integrity (MANDATORY — do this first).** Before assessing novelty, verify the
   draft's *own* citations are real. Extract every `\cite` key and its `references.bib` entry;
   verify each against an authoritative record — arXiv ids via the arXiv API, DOIs / venues via
   OpenAlex or DOI content-negotiation. See [citation-verify](references/citation-verify.md).
   Confirm the id/DOI resolves to the *same* paper (title match), with correct authors and year,
   and read the abstract to check any claim the draft makes *about* that work ("parameter-free",
   "first to"). A fabricated id, a mismatched title, or an unsupported claim-about-a-paper is a
   **stop-ship** finding — fix or flag it before anything else. A single wrong citation sinks the
   paper.

1. **Extract claims.** Parse `main.tex` for the title, abstract, and stated contributions (the
   `% (C1) …` or `\item` list after "Our contributions" / "In this paper"). Collect flag-claims:
   `first`, `novel`, `outperforms`, `state-of-the-art`, and any `N×` / `N%` number. Show the
   extracted contribution list to the user to confirm or edit before retrieving — the claims
   drive everything downstream.

2. **Retrieve.** Per contribution, build a focused query from its noun phrases and search
   OpenAlex; collect {title, year, DOI, citations, abstract}. Rank by relevance, then citation
   count; web-search fills gaps. Log every query. See [retrieval recipes](references/retrieval.md).
   **Only derived keyword queries leave the machine — never the paper text** (drafts are private,
   often double-blind).

3. **Compare** — each contribution against its top candidates. Ground every judgment in a
   verbatim snippet from the retrieved abstract. Classify: novel / incremental / overlaps-with
   [cite]. A verdict with no retrieved record + snippet is **unverified**, never a confident
   assertion.

4. **Synthesize** into the configured report from
   [the template](templates/novelty-review.md.tmpl):
   - **§0 Citation integrity** — each cited work → verified (source) / mismatch-fixed /
     **stop-ship**; stop-ship findings first. No fabricated or mischaracterized citations.
   - **§1 Novelty** — per contribution: verdict + closest prior work (cited + snippet) + what is
     distinct.
   - **§2 Related-work gaps** — retrieved papers absent from `references.bib` (cross-check DOIs
     and titles per the recipe). The closely-related work the author overlooked.
   - **§3 Claim-support** — each flag-claim → supported / unsupported / overclaim. First-ness
     from retrieval; quantitative claims against the `--from` repo's harvest output (else flag
     "verify against source").
   - **§4 Lab-overlap — surface, do not adjudicate.** Parse `lab_line`; list adjacent lab papers
     and which draft claims overlap; emit the COPE disclosure checklist. **Never render a
     too-close / go-no-go verdict** — that boundary is the author's and advisor's to agree.
   - **§ Provenance** — every query and the records it returned, re-runnable.

Report the path + a one-line summary (N contributions, M novel / K overlaps, P uncited gaps,
lab-overlap: needs-discussion). **Never edit the paper** — this pass is advisory.

## Common mistakes

- **Trusting the draft's existing citations.** Verify them too (§0) — a seed bib or a recalled
  citation can be fabricated or mischaracterized. arXiv id → arXiv API; venue → OpenAlex / DOI; a
  claim *about* a paper → its abstract. A single wrong citation sinks the paper.
- **Asserting novelty from memory.** The failure this skill exists to stop. No verdict without a
  retrieved record + a quoted snippet logged in § Provenance.
- **Inventing or half-remembering a citation.** A fabricated reference is worse than none. If a
  search did not return it, do not cite it.
- **Eyeballing the bibliography.** §2 gaps come from parsing `references.bib` (DOIs + titles) and
  comparing to the retrieved set — not from guessing what is already cited.
- **Adjudicating the lab boundary.** §4 surfaces adjacency + the disclosure checklist and stops.
  Scoring it go/no-go usurps a human agreement.
- **Relying on keyless Semantic Scholar.** It returns `429`. OpenAlex is primary; S2 only with a
  key.

## Why this skill is careful

The output is one advisory artifact — `novelty-review.md` — and it never touches the draft. Its
value is that every line can be checked: a cited paper, a quoted snippet, a logged query. Sibling
of `techne:paper`, which scaffolds the draft this one reviews.
