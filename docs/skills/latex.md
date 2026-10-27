---
description: Build a LaTeX document and gate the result on its log, its PDF and the assignment it answers.
---

# `graphe:latex`

Build a LaTeX document and gate the result on its log, its PDF, and the assignment it answers.

Part of [graphe](../plugins/graphe.md): `/plugin install graphe@techne`, then `/graphe:setup`.

## When to use

- "Build this `.tex`."
- A build failed and the log needs triage.
- Checking a draft is actually finished before it gets submitted.
- Any point where the alternative is reading three thousand lines of `latexmk` output looking for the one line that matters.

## Usage

Invoke by name in Claude Code:

```
/graphe:latex
```

Or run the builder directly from a techne checkout. The path is a `.tex`, or a directory holding exactly one file with `\documentclass`:

```
uv run --no-project --quiet python plugins/graphe/skills/latex/scripts/latex.py <path>
```

Options:

| Option | Effect |
|---|---|
| `--prompt FILE` | Assignment text to check coverage against. Default: the lone `*.extracted.md` beside the source. |
| `--no-prompt` | Skip the coverage check. |
| `--no-prose` | Skip the plain-prose pattern check. |
| `--markers A,B` | Draft markers that must not survive into the PDF (default `FILL`, `TODO`, `XXX`, `CITATION NEEDED`). |
| `--overfull-pt N` | Report overfull boxes at or above N points (default 5). |
| `--engine {pdf,xelatex,lualatex}` | The latexmk engine flag (default `pdf`). |

A `## latex` section in the repo's `.claude/skill-context.md` sets `markers`, `overfull_pt` and `engine` per repo, and the options override it. There are no Python dependencies; the script needs TeX Live and poppler. It runs through `uv run` rather than `python`, which is not on PATH on a machine that ships only `python3`.

## Why one command

`latexmk` exits 0 on a document whose every citation resolved to `[?]`, so the exit code is not the signal and the parsed log is. Building and gating are fused for that reason: a separate verify step is a step that gets skipped on exactly the run where it mattered.

The exit code carries the verdict. `0` built clean, `1` did not build, or bad path, `2` built and the PDF is wrong.

## What it gates on

Errors come with `file:line`. Gate ids are `tex-error`, `undefined-cite`, `undefined-ref`, `duplicate-label`, `missing-glyph` and `draft-marker`. Blockers are the things that compile without complaint and are still wrong in the PDF: `[?]` from an unresolvable citation, `??` from a missing reference, a label defined twice so refs point at the last one, characters dropped because the font lacks the glyph, and draft markers surviving into the output. Three gates round that out: `bibliography` (BLOCK) reports every biber warning in the `.blg`, `unsettled` (BLOCK) fires when the log still asks for a rerun, and `no-pdf` (ERROR) fires when the run claimed success and wrote nothing. Warnings cover the largest overfull boxes, font substitution and package chatter.

One class is advisory. Coverage regexes problem headers out of the assignment prompt and out of `pdftotext` output and reports what it could not locate. A document that renumbers its headers trips it while being complete, so it prints as `REVIEW` and never decides the exit code.

The length budget is a gate. The root `.tex` declares it on one comment line before drafting, `% budget: 4 pages`, `% budget: 3000 words` or both joined by a comma, and `budget` (BLOCK) fires when the PDF is over it or the line cannot be read. A document with no limit declares `% budget: none` and gets its measured length instead. Pages count the whole PDF. A venue that limits the pages before the references adds body pages, `% budget: 7 pages, 6 body pages` (six plus one of references) or `% budget: 9 body pages` (references free): read from the PDF's text through `pdftotext`, the body runs over when the first references heading (References, Bibliography, Works Cited or Literature Cited on a line of its own) falls after the first line of the page past the limit, the first-line rule of ACL's pubcheck, which also ends the body at Limitations or Acknowledgments where this gate ends it at the references alone. Appendices placed before the references count as body. Folios, running heads (the outermost edge line, confirmed on other pages, so a document under three pages keeps them), a review copy's line-number ruler and contents-page entries are not lines; a head the gate cannot confirm stays a line and can push the heading off line 1, a loud error the BLOCK message locates. The real heading is the earliest heading-like line or a later one, so the earliest alone may block; the gate passes a body only when the PDF shows one such line or fits whole, and asks for a look (`REVIEW budget`) when it shows several (a head that names the section, a contents list run on, a table column), none, or `pdftotext` is missing. Words come from the source through `texcount -inc -sum` (text, headers and captions, bibliography left out), the way Overleaf counts. The root and the files it loads by `\input` or `\include` have their `\iffalse` and `comment` blocks left out, which Overleaf's count keeps; files that the `import` or `subfiles` packages load (`\subimport`, `\import`, `\subfile`, `\includefrom`, `\inputfrom`) are followed by `texcount` itself, which counts their hidden blocks; the `\title` text counts as a header, where the markdown gate leaves out the title block. A document that declares no budget gets a `REVIEW budget` line asking for one, as does a declared limit the gate cannot measure (pages it cannot count, or a word limit with no `texcount`; `/graphe:setup` lists it). A `budget:` comment is a declaration when it opens with a number, a number word before `page(s)` or `word(s)`, a `_` placeholder, or `none`/`unlimited`/`no limit` alone, and then it must parse (`max 4 pages`, `~1200 words`, `4 pp`, `4 sheets` and `1200 wrods` are unreadable and block; write `4 pages` or `1200 words`, with an optional full stop); any other `budget:` comment is prose. When the build fails, the PDF checks (draft markers, coverage, prose and budget) run only if the build wrote a new PDF, since the file may be an earlier run's. The sentence-level prose check below cannot see a document that states each result three times, and this gate exists because one such document passed it.

Prose is advisory too. The skill has the writer read `_shared/plain-prose.md` before drafting, and the gate reports the patterns that file lists (em-dashes, throat-clearing, commentary on the paper itself, ornate verbs, filler, stacked hedges) and sentences over 40 words as `REVIEW prose`. The patterns live in the rubric, so what the writer reads and what the gate checks cannot drift. `--no-prose` skips it.

## Engine

latexmk driving local TeX Live pdflatex. Not tectonic: it ships its own biblatex against the system biber, and the resulting version skew is a known issue class rather than an accident, which `biblatex-chicago` + biber is squarely in the path of. Not texlogsieve or texfot either, good as they are at summarizing for a human: the log wrapping they exist to repair is repaired upstream instead, by unwrapping the log at the source with `max_print_line`.

## Testing it

`make test-unit` runs the suite. The gate parsers are covered by unit tests over fixture log text, which is where every defect found so far has lived: a regex that matched nothing, or a finding reported when it should have been suppressed. Six end-to-end cases build real documents and assert the exit code.

Those need TeX Live, and CI does not install it. Rather than let them skip unnoticed, a guard test fails when the toolchain is missing and `TECHNE_NO_TEX=1` is not set; `validate.yml` sets it and says why. The suite therefore either built the documents or declared in writing that it did not.

## See also

- [`graphe:pdf`](pdf.md): markdown in, PDF out, a different pipeline.
- [`graphe:paper`](paper.md): scaffolding a new paper directory rather than building an existing one.

## Full instructions

[`SKILL.md` on GitHub](https://github.com/ajbarea/techne/blob/main/plugins/graphe/skills/latex/SKILL.md) holds the full instructions Claude follows for this skill.
