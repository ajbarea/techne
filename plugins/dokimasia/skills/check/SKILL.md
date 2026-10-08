---
name: check
description: Verify a LaTeX project's bibliography. Use when asked to verify a bibliography, check that references exist and match their source, check citations before submitting a paper, or when a reference list may contain fabricated or drifted entries, such as "check my citations" or "verify references.bib". Lints any .bib or hand-written thebibliography offline, resolves arXiv ids and DOIs against arXiv and Crossref, and checks that every cited key rendered in the built document. Not for formatting or styling a .bib, and it cannot tell whether a sentence describes its source correctly.
disable-model-invocation: false
allowed-tools: Bash Glob Grep Read
---

# Check a bibliography

Three passes over any LaTeX project's `.bib`, or over a reference list written by hand in
`thebibliography`. Run the one that answers the question; do not judge a reference by memory.

## Run it

```
uv run --no-project --quiet python ${CLAUDE_SKILL_DIR}/scripts/dokimasia.py [--root DIR] [--require-built] {lint,verify,rendered} [DOC.tex ...]
```

The script is one file with no dependencies and needs Python 3.11 or later. Invoke it through
`uv run` rather than `python`, which is absent on a machine that ships only `python3`.

| Mode | Network | Checks |
|---|---|---|
| `lint` | no | Every entry has an identifier, identifiers are well formed, no duplicate keys, no dangling citation, no orphan entry, no citation of a key the reading log still stages as unread. For a hand-written list: no duplicate `\bibitem`, no citation without one, no item nothing cites. |
| `verify` | yes | Resolves each `eprint` and `doi` and compares title, first-author surname and year with what the source returns. A hand-written entry is resolved through an arXiv id or DOI printed in it. |
| `rendered` | no | Every key a document cites is in its `.bbl`, or has a `\bibitem` in its hand-written list. With no arguments it checks every document under the root; with arguments, only those `.tex` files. |

Run `lint` freely. Run `verify` on request or on a schedule, not on every push: it calls
arXiv and Crossref and is slow on purpose (3 seconds between arXiv lookups).

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Clean. |
| 1 | Findings: lint findings, verify drift, a key that did not render, or with `--require-built` a document with no `.bbl`. |
| 2 | Usage or configuration error, including an unknown config key. |

Findings print on stderr and the summary on stdout, every summary and finding line prefixed `dokimasia:`; key lists and file details under a line are indented.

## Verify outcomes

| Outcome | Meaning | Action |
|---|---|---|
| verified | Resolved and matched. | None. |
| drift | Resolved, and the title, first author or year differs from the source. | Check the source, then decide which side is wrong. |
| unresolved | The entry has an identifier and the lookup did not answer. The reason is printed (`HTTP 406`, `TimeoutError`, `unparseable response`, `no matching record`). | Rerun later. Say nothing about the entry. |
| unverifiable | No `eprint` and no `doi` (for a hand-written entry, none printed), so there is nothing to resolve. Named every run. | Add an identifier, or accept that a human checks it. |
| exempt | Listed in the config with a reason. The reason is printed. | None. |

A failed lookup is never cached and never a finding. A throttled host (406, 429, 503) is
waited out: a lookup tries three times, 5 then 20 seconds apart.

## Hand-written reference lists

A document that writes `\begin{thebibliography}` and `\bibitem` itself has no `.bib` and never
builds a `.bbl`. Its items are its entries, and it draws on no `.bib` in the project, unless it
also names one with `\bibliography`. Items may sit in an `\input` file inside the block. A list
inside `\iffalse`, a `comment` environment or a `\newenvironment` definition is not read. A
project whose only reference lists are hand-written is not a configuration error.

- `rendered` checks that every cited key has a `\bibitem`; such a document is never "not built".
  A document that also names a `.bib` is checked against both, and still needs its `.bbl`.
