# `techne:paper`

Scaffold a new research paper in a papers-style monorepo — the per-paper LaTeX dir, a
results-harvest script, shared-bibliography wiring, and a portfolio-record row — so it builds
on day one and you only write prose.

## When to use

- Starting a new first-author paper: "scaffold a paper called X", "new paper from `<repo>`".
- NOT for editing an existing paper's prose or one-off non-repo documents.

## Usage

```
/techne:paper <name> [--from <repo>] [--venue <venue>]
```

Reads the `## paper` section of `.claude/skill-context.md` (author, bib path, portfolio
file), scaffolds `papers/<name>/`, build-verifies through the `techne:latex` runner (a fresh
scaffold's only finding is the template's `TODO` draft markers), and
adds a row to the portfolio file. Then write prose into the `% HARVEST:` blocks; run
`python harvest.py` to regenerate the evaluation table from the source repo's corpus.

## See also

- [`techne:sisters`](sisters.md): the sister repos a paper harvests from.
- [Conventions](../conventions.md).
