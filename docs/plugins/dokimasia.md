---
description: dokimasia plugin, bibliography verification for LaTeX projects. Lint a .bib offline, verify entries against arXiv and Crossref, and check every cited key rendered.
---

# dokimasia

dokimasia verifies a LaTeX project's bibliography. It lints any `.bib` or hand-written `thebibliography` offline, checks arXiv ids and DOIs against arXiv and Crossref, and checks that every cited key rendered in the built document.

## Use it when

- You are about to submit a paper and want the references checked.
- A reference list may hold fabricated or drifted entries.
- A push gate should fail on a dangling citation or an orphan entry.

## Install

```text
/plugin marketplace add ajbarea/techne
/plugin install dokimasia@techne
```

## Needs

[uv](https://docs.astral.sh/uv/). If `command -v uv` prints nothing, install it with `curl -LsSf https://astral.sh/uv/install.sh | sh`. The `verify` mode also needs network access to `export.arxiv.org` and `api.crossref.org`.

## Set up

dokimasia has no setup skill. Configuration is optional: put `dokimasia.toml` at the project root (the [check page](../skills/check.md#configuration) lists the keys).

## Skills

| Skill | Use it to |
|---|---|
| [`dokimasia:check`](../skills/check.md) | Lint, verify and render-check a bibliography. |

Ask Claude to "check my citations" in a LaTeX project, or run `/dokimasia:check`. The [check page](../skills/check.md) describes each mode, the exit codes (`0` clean, `1` findings, `2` usage or configuration error) and the one-file script.

## Troubleshooting

- **`uv: command not found`.** Install uv as above and open a new terminal.
- **A lookup fails.** dokimasia reports a lookup it could not make apart from an entry that is wrong. Check that the machine can reach `export.arxiv.org` and `api.crossref.org`, then run it again.
