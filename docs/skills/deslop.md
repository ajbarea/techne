# `techne:deslop`

Scans the codebase for AI-generated slop in comments and docstrings (temporal markers, self-referential AI framing, narrative WHAT-comments, marketing padding) and proposes tightened rewrites.

## When to use

- After other AI assistants (Copilot, Gemini, GPT) have touched a repo.
- Auditing pending changes for verbose, low-value commentary.
- Cleaning up a codebase that's drifted toward over-narrated comments.

## What it targets

- **Temporal markers**: "as of 2025", "currently", "now we"
- **Self-referential AI framing**: "this function helps you", "let me explain"
- **Narrative WHAT-comments**: comments that restate what the code clearly does
- **Marketing padding**: "robust", "elegant", "powerful", "seamless"

## What it produces

A diff or report of proposed rewrites. The skill doesn't auto-commit; you review the changes.

## Sibling

[`techne:reslop`](reslop.md) goes further: it rewrites docstrings grounded in the actual implementation instead of just trimming them.

## Reads

- `<repo>/**/*.py`, `*.ts`, `*.vue`, etc. (configurable).
- Pending git diff (when scanning changes only).
