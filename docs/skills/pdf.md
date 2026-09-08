# `techne:pdf`

Render markdown to print-quality PDFs through a Typst template, then verify the output against the source.

## When to use

- "Turn these markdown files into PDFs."
- Regenerating PDFs after editing the `.md` they were built from.
- Working out how the PDFs already sitting in a folder were produced.
- Any point where the alternative is probing `which pandoc weasyprint wkhtmltopdf` and picking from whatever answers.

## Usage

Invoke by name in Claude Code:

```
/techne:pdf
```

Or run the generator directly. `<src>` takes a single `.md` or a directory of them:

```
uv run --quiet --with typst python \
  plugins/techne/skills/pdf/scripts/render.py <src> <out-dir>
```

Nothing needs installing. The `typst` wheel bundles the compiler, and `cmarker` is pulled from Typst Universe on first compile and cached afterwards.

## Output checks

Every run prints the font families each PDF actually embedded. `--check-fonts LibertinusSerif TeXGyreHeros` turns that into a gate and exits non-zero on a mismatch, which is what catches a machine where a requested family is missing or unreadable and Typst has quietly fallen back.

Content is verified by diffing normalized `pdftotext` output against the markdown, not by looking at the page. Wrapped table cells reorder under `-layout` and repeated `table.header` rows appear once per page; both are extraction artifacts. Anything else is a real difference.

## See also

- [`techne:paper`](paper.md): LaTeX manuscripts in a papers monorepo, a different pipeline.
- [Conventions](../conventions.md): where generated artifacts belong relative to their sources.
