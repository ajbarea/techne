# `graphe:paper`

Scaffold a new research paper in a papers-style monorepo — the per-paper LaTeX dir, a
results-harvest script, shared-bibliography wiring, and a portfolio-record row — so it builds
on day one and you only write prose.

## When to use

- Starting a new first-author paper: "scaffold a paper called X", "new paper from `<repo>`".
- NOT for editing an existing paper's prose or one-off non-repo documents.

## Usage

```
/graphe:paper <name> [--from <repo>] [--venue <venue>]
```

Reads the `## paper` section of `.claude/skill-context.md` (author, bib path, portfolio
file), scaffolds `papers/<name>/`, build-verifies through the `graphe:latex` runner (a fresh
scaffold's only finding is the template's `TODO` draft markers), and
adds a row to the portfolio file. Then write prose into the `% HARVEST:` blocks, following `_shared/plain-prose.md`; run
`python harvest.py` to regenerate the evaluation table from the source repo's corpus.

It also adds a `conventions.md` sheet (filled from the target venue's accepted papers: structure and counts, titles only) and a `CUTS.md` log of every sentence cut. The rules for both live in `_shared/paper-quality.md`: the bar is clarity and conciseness, every sentence earns its place, the author writes the claim sentences, and integrity guards on ethics statements and restricted data.

## See also

- [`techne:sisters`](sisters.md): the sister repos a paper harvests from.
- [Conventions](../conventions.md).
