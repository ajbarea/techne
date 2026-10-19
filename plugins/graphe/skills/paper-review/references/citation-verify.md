# Citation verification — paper-review

MANDATORY pre-check. Every citation the draft already makes must resolve to a real record with
the right title / authors / year, and any claim *about* a cited work must match that work's
abstract. A single fabricated or mischaracterized citation is a research-integrity failure that
sinks the paper. Never trust a seed bib, a recalled citation, or a search snippet.

## Pacing

Use the retrieval script that SKILL.md names (shown here as `<retrieval script>`) for every
lookup below. It spaces requests per host across processes, waits out `Retry-After`, stops asking
a host that refused it, and sends your `OPENALEX_MAILTO` to OpenAlex and Crossref. Do not call
these hosts with `curl`. If the script prints `not checked: <host> refused until ...`, record
that citation as not checked and move on; do not retry it another way.

## Extract what the draft cites

```bash
grep -rohE '\\cite\{[^}]+\}' --include='*.tex' . | grep -oE '\{[^}]+\}' | tr -d '{}' \
  | tr ',' '\n' | sed 's/ //g' | sort -u                                  # cite keys used
grep -oE '^@[a-z]+\{[^,]+' references.bib | sed -E 's/^@[a-z]+\{//' | sort -u   # keys defined
```

A used key not defined in the bib is a broken citation. Then pull each entry's id / DOI / title.

A draft with an inline `thebibliography` block has no `.bib`: take the defined keys from its
`\bibitem`s and the ids, DOIs and titles from the item text, and point every recipe below at the
`.tex` instead of `references.bib`.

```bash
grep -oE '\\bibitem(\[[^]]*\])?\{[^}]+\}' draft.tex | grep -oE '\{[^}]+\}$' | tr -d '{}' | sort -u
```

## arXiv ids → arXiv API (authoritative)

Resolve every arXiv id in one call. Each line is one entry with `id`, `title`, `authors`, `year`
and `abstract`:

```bash
IDS=$(grep -oiE 'arxiv:[0-9]{4}\.[0-9]{4,5}' references.bib | sed -E 's/arxiv://I' | sort -u | paste -sd,)
uv run --no-project --quiet python <retrieval script> arxiv-id "$IDS"
```

- An id that returns **no entry** is fabricated — **stop-ship**.
- A returned `<title>` that does not match the bib title means the id points to a **different
  paper** — stop-ship.
- Compare `authors` and `year` against the bib; fix mismatches.
- Read `abstract` to check any claim the draft makes about the paper.

Ids requested but missing from the output are the fabricated ones.

## Published venues → OpenAlex or Crossref

```bash
uv run --no-project --quiet python <retrieval script> openalex '<title words>' --limit 1
uv run --no-project --quiet python <retrieval script> crossref '<doi>'   # title, authors, year, venue
```

Confirm the top hit's title matches; take authors / venue / year from the Crossref record.

## Claims *about* a cited work

A descriptor like "parameter-free", "first to", "state-of-the-art", or "outperforms X" applied
to a *cited* paper is a claim about that paper. Verify it against the paper's full text where
it is open access (arXiv PDF, open journal), else its abstract, never recall. (Real examples: a
draft called ArKrum "parameter-free"; its abstract says it *estimates* the adversary count. A
proposal summarized Kumar et al. as "expressive encodings stop the attack"; only the full text
shows the claim holds for an *underparameterized* attacker model.)

Summaries in the draft's own words count too, not only flag words: "X shows that trainable
circuits leak their inputs" overstates a paper that reports a *weak* privacy breach.

## Record the result

Log each citation → authoritative source + status (verified / mismatch-fixed / **stop-ship**) in
the report's §0, and stamp the bib header with the verification date. Stop-ship findings block
the novelty pass: a paper with a wrong citation is not ready, no matter how novel it is.
