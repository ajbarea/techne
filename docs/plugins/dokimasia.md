# dokimasia

dokimasia verifies a LaTeX project's bibliography. It lints any `.bib` or hand-written `thebibliography` offline, checks arXiv ids and DOIs against arXiv and Crossref, and checks that every cited key rendered in the built document. The [check page](../skills/check.md) describes each mode.

## Install

```bash
/plugin marketplace add ajbarea/techne
/plugin install dokimasia@techne
```

dokimasia needs [uv](https://docs.astral.sh/uv/). If `command -v uv` prints nothing, install it with `curl -LsSf https://astral.sh/uv/install.sh | sh`.

## First use

Ask Claude to "check my citations" in a LaTeX project, or run `/dokimasia:check`.

## Troubleshooting

- **`uv: command not found`.** Install uv as above and open a new terminal.
- **A lookup fails.** dokimasia reports a lookup it could not make apart from an entry that is wrong. Check that the machine can reach arxiv.org and api.crossref.org, then run it again.
