---
name: pdf
description: Render markdown files to print-quality PDFs with a Typst template, and verify the output against the source. Use when the user wants a PDF built from markdown, wants stale PDFs regenerated after editing their .md, or asks how PDFs in a folder were produced. Covers the toolchain choice, the print template, and the checks that catch silent font and content drift.
disable-model-invocation: false
allowed-tools: Bash Glob Grep Read Edit
---

# PDF

Markdown in, print-quality PDF out. Do not go looking for a converter: the
decision is made and the generator is in this skill.

## Run it

The user gives a path and usually nothing else. Resolve the rest yourself:

- **A path to a directory:** render every `*.md` in it, non-recursively.
- **A path to one `.md`:** render that file.
- **No path:** ask which directory. Do not guess from the working directory.

**Where output goes.** Beside the sources by default, `foo.md` to `foo.pdf`. If
that would overwrite existing PDFs, render into a `_typst-preview/` subfolder
first, report what changed, and promote only when the user says so. Overwriting
a document someone is about to send is not yours to decide.

```
uv run --quiet --with typst python ${CLAUDE_PLUGIN_ROOT}/skills/pdf/scripts/render.py <src> <out-dir>
```

Nothing needs installing: the `typst` wheel bundles the compiler, and `cmarker`
is fetched from Typst Universe on first compile and cached.

Add `--check-fonts LibertinusSerif TeXGyreHeros` to fail the run if the embedded
fonts are not exactly those. Use it in any repeat build.

## The toolchain, and why

`# research(2026-09)`

- **Typst 0.15**, via the `typst` PyPI wheel. Typst is a valid pandoc
  `--pdf-engine`, but the wheel removes pandoc from the picture entirely and
  pins the compiler with the build. Typst is far faster than XeLaTeX at
  equivalent quality, and since 0.14 it writes tagged, PDF/UA-1-conformant
  output by default.
- **cmarker** for the markdown bridge, not pandoc. Its documented use case is
  markdown that stays canonical and keeps being edited, which is this one;
  pandoc is for one-time conversions. It also handles tables, footnotes and
  strikethrough.
- **Not headless Chrome.** It renders below a real typesetting engine, needs a
  browser on the machine, and the CSS gets no print engine behind it.
- **Not WeasyPrint.** It buys CSS reuse, but Windows-only font stacks fall back
  differently under Linux, so the design drifts.
- **Not `apt install pandoc`.** The Ubuntu candidate is 3.1.3, too old for the
  typst engine.

## Fonts

The template asks for Charter, then a sans, and falls back to what the wheel
carries: Libertinus Serif, New Computer Modern, DejaVu Sans Mono. Those three
always resolve, so a build never fails for a missing font. It can silently
change typeface instead, which is worse, so every run prints the families it
actually embedded.

Typst reads only TrueType and OpenType. A family present as a Type 1 `.pfb`
looks installed to `fc-list` and is invisible to Typst: `texlive-fonts-recommended`
ships Bitstream Charter that way, so requesting Charter on a TeX Live box
silently yields Libertinus. Confirm from the run's font line, never from
`fc-list`.

## Verifying a build

Diff the words, do not eyeball the page:

```
pdftotext -layout out/doc.pdf - | ...   # compare against the .md
```

Normalize both sides (strip markdown syntax and punctuation, casefold, split on
whitespace) and diff the token lists. Expect two benign classes of difference:

- **Tables.** `-layout` reads wrapped cells column by column, so tokens
  reorder. Check the reordered run is the same text before dismissing it.
- **Repeated table headers.** `table.header` reprints on page breaks, so a
  header row appears once per page.

Anything else is real. For geometry, `pdftotext -bbox` gives per-word boxes;
diff the y-pitch against a known-good reference rather than guessing at leading.

`pdfinfo` on Typst output prints `Syntax Error: Suspects object is wrong type
(boolean)`. It is a known spurious poppler warning about the MarkInfo
dictionary, not a defect in the file. Ignore it.

## The template

`templates/document.typ.tmpl`, placeholders in `{{DOUBLE_BRACES}}` filled by
`render.py`. Letter, 0.9in/0.95in margins, 11.2pt serif on a 17.25pt baseline,
uppercase accent headings on hairline rules.

Two things there are load-bearing and will look like mistakes:

- **The `{{TITLE}}` and `{{SUBTITLE}}` block.** The leading `# Heading` and an
  italic-only line after it are lifted out of the markdown by `render.py` so the
  subtitle can carry its own size and color. Leave them in the markdown and the
  subtitle renders as body text.
- **The `show table` re-emit.** cmarker returns tables carrying an explicit
  `inset: 0% + 5pt`, which beats a set rule and segments the header rule into
  per-column dashes. The rule re-emits the table without it. Dropping the inset
  is also the recursion guard: an inner `show table: it => it` does not stop the
  rule reapplying, and `..t.fields()` is rejected because `children` is not a
  named argument. Keep cmarker's `auto` columns; forcing `(1fr,) * n` makes a
  two-column prose table wrap badly.
