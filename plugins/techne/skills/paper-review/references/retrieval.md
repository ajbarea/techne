# Retrieval recipes — paper-review

The grounding substrate. Every novelty or claim verdict in the report must trace to a record
retrieved here, paired with a verbatim snippet. **OpenAlex is primary** (keyless, reliable);
Semantic Scholar enriches only with a key; web-search is the backstop.

## OpenAlex (primary)

Keyless. Identify yourself with `mailto` (the "polite pool" — faster, friendlier). Search the
title+abstract, sort by relevance, and reconstruct the abstract from its inverted index for the
snippet.

```bash
MAILTO="${OPENALEX_MAILTO:-$(git config user.email)}"
Q='federated learning Byzantine robust aggregation'   # one focused query per contribution
ENC=$(printf '%s' "$Q" | jq -sRr @uri)
curl -s --max-time 25 \
  "https://api.openalex.org/works?filter=title_and_abstract.search:${ENC}&per-page=8&sort=relevance_score:desc&mailto=${MAILTO}&select=id,title,publication_year,cited_by_count,doi,abstract_inverted_index" \
  | jq -r '.results[] | .abstract_inverted_index as $idx
      | "- \(.title) (\(.publication_year), cites=\(.cited_by_count)) doi=\(.doi // "none")\n  \(([$idx // {} | to_entries[] | .key as $w | .value[] | {p:., w:$w}] | sort_by(.p) | map(.w) | join(" "))[0:280])"'
```

Each result yields {title, year, citation count, DOI, abstract text} — enough to cite and to
quote a verbatim snippet. Rank candidates by relevance first; break ties by `cited_by_count`.

**Query construction.** One focused query per *contribution*, built from its noun phrases
(C3 "Byzantine attack arena" → `federated learning Byzantine attack defense benchmark`). Keep it
to **~3-4 high-signal terms**: `title_and_abstract.search` effectively ANDs the terms, so a 5-6
word query over-constrains and returns zero. Generic queries ("benchmark leaderboard") pull
unrelated fields; long queries return nothing. Run 2-3 short phrasings per contribution and
merge, de-duplicating on DOI. Systems / implementation topics (e.g. a Rust kernel) are thinly
indexed in OpenAlex — fall to the web-search backstop for those.

## Semantic Scholar (secondary, key-gated)

Keyless requests are rate-limited and return HTTP `429` — do NOT rely on it unprompted. Use only
when `S2_API_KEY` is set, to enrich a paper already found via OpenAlex (TLDR, citation contexts):

```bash
[ -n "$S2_API_KEY" ] && curl -s --max-time 25 -H "x-api-key: $S2_API_KEY" \
  "https://api.semanticscholar.org/graph/v1/paper/search?query=byzantine+robust+federated+learning&limit=5&fields=title,year,tldr,citationCount,externalIds"
```

Without a key, skip S2 and stay on OpenAlex + web-search.

## Web-search (backstop)

When OpenAlex is thin for a contribution (fresh arXiv preprints, non-indexed venues), use the
`WebSearch` tool with the contribution's terms + `arxiv`, then confirm each hit resolves to a
real record before citing it. Never cite a paper you have not seen returned by a search.

## references.bib gap cross-check

To find retrieved papers missing from the draft's bibliography:

```bash
BIB=../references.bib                       # or the configured bib path
grep -ioE 'doi\s*=\s*[{"][^}"]+' "$BIB" | grep -ioE '10\.[0-9]+/[^} "]+' | sort -u   # cited DOIs
grep -ioE 'title\s*=\s*[{"][^}"]+' "$BIB"                                            # cited titles
```

For each retrieved DOI not in the cited-DOI set, the paper is a candidate gap. Normalize titles
(lowercase, strip punctuation) to catch papers cited without a DOI. A retrieved paper that is
both highly relevant and absent from both sets is a §2 related-work gap.

## Provenance

Log every query and the records it returned into the report's `§ Provenance`, so a reader can
re-run the exact search. A citation with no logged query is not grounded — downgrade its verdict
to **unverified**.
