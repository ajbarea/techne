---
description: graphe:setup checks what the graphe document skills need on this machine (uv, TeX Live, poppler, strings, Chromium, pptx tools) and prints the install command for each gap.
---

# `graphe:setup`

Check what the graphe skills need on this machine and print the install command for each gap.

Part of [graphe](../plugins/graphe.md): `/plugin install graphe@techne`.

## When to use

After installing graphe, when a graphe skill reports `latexmk`, poppler, `strings` or Chromium missing, or to ask whether this machine can build LaTeX, PDFs or slides.

## Usage

```text
/graphe:setup
```

The skill runs a doctor script that only reads, then follows the [setup runbook](https://github.com/ajbarea/techne/blob/main/plugins/graphe/AGENTS.md). It installs nothing itself. The doctor needs python3 3.9 or newer.

## What it checks

| Check | Used by |
|---|---|
| `uv` | Every graphe script. |
| `latexmk`, `pdflatex` | `graphe:latex`, `graphe:paper`. |
| `texcount` | Optional. The `graphe:latex` word budget. |
| `biber` | Optional. Documents that use biblatex. |
| `pdftotext`, `pdfinfo`, `pdffonts`, `pdftoppm` | The `graphe:latex` gates and `graphe:slides`. One poppler install covers all four. |
| `strings` | The `graphe:pdf` font report. |
| `chromium` | `graphe:slides` web decks. Required, so a LaTeX-only user still sees `result: missing chromium`. |
| `pptx-renderer`, `node`, `pptxgenjs` | Optional. Building and rendering a `.pptx` deck. |

## Output

Each line starts with `ok`, `missing`, `optional` or `n/a`, then the check's name and a detail. A `missing` or `optional` line is followed by one or more `fix:` lines. The last line is `result: ready`, or `result: missing` with the names of the required checks that failed. The doctor exits 0 when nothing required is missing, and only reads.

## See also

- [graphe plugin](../plugins/graphe.md): install, needs and troubleshooting.

## Full instructions

[`SKILL.md` on GitHub](https://github.com/ajbarea/techne/blob/main/plugins/graphe/skills/setup/SKILL.md) holds the full instructions Claude follows for this skill.
