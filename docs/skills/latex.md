# `techne:latex`

Build a LaTeX document and gate the result on its log, its PDF, and the assignment it answers.

## When to use

- "Build this `.tex`."
- A build failed and the log needs triage.
- Checking a draft is actually finished before it gets submitted.
- Any point where the alternative is reading three thousand lines of `latexmk` output looking for the one line that matters.

## Usage

Invoke by name in Claude Code:

```
/techne:latex
```

Or run the builder directly from a techne checkout. The path is a `.tex`, or a directory holding exactly one file with `\documentclass`:

```
uv run --quiet python plugins/techne/skills/latex/scripts/latex.py <path>
```

There are no Python dependencies; the script needs TeX Live and poppler. It runs through `uv run` rather than `python`, which is not on PATH on a machine that ships only `python3`.

## Why one command

`latexmk` exits 0 on a document whose every citation resolved to `[?]`, so the exit code is not the signal and the parsed log is. Building and gating are fused for that reason: a separate verify step is a step that gets skipped on exactly the run where it mattered.

The exit code carries the verdict. `0` built clean, `1` did not build, `2` built and the PDF is wrong.

## What it gates on

Errors come with `file:line`. Blockers are the things that compile without complaint and are still wrong in the PDF: `[?]` from an unresolvable citation, `??` from a missing reference, a label defined twice so refs point at the last one, characters dropped because the font lacks the glyph, and draft markers surviving into the output. Warnings cover the largest overfull boxes, font substitution and package chatter.

One class is advisory. Coverage regexes problem headers out of the assignment prompt and out of `pdftotext` output and reports what it could not locate. A document that renumbers its headers trips it while being complete, so it prints as `REVIEW` and never decides the exit code.

## Engine

latexmk driving local TeX Live pdflatex. Not tectonic: it ships its own biblatex against the system biber, and the resulting version skew is a known issue class rather than an accident, which `biblatex-chicago` + biber is squarely in the path of. Not texlogsieve or texfot either, good as they are at summarizing for a human: the log wrapping they exist to repair is repaired upstream instead, by unwrapping the log at the source with `max_print_line`.

## Testing it

`make test-unit` runs the suite. The gate parsers are covered by unit tests over fixture log text, which is where every defect found so far has lived: a regex that matched nothing, or a finding reported when it should have been suppressed. Four end-to-end cases build real documents and assert the exit code.

Those need TeX Live, and CI does not install it. Rather than let them skip unnoticed, a guard test fails when the toolchain is missing and `TECHNE_NO_TEX=1` is not set; `validate.yml` sets it and says why. The suite therefore either built the documents or declared in writing that it did not.

## See also

- [`techne:pdf`](pdf.md): markdown in, PDF out, a different pipeline.
- [`techne:paper`](paper.md): scaffolding a new paper directory rather than building an existing one.
