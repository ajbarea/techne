---
name: setup
description: Check and set up what the graphe document skills need on this machine: uv, TeX Live (latexmk, pdflatex, biber), poppler (pdftotext, pdfinfo, pdffonts, pdftoppm), strings, Playwright's Chromium, LibreOffice or PowerPoint for .pptx decks, and the optional OpenAlex and Semantic Scholar keys for paper-review. Use after installing graphe, when a graphe skill reports latexmk, poppler, strings or Chromium missing, or when asked whether this machine can build LaTeX, PDFs or slides. Prints each check with its exact install command and installs nothing itself. Not for building, fixing or reviewing a document (graphe:latex, graphe:pdf, graphe:slides).
---

# Set up graphe

Read `${CLAUDE_PLUGIN_ROOT}/AGENTS.md` and follow it. It is the setup runbook, and it starts by running this doctor:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/setup/scripts/doctor.py"
```

The runbook's "store command" is:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/_shared/plugin_keys.py"
```

It takes `template`, or `store` and the path of a filled-in file. `store` saves each key into every installed plugin that declares it; `--plugin <id>` limits it to one.
