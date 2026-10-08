# `dokimasia:check`

Verify a LaTeX project's bibliography: lint any `.bib` offline, resolve its identifiers against arXiv and Crossref, and confirm every cited key rendered.

Named for the Athenian *dokimasia*, the scrutiny of a candidate's credentials before office.

## When to use

- "Check my citations." "Verify `references.bib`."
- Before submitting a paper.
- A reference list may contain fabricated or drifted entries.
- Any point where the alternative is trusting an entry because it looks right.

It checks metadata, not claims. Whether a sentence describes its source correctly is a reading task it cannot do.

## Usage

Invoke by name in Claude Code:

```
/dokimasia:check
```

Or run the script directly from a techne checkout. It is one standard-library file and needs Python 3.11 or later. `--no-project` keeps `uv` from creating a `.venv` in your project; `python3` works too:

```
uv run --no-project --quiet python plugins/dokimasia/skills/check/scripts/dokimasia.py [--root DIR] [--require-built] [{lint,verify,rendered}] [DOC.tex ...]
```

| Mode | Network | Checks |
|---|---|---|
| `lint` | no | Identifiers present and well formed, no duplicate keys across files, no dangling citation, no orphan entry, no citation of a key the reading log stages as unread. |
| `verify` | yes | Title, first-author surname and year against the arXiv or Crossref record. |
| `rendered` | no | Every key a document cites is in its `.bbl`. |

The mode defaults to `lint`. Exit codes: `0` clean, `1` findings, `2` usage or configuration error.

## Why three passes

They fail differently. `lint` is deterministic and fit for every push. `verify` depends on third-party APIs, so a push gate would fail for reasons that have nothing to do with the bibliography; run it on a schedule, where it reports rather than blocks. `rendered` needs a built document.

## Verify keeps five outcomes apart

Conflating them is how a blind spot goes quiet.

- **Verified**: resolved and matched.
- **Drift**: resolved, and the file differs from the source.
- **Unresolved**: the entry has an identifier and the lookup did not answer. The reason is printed. This says nothing about the entry, and a throttled host is waited out rather than counted.
- **Unverifiable**: no `eprint` and no `doi`, so nothing can be resolved. Named on every run.
- **Exempt**: listed in the config with a reason. The reason is printed.

A failed lookup is never cached. A 200 response that does not parse counts as a failed lookup, and only a valid empty arXiv feed means "no such record".

Year is compared only where it is sound: against the arXiv posting year for an arXiv preprint, and against either the issued or the print year for a DOI entry. A venue-dated entry is never checked against its preprint's arXiv year.

## Rendered

Documents are derived: any `.tex` with a `\documentclass` outside a comment. A `subfiles` child is not a document. Citations are read from the document and every file it reaches through `\input`, `\include`, `\subfile` and the `\import` family, for natbib and biblatex commands in any capitalisation. Comments, `\verb`, verbatim text and macro definitions are skipped. A document is checked against the bibliographies it names with `\bibliography` or `\addbibresource`, or all of them when it names none. `\nocite{*}` counts every entry of those bibliographies as cited, and lint names the documents where that happens. Keys are parsed out of the `.bbl` (`\bibitem` for BibTeX, `\entry` for biber), so `li2020` does not pass because `li2020b` rendered.

The `.bbl` is the same stem in `outdir` when set and present there, else beside the `.tex`. An `exclude` entry that matches no directory is named in the output. A document with no `.bbl` is reported as not built, with a count in the summary line. `--require-built` makes that a failure for a document that cites something or names a bibliography. `rendered` also names the `.tex` files under a document's directory that no document reaches, so an include form the tool does not follow is visible.

## Configuration

Optional. Put `dokimasia.toml` at the project root, or a `[tool.dokimasia]` table in `pyproject.toml`. An unknown key is an error.

```toml
bib = ["references.bib"]        # default: every *.bib under the root
exclude = ["vendor", "old/drafts"] # a name skips that directory anywhere; a path with / is
                                # a prefix from the root
cache = ".dokimasia-cache.json" # verify cache; must stay inside the root
outdir = "build"                # where builds write the .bbl, relative to each document
orphans = true                  # report entries nothing cites
[intake]                        # optional reading log
file = "related-work/intake.md"
staged_headings = ["not yet positioned", "do not cite"]
[exempt.title]                  # key = reason
smith2024x = "arXiv's own title misspells a word"
[exempt.record]                 # key = reason: skips first author and year
```

A configured intake file that does not exist is an error, as is a cache file that is not a JSON object. The root search stops at the git top-level. Every exemption needs a reason, and one naming a key that is not in the bibliography is a lint finding. Set `DOKIMASIA_MAILTO` to use Crossref's polite pool.

## Testing it

`make test-unit` covers the parser, the config rules, the citation and `.bbl` readers, the lookup and cache behaviour, and the exit codes against scratch projects. The lookups are faked; no test touches the network.

## See also

- [`graphe:latex`](latex.md): builds the document whose `.bbl` `rendered` reads.
