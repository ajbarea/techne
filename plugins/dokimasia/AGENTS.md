# dokimasia runbook

This is the guide for an agent running dokimasia, the bibliography checker, for a user. dokimasia has no setup skill and no doctor. It is one standard-library Python file that needs uv and Python 3.11 or later.

## Rules

- Run `lint` and `rendered` freely. They read the project and never touch the network.
- Run `verify` when the user asks, or on a schedule, not on every push. It calls arXiv and Crossref and waits 3 seconds between arXiv lookups.
- Report only what the script printed. Every summary and finding line starts with `dokimasia:`; findings go to stderr and the summary to stdout.
- A failed lookup is not a finding about the entry. Say the lookup failed and rerun later; never say the entry is wrong.

## 1. Check uv

Run `command -v uv`. If it prints nothing, the user installs it with `curl -LsSf https://astral.sh/uv/install.sh | sh` and opens a new terminal. Invoke the script through `uv run`, not `python`, which is absent on a machine that ships only `python3`.

## 2. Pick a mode

```
uv run --no-project --quiet python <plugin root>/skills/check/scripts/dokimasia.py [--root DIR] [--require-built] {lint,verify,rendered} [DOC.tex ...]
```

| Mode | Network | Use it to |
| --- | --- | --- |
| `lint` | no | Find missing or malformed identifiers, duplicate keys, dangling citations and orphan entries. |
| `verify` | yes, `export.arxiv.org` and `api.crossref.org` | Compare each entry's title, first author and year with its arXiv or Crossref record. |
| `rendered` | no | Confirm every cited key is in the built `.bbl`, or has a `\bibitem`. |

Exit codes: `0` nothing failed, `1` findings, `2` usage or configuration error (an unknown config key is one). For `verify`, only drift exits 1: unresolved, unverifiable and uncompared entries are listed on stdout and the run still exits 0, so read the summary line (`verified N, exempt N, unresolved N, ...`) before calling a bibliography verified. With `--require-built`, a document with no `.bbl` is a finding.

## 3. Fix each outcome

| Outcome | What to do |
| --- | --- |
| `drift` | Check the source, then decide with the user which side is wrong. |
| `unresolved` | The lookup did not answer. Rerun later. A 406, 429 or 503 is tried three times in all, waiting 5 then 20 seconds. |
| `unverifiable` | The entry has no `eprint` or `doi`. The user adds an identifier, or a human checks it. |
| `uncompared` | A hand-written item that does not quote its title. Check it by hand. |
| `exempt` | Listed in the config with a reason. Nothing to do. |
| `could not reach`, timeouts | Check that the machine reaches `export.arxiv.org` and `api.crossref.org`. |

## 4. Configuration

Optional. `dokimasia.toml` at the project root, or `[tool.dokimasia]` in `pyproject.toml`; `dokimasia.toml` wins when both exist. Ask before writing one. The keys are `bib`, `exclude`, `cache`, `outdir`, `orphans`, `[intake]`, `[exempt.title]` and `[exempt.record]`, and every exemption needs a reason. Set `DOKIMASIA_MAILTO` to use Crossref's polite pool. [The check page](https://ajbarea.github.io/techne/skills/check/) lists each key and its default.
