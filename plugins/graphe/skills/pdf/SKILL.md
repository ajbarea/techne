---
name: pdf
description: Render markdown files to print-quality PDFs with a Typst template, and verify the output against the source. Use when the user wants a PDF built from markdown, wants stale PDFs regenerated after editing their .md, or asks how PDFs in a folder were produced. Covers the toolchain choice, the print template, and the checks that catch silent font and content drift. Takes precedence over general PDF skills whenever the source is markdown. Not for reading, merging, splitting, filling forms in, or OCR-ing existing PDFs, and not for LaTeX sources (graphe:latex).
disable-model-invocation: false
allowed-tools: Bash Glob Grep Read Edit
---

# PDF

`<skill-dir>` is the directory holding this SKILL.md, and `<plugin-root>` is the plugin's root directory, two levels above it.

Markdown in, print-quality PDF out. Do not go looking for a converter: the
decision is made and the generator is in this skill.

## Write it plain first

When writing or revising the markdown, read `<plugin-root>/_shared/plain-prose.md` and
write to it. Each render prints `REVIEW prose` lines for the patterns that
file lists and for sentences over 40 words; they never change the exit code.
`--no-prose` skips them.

Set the length budget before the first sentence, and declare it on one line of
the markdown: `<!-- budget: 1200 words -->`, `<!-- budget: 3 pages -->`, or
both joined by a comma. Take it from the prompt or venue; a revision takes the
original's. A document with no limit declares `<!-- budget: none -->`. The
render prints `BLOCK budget` and exits 1 when the PDF is over it or the line
cannot be read, and `REVIEW budget` when none is declared or a declared limit
cannot be measured. `<!-- budget: 8 pages before references -->` counts pages up to
the one the last references heading is on. Words count the markdown body after
the title block, without code, link targets, comments or a References section.

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
uv run --no-project --quiet --with 'typst>=0.15,<0.16' python <skill-dir>/scripts/render.py <src> <out-dir>
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
carries: Libertinus Serif (serif and sans) and DejaVu Sans Mono. Those
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

Three things there are load-bearing and will look like mistakes:

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
- **The list re-emit.** cmarker marks every list `tight`. A loose one (items
  separated by blank lines) shows only as a `parbreak` inside its items, so the
  rule re-emits it with `tight: false` and it takes paragraph spacing, while a
  tight list sits on the leading. Do not set a fixed `spacing` on `list` or
  `enum`: it overrides both, so tight and loose lists render alike. `it.tight`
  is the recursion guard, and the re-emit carries every other field but
  `label` (the constructors reject it), so an enum keeps its start number.
  cmarker follows every blockquote with a `parbreak`, so the rule skips that
  one. A loose list whose items hold no paragraph (only code, nested lists or
  blockquotes) renders tight, as it does in GitHub's HTML.