- A `.bbl` pasted in with `\input`, as arXiv submissions do, is build output: it counts as
  rendered, and its entries are checked through the `.bib` it came from.
- `lint` does not require an identifier: printed styles routinely drop the DOI. It counts the
  items that print none, and `verify` names each of them as unverifiable.
- `verify` resolves only an arXiv id or DOI printed in the item, then compares the record with
  the printed text. A quoted title is compared as a `.bib` title is; an unquoted one must start
  a printed field, so a real title inside a longer invented one is drift. Of the source's
  authors, the first printed before the title must be its first author. A year is compared
  against a Crossref record, and against arXiv only where a year follows the arXiv id. It never
  looks an entry up by its title: a search hit is weaker evidence than a resolved identifier.
- One gap is left: an unquoted entry whose venue is named exactly like the source's title
  passes the title check.
- Output names a hand-written entry with its file, `key (paper.tex)`, since two papers may
  each print their own `smith2020`. Exemptions use the bare key.

## Rules for Claude

- **An unresolved entry is never edited on that basis.** It says the lookup failed, not that the entry is wrong.
- **A drift finding is checked against the source before the entry is changed.** Open the arXiv or DOI record. The source is sometimes the wrong side; that case is an `exempt` entry with a reason, not an edit.
- **Never use an LLM's own judgement as evidence that a reference exists.** Existence comes from `verify` or from a record you opened.
- **Report counts from the summary line** (`verified N, exempt N, unresolved N, unverifiable N, drift N`), and name the unresolved reasons. Do not round them into "mostly fine".
- **A document that is not built is not checked.** Say which documents `rendered` skipped; offer to build them with `/graphe:latex`.

## Configuration

Optional. `dokimasia.toml` at the project root, or a `[tool.dokimasia]` table in
`pyproject.toml`; `dokimasia.toml` wins when both exist. The root is `--root`, else the
nearest ancestor holding either, else the git top-level, else the working directory. An
unknown key is an error, so a typo cannot quietly turn a check off.

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
[exempt.title]                  # key = reason: skip the title comparison
smith2024x = "arXiv's own title misspells a word"
[exempt.record]                 # key = reason: skip first author and year
```

Hidden directories and `node_modules` are always skipped. Every exemption needs a reason, and
an exemption for an entry that is not in the bibliography is a lint finding.

Documents are derived: any `.tex` with a `\documentclass` outside a comment, except a
`subfiles` child. Its citations include every file reached through `\input`, `\include`,
`\subfile` and the `\import` family, in any capitalisation of `cite`; comments, `\verb`,
verbatim text and macro definitions are skipped. A document is checked against the
bibliographies it names with `\bibliography` or `\addbibresource`, or all of them when it
names none, so one key in two unrelated papers' bibliographies is fine. `\nocite{*}` counts
every entry of its bibliographies as cited, and lint says which documents did that.

Its `.bbl` is the same stem in `outdir` when set and present there, else beside the `.tex`. `rendered` also names the
`.tex` files under a document's directory that no document reaches, so an include form this
tool does not follow shows up instead of passing silently. `--require-built` fails only for a
document that cites something or names a bibliography.

A configured `[intake] file` that does not exist is an error, as is a `cache` outside the root
or a cache file that is not a JSON object. The root search stops at the git top-level.

Set `DOKIMASIA_MAILTO` to your address to use Crossref's polite pool. It is added to Crossref
requests and the User-Agent, and never stored.

## Without Claude

It is one standard-library file. From any checkout of techne:

```
python3 plugins/dokimasia/skills/check/scripts/dokimasia.py lint
```

Or fetch just that file and run it where the project is. Add `lint` and `rendered
--require-built` to CI, and `verify` to a weekly schedule.

## Not this skill

- Formatting, sorting or restyling a `.bib`.
- Whether a sentence in the paper describes its source correctly: the script compares metadata, not claims.
- Building the document: `graphe:latex`.
