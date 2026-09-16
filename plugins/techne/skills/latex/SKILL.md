---
name: latex
description: Build a LaTeX document and gate the result on its log, its PDF, and the assignment it answers. Use when a .tex needs compiling, when a build fails and the log needs triage, when checking a draft is finished before submitting it, or when asked whether a PDF is clean. Covers the engine choice, the gates that catch a document that compiled but is still wrong, and the log-reading traps.
disable-model-invocation: false
allowed-tools: Bash Glob Grep Read Edit
---

# LaTeX

Build and gate in one command. Do not go looking for an engine: the decision is
made below and the runner is in this skill.

## Run it

```
python ${CLAUDE_PLUGIN_ROOT}/skills/latex/scripts/latex.py <path>
```

`<path>` is a `.tex`, or a directory holding exactly one file with
`\documentclass`. Nothing needs installing beyond TeX Live and poppler.

Read the exit code, not the output's tone:

| Code | Meaning |
|---|---|
| 0 | Built and every gate passed. Any `REVIEW` line still needs your eye. |
| 1 | Did not build. One or more `ERROR` findings; everything downstream is hidden. |
| 2 | Built, and the PDF is wrong. `BLOCK` findings, each visible in the output. |

**Never report a build as fine on `latexmk`'s exit code.** It exits 0 on a
document whose every citation resolved to `[?]`. That is why building and gating
are one command here and not two: a separate verify step is a step that gets
skipped on the run where it mattered.

## The gates

| Severity | Gate | Catches |
|---|---|---|
| ERROR | `tex-error` | Anything that stopped the run, with `file:line`. |
| ERROR | `no-pdf` | The run claimed success and wrote nothing. |
| BLOCK | `undefined-cite` | `[?]` in the text. Both spellings: classic `Citation undefined`, and biblatex's own "entry could not be found". |
| BLOCK | `bibliography` | Every biber `WARN`/`ERROR` in the `.blg`. |
| BLOCK | `undefined-ref` | `??` in the text. |
| BLOCK | `duplicate-label` | Two `\label`s with one name; refs silently point at the last. |
| BLOCK | `missing-glyph` | Characters dropped from the PDF because the font lacks them. Nothing on screen marks the hole. |
| BLOCK | `draft-marker` | `FILL`, `TODO`, `XXX` surviving into the PDF. |
| BLOCK | `unsettled` | The log still asks for a rerun, so cross-references are stale. |
| WARN | `overfull`, `font-substitution`, `package` | Largest five overfull boxes, then a count. |
| REVIEW | `coverage` | Problem headers in the prompt with no match in the PDF. |

`--markers`, `--overfull-pt` and `--engine` move the thresholds. Read the
`## latex` section of `<repo>/.claude/skill-context.md` for per-repo marker
words before overriding them.

## Coverage is a heuristic and never fails the build

It regexes `Problem|Question|Exercise|Task|Bonus` + a number out of the prompt
and out of `pdftotext` output, then reports what it could not find. A document
that renumbers or rewords its headers trips it while being complete. Report the
`REVIEW` line to the user as something to confirm; do not call the homework
incomplete on the strength of it, and do not suppress it either.

The prompt is auto-detected only when exactly one `*.extracted.md` sits beside
the source that is not the document's own sidecar. Two candidates means it asks
for `--prompt`. For `classes/csci739-*`, the prompt lives in the read-only clone
repo, not next to the solutions, so pass it:

```
python .../latex.py 03-assignments/hw1 \
  --prompt ../csci739-quantum-machine-learning-hw/"Homework 1"/main.tex
```

## The toolchain, and why

`# research(2026-09)`

- **latexmk driving local TeX Live pdflatex.** latexmk resolves the pass count
  and calls biber itself. It is what these documents already build under.
- **Not tectonic**, though it is installed and is the better story on paper
  (self-contained, fetches its own packages, reproducible bundles). It ships its
  own biblatex against your system biber, and that pairing breaks on version
  skew often enough to be a known issue class, not an accident
  ([#893](https://github.com/tectonic-typesetting/tectonic/issues/893),
  [#1220](https://github.com/tectonic-typesetting/tectonic/issues/1220)).
  `biblatex-chicago` + biber 2.19 is exactly the combination at risk. Reach for
  tectonic only on a machine with no TeX Live, and expect the bibliography to be
  the thing that fails.
- **Not texlogsieve or texfot**, though texlogsieve is installed and is the best
  of the log summarizers. Both produce prose for a human to read; parsing another
  tool's prose to reach a verdict adds a format to track. The wrapping problem
  they solve is solved upstream instead, below.

## Three things that will look like mistakes

- **`max_print_line=10000` in the build environment.** TeX breaks log lines at
  79 columns, mid-word, mid-filename. Every regex over a raw log is wrong at the
  wrap points, which is the entire reason the log-filter tools exist. Setting it
  unwraps the log at the source. Remove it and the gates start missing findings
  rather than failing loudly.
- **Downstream findings are hidden when the build errored.** A run that died
  wrote no `.aux`, so every `\ref` and `\cite` in the document reads as
  undefined. Reporting that cascade buries the one line to fix. The count is
  still printed.
- **The `.blg` regex is unanchored.** biber prefixes each line with its own
  module trace (`[0] Biber.pm:123> WARN - ...`), so anchoring the severity to
  the start of the line silently matches nothing. That bug shipped once and made
  a missing citation read as a clean build.

## Changing a gate

The regexes are covered by `make test-unit` in the techne repo, against fixture
log text. Add the fixture with the change; every defect in this script so far
has been a misclassification a three-line test would have caught.

## Not this skill

- Markdown in, PDF out: `techne:pdf`.
- Scaffolding a new paper directory: `techne:paper`.
