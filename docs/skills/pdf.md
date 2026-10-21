---
description: Render markdown to print-quality PDFs with a Typst template and verify the output against the source.
---

# `graphe:pdf`

Render markdown to print-quality PDFs through a Typst template, then verify the output against the source.

Part of [graphe](../plugins/graphe.md): `/plugin install graphe@techne`, then `/graphe:setup`.

## When to use

- "Turn these markdown files into PDFs."
- Regenerating PDFs after editing the `.md` they were built from.
- Working out how the PDFs already sitting in a folder were produced.
- Any point where the alternative is probing `which pandoc weasyprint wkhtmltopdf` and picking from whatever answers.

## Usage

Invoke by name in Claude Code:

```
/graphe:pdf
```

Or run the generator directly from a techne checkout. `<src>` takes a single `.md` or a directory of them:

```
uv run --no-project --quiet --with 'typst>=0.15,<0.16' python \
  plugins/graphe/skills/pdf/scripts/render.py <src> <out-dir>
```

The `typst` wheel bundles the compiler, and `cmarker` is pulled from Typst Universe on first compile and cached afterwards. The font report needs `strings` (binutils, present on most systems), and the content check below needs poppler's `pdftotext`. A directory source renders its `*.md` files non-recursively, and the PDFs land beside the sources by default; the skill renders into a `_typst-preview/` folder first when that would overwrite existing PDFs. The font stack is Charter, XCharter, then Libertinus Serif for text, Helvetica Neue through Libertinus Serif for headings, and SF Mono, Menlo, Consolas, then DejaVu Sans Mono for code.

Exit codes: `0` rendered, `1` font drift under `--check-fonts`, a PDF over its length budget or an unreadable budget line, `2` the directory holds no `*.md`.

## Output checks

Every run prints the font families each PDF actually embedded. `--check-fonts LibertinusSerif TeXGyreHeros` turns that into a gate and exits non-zero on a mismatch, which is what catches a machine where a requested family is missing or unreadable and Typst has quietly fallen back.

A markdown file declares its length budget on one line before drafting: `<!-- budget: 1200 words -->`, `<!-- budget: 3 pages -->`, or both joined by a comma; a document with no limit declares `<!-- budget: none -->`. Each render prints the measured length against it, `BLOCK budget` and exit 1 when the PDF is over it, and `REVIEW budget` when none is declared or a declared limit cannot be measured. `<!-- budget: 8 pages before references -->` counts pages up to the one holding the first `[1]` reference entry (a numbered list; otherwise a `REVIEW budget`). Words count the markdown body after the title block, without code, link targets, comments or a References, Bibliography or Works Cited section (up to the next heading of its level).

Each render also prints `REVIEW prose` lines for the markdown source: the patterns listed in `_shared/plain-prose.md` and sentences over 40 words, with code and link targets ignored. They never change the exit code; `--no-prose` skips them.

Content is verified by diffing normalized `pdftotext` output against the markdown, not by looking at the page. Wrapped table cells reorder under `-layout` and repeated `table.header` rows appear once per page; both are extraction artifacts. Anything else is a real difference.

## Testing it

`make test-unit` runs the suite. The markdown front end is covered by unit tests: what `_typst_str` escapes and in what order, what `split_front_matter` lifts out of a document and what it leaves in the body, and that the template has no placeholder the renderer forgot to fill. The end-to-end cases compile real documents through Typst, check the words survive the round trip, and check that a tight list sits on the line pitch while a loose one takes paragraph spacing.

Those need the typst wheel, and the first compile fetches cmarker from Typst Universe. CI declines that network dependency and sets `TECHNE_NO_TYPST=1` to say so; without the declaration the suite fails rather than skipping the renders unnoticed.

## See also

- [`graphe:paper`](paper.md): LaTeX manuscripts in a papers monorepo, a different pipeline.
- [Conventions](../conventions.md): where generated artifacts belong relative to their sources.

## Full instructions

[`SKILL.md` on GitHub](https://github.com/ajbarea/techne/blob/main/plugins/graphe/skills/pdf/SKILL.md) holds the full instructions Claude follows for this skill.
