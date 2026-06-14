# Citation verification — paper-review

MANDATORY pre-check. Every citation the draft already makes must resolve to a real record with
the right title / authors / year, and any claim *about* a cited work must match that work's
abstract. A single fabricated or mischaracterized citation is a research-integrity failure that
sinks the paper. Never trust a seed bib, a recalled citation, or a search snippet.

## Extract what the draft cites

```bash
grep -rohE '\\cite\{[^}]+\}' --include='*.tex' . | grep -oE '\{[^}]+\}' | tr -d '{}' \
  | tr ',' '\n' | sed 's/ //g' | sort -u                                  # cite keys used
grep -oE '^@[a-z]+\{[^,]+' references.bib | sed -E 's/^@[a-z]+\{//' | sort -u   # keys defined
```

A used key not defined in the bib is a broken citation. Then pull each entry's id / DOI / title.

## arXiv ids → arXiv API (authoritative)

Batch every arXiv id in one call (use **https**; `http` can return an empty body):

```bash
IDS=$(grep -oiE 'arxiv:[0-9]{4}\.[0-9]{4,5}' references.bib | sed -E 's/arxiv://I' | sort -u | paste -sd,)
curl -s "https://export.arxiv.org/api/query?id_list=${IDS}&max_results=60"   # Atom: title, author, published, summary
```

- An id that returns **no entry** is fabricated — **stop-ship**.
- A returned `<title>` that does not match the bib title means the id points to a **different
  paper** — stop-ship.
- Compare `<author>` and the `<published>` year against the bib; fix mismatches.
- Read `<summary>` (the abstract) to check any claim the draft makes about the paper.

Parse the feed with `python3 -c` + `xml.etree` (namespace `{http://www.w3.org/2005/Atom}`);
the entries returned vs. the ids requested reveals which ids are missing (fabricated).

## Published venues → OpenAlex or DOI

```bash
curl -s "https://api.openalex.org/works?search=<title>&per-page=1&mailto=<email>&select=title,publication_year,authorships,primary_location"
curl -s "https://api.openalex.org/works/doi:<doi>?mailto=<email>&select=title,authorships,publication_year"
curl -LsH "Accept: application/x-bibtex" "https://doi.org/<doi>"   # authoritative BibTeX, ready to paste
```

Confirm the top hit's title matches; take authors / venue / year from the authoritative record.

## Claims *about* a cited work

A descriptor like "parameter-free", "first to", "state-of-the-art", or "outperforms X" applied
to a *cited* paper is a claim about that paper — verify it against the paper's abstract, not
recall. (Real example: a draft called ArKrum "parameter-free"; its abstract says it *estimates*
the adversary count. A mischaracterization, caught only by reading the source.)

## Record the result

Log each citation → authoritative source + status (verified / mismatch-fixed / **stop-ship**) in
the report's §0, and stamp the bib header with the verification date. Stop-ship findings block
the novelty pass: a paper with a wrong citation is not ready, no matter how novel it is.
