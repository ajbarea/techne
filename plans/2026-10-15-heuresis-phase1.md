# heuresis phase 1 (store and terminal triage) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the heuresis plugin in the techne marketplace so `/heuresis:idea --now <text>` captures an idea into a private git store, searches papers, patents, products and AJ's own work, and files a verdict grounded in records a script has verified.

**Architecture:** A uv-managed Python package inside the plugin (`plugins/heuresis/heuresis/`) does every mechanical step: the idea store, source adapters, pooling, link and quote verification, verdict rules, board generation and git sync. Claude does the judgment steps: one skill orchestrates four Sonnet scout agents and one Opus judge agent, each of which talks to the package through a CLI. Paper retrieval lives in one stdlib-only file shared with `graphe:paper-review` through techne's existing `_shared/` copy convention.

**Tech Stack:** Python 3.12+, PyYAML, stdlib `urllib`/`html.parser`/`xml.etree`, pytest, ruff, ty, Claude Code plugin skills and agents, `claude plugin eval`.

**Spec:** `specs/2026-10-15-heuresis-design.md`. Read it before any task. This plan covers spec build-order phase 1 only.

## Global Constraints

- Work in the techne worktree `.claude/worktrees/heuresis-spec` (branch `docs/heuresis-spec`); never edit the main checkout.
- `requires-python = ">=3.12"`; ruff line length 100, rules `E F I UP B RUF`; `ty check` clean. Run `make lint` and `make test` from the worktree root after the last edit of each task.
- heuresis runtime dependencies: `pyyaml>=6.0.2` only. Everything else is stdlib.
- `_shared/scholarly.py` is stdlib-only and runs on Python 3.11+ via `uv run --no-project`.
- The canonical shared file is `plugins/techne/_shared/scholarly.py`; `plugins/graphe/_shared/scholarly.py` and `plugins/heuresis/_shared/scholarly.py` are byte-identical copies (`make guards` enforces this).
- API keys come only from environment variables: `OPENALEX_API_KEY`, `S2_API_KEY`, `LENS_API_TOKEN`, `EPO_OPS_KEY`, `EPO_OPS_SECRET`, `GITHUB_TOKEN` (fallback: `gh auth token`). Sensitive values never go in `userConfig`, because Claude Code does not substitute them into skill content or export them to Bash-tool processes (plugins-reference, "Reference a saved value").
- Skill and agent Markdown call the package as `env UV_PROJECT_ENVIRONMENT=${CLAUDE_PLUGIN_DATA}/venv uv run --quiet --directory ${CLAUDE_PLUGIN_ROOT} python -m heuresis ...` and pass every path as an absolute path (`--directory` changes the working directory).
- States: `inbox | trash | later | do | building | shipped | merged`. Types: `product | tool | research | improve`. `captured_via`: `terminal | phone | form | import`. Exact strings.
- Verdict rules (spec "Triage pipeline" step 5): `do` needs a verified closest rival with all four facets (domain, purpose, mechanism, evaluation) filled, and at least one paper source with status `ok`; otherwise the verdict becomes `later` with reason "insufficient evidence" and a revisit date. `merged` needs `duplicate_of` naming an existing idea.
- Published Markdown (`plugins/**`, `docs/**`, `README.md`) carries no personal email address and no machine path (`/home/`, `/mnt/`, `C:\Users`); `tests/test_plugin_packaging.py` enforces it.
- Prose in shipped files follows `plugins/graphe/_shared/plain-prose.md`: no em-dashes, plain verbs, no time estimates.
- Commit messages: Conventional Commits, no attribution trailers or session links of any kind.

## Plan deviations from the spec (flag to AJ in the PR)

1. **Run artifacts live in `runs/<id>/` beside the idea file**, not inside it. The spec says each triage step writes its output into the idea file. Scout records (up to 60 records with abstracts) would bury the readable file, so step outputs go to `runs/<id>/{restate,scout-papers,scout-patents,scout-products,scout-context,pool,judge,verify}.json`, committed with the idea. The idea file still gets the Restated section the moment restating finishes, and the checkpoint property the spec needs (resume from the last finished step) holds because each step's file exists or does not.
2. **Google Patents BigQuery is not in phase 1.** It needs a GCP project and billing account. Lens and EPO OPS cover patents; every verdict already reports patent coverage as partial. Add BigQuery only if both prove unusable.
3. **Plan and spec live in `plans/` and `specs/` at the repo root**, because the docs site builds `docs/` in strict mode and publishes every page there.

## Review Focus

1. **Idea text that YAML or Markdown would mangle** (colons, quotes, a leading `---`, `## ` lines, emoji, non-Latin scripts): the Idea section and title round-trip exactly; the file still parses. Test in Task 3.
2. **Two ideas with the same first words on the same day**: each gets its own id (`-2`, `-3`) and neither file is overwritten. Test in Task 3.
3. **A source that times out, returns 429, or returns malformed JSON**: the run continues, coverage says `failed` with the reason, and if every paper source failed the verdict cannot be `do`. Tests in Tasks 4 and 7.
4. **Evidence pages with HTML entities, curly quotes, line breaks inside the quoted passage, or text only rendered by JavaScript**: the first three still match; the last is dropped as "quote not found", never a crash. Test in Task 10.
5. **The ideas repo changed on the remote since the last pull** (phone capture, a second machine): publish rebases, regenerates `BOARD.md` and `LOG.md`, and pushes; a real conflict in an idea file aborts the rebase and leaves the local commit for AJ, with a clear message. Test in Task 11.

---

## File structure

```
plugins/heuresis/
  .claude-plugin/plugin.json        manifest + userConfig (ideas_repo, repos_root)
  README.md                         pointer README (packaging test shape)
  AGENTS.md                         setup runbook
  pyproject.toml  uv.lock           package = false, dependency pyyaml
  _shared/doctor_lib.py             copy of plugins/techne/_shared/doctor_lib.py
  _shared/scholarly.py              copy of plugins/techne/_shared/scholarly.py
  heuresis/__init__.py              version string
  heuresis/__main__.py              python -m heuresis
  heuresis/model.py                 constants + dataclasses (Idea, Record, Coverage, Verdict)
  heuresis/store.py                 parse/render idea files, ids, validation, verdict log
  heuresis/rules.py                 verdict rules, demotion to later
  heuresis/board.py                 BOARD.md and LOG.md generation
  heuresis/context.py               projects.toml, context.toml, init seeding
  heuresis/similar.py               duplicate candidates by word overlap
  heuresis/sources/__init__.py      Source protocol, registry, run_queries
  heuresis/sources/http.py          one HTTP helper with timeouts, size cap, errors
  heuresis/sources/papers.py        OpenAlex, Semantic Scholar, arXiv adapters over scholarly.py
  heuresis/sources/products.py      GitHub, Hacker News adapters
  heuresis/sources/patents.py       Lens, EPO OPS adapters
  heuresis/pool.py                  merge scout outputs, dedupe, cap
  heuresis/verify.py                fetch evidence, check quotes
  heuresis/render.py                Closest work / Fit / Product evidence sections from judge.json
  heuresis/sync.py                  commit, rebase, regenerate, push
  heuresis/cli.py                   argparse entry point for every step
  agents/scout-papers.md  agents/scout-patents.md  agents/scout-products.md
  agents/scout-context.md  agents/judge.md
  skills/idea/SKILL.md              orchestration
  skills/setup/SKILL.md  skills/setup/scripts/doctor.py
  evals/fires-idea/  evals/never-idea-paper-review/  evals/fires-setup/  evals/never-setup-idea/
plugins/techne/_shared/scholarly.py canonical shared retrieval
plugins/graphe/_shared/scholarly.py copy
plugins/graphe/skills/paper-review/references/retrieval.md   recipes call scholarly.py
tests/test_heuresis_*.py            one file per module
tests/fixtures/heuresis/            recorded API responses
```

The spec named the web scout `scout-web`; this plan calls it `scout-products` because it covers products, GitHub and Hacker News plus general web search, and `scout-web` read as "the only one that uses the web".

---

### Task 1: Plugin scaffold and packaging

**Files:**
- Create: `plugins/heuresis/.claude-plugin/plugin.json`, `plugins/heuresis/README.md`, `plugins/heuresis/pyproject.toml`, `plugins/heuresis/heuresis/__init__.py`, `plugins/heuresis/heuresis/__main__.py`, `plugins/heuresis/heuresis/cli.py`, `docs/plugins/heuresis.md`
- Modify: `.claude-plugin/marketplace.json` (append entry), `pyproject.toml` (dependency group, pytest `pythonpath`, ty `extra-paths`), `zensical.toml` (Plugins nav)
- Test: `tests/test_heuresis_cli.py`

**Interfaces:**
- Produces: `heuresis.__version__: str`; `heuresis.cli.main(argv: list[str] | None = None) -> int`; subcommand registry `heuresis.cli.build_parser() -> argparse.ArgumentParser` that later tasks extend by adding `sub.add_parser(...)` blocks inside `build_parser`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_heuresis_cli.py
"""heuresis CLI entry point."""

from __future__ import annotations

import heuresis
from heuresis import cli


def test_version_command_prints_the_package_version(capsys):
    assert cli.main(["version"]) == 0
    assert capsys.readouterr().out.strip() == heuresis.__version__


def test_unknown_command_exits_with_usage_error(capsys):
    try:
        cli.main(["no-such-command"])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("argparse should reject an unknown command")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_heuresis_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'heuresis'`

- [ ] **Step 3: Create the package, manifest and project files**

`plugins/heuresis/heuresis/__init__.py`:
```python
"""heuresis: capture an idea, search for prior work, file a grounded verdict."""

__version__ = "0.1.0"
```

`plugins/heuresis/heuresis/__main__.py`:
```python
from heuresis.cli import main

raise SystemExit(main())
```

`plugins/heuresis/heuresis/cli.py`:
```python
"""Command line for every mechanical heuresis step. Skills and agents call this."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

import heuresis


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="heuresis")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("version", help="print the heuresis version")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "version":
        print(heuresis.__version__)
        return 0
    raise AssertionError(f"unhandled command {args.command}")
```

`plugins/heuresis/pyproject.toml`:
```toml
[project]
name = "heuresis"
version = "0.1.0"
description = "Capture an idea, search for prior work, and file a verdict grounded in what was found."
requires-python = ">=3.12"
dependencies = ["pyyaml>=6.0.2"]

[tool.uv]
package = false
```

`plugins/heuresis/.claude-plugin/plugin.json`:
```json
{
  "name": "heuresis",
  "description": "Idea triage: capture an idea in plain text, search papers, patents, products and your own work for anything like it, and file it with a verdict grounded in records a script has checked.",
  "author": {"name": "AJ"},
  "repository": "https://github.com/ajbarea/techne",
  "homepage": "https://ajbarea.github.io/techne/plugins/heuresis/",
  "license": "MIT",
  "keywords": ["ideas", "prior-art", "triage", "research", "novelty"],
  "userConfig": {
    "ideas_repo": {
      "type": "directory",
      "title": "Ideas repository",
      "description": "Local clone of your private ideas repository. /heuresis:setup creates it if it does not exist yet."
    },
    "repos_root": {
      "type": "directory",
      "title": "Repositories folder",
      "description": "Folder holding your repo clones (papers, talks, your projects). heuresis reads your bibliography, notes, decks and ROADMAPs from here."
    }
  }
}
```

`plugins/heuresis/README.md` (pointer README; at most 20 non-blank lines, no Setup/Install heading):
```markdown
# heuresis

Idea triage: capture an idea in plain text, search papers, patents, products and your own work for anything like it, and file it with a verdict grounded in records a script has checked.

```
/plugin marketplace add ajbarea/techne
/plugin install heuresis@techne
```

Needs uv, git and gh. Install, first use and troubleshooting: [https://ajbarea.github.io/techne/plugins/heuresis/](https://ajbarea.github.io/techne/plugins/heuresis/).
```

`docs/plugins/heuresis.md`:
```markdown
# heuresis

heuresis keeps every idea in one private git repository and gives each one a first opinion grounded in prior work. It searches papers (OpenAlex, Semantic Scholar, arXiv), patents (Lens, EPO), products (GitHub, Hacker News, the web) and your own bibliography, notes, decks and repos, then names the closest existing work and files the idea as trash, later or do.

## Install

```bash
/plugin marketplace add ajbarea/techne
/plugin install heuresis@techne
```

heuresis needs [uv](https://docs.astral.sh/uv/), git and the GitHub CLI. Run `/heuresis:setup` after installing: it checks each one, creates your ideas repository, and lists the API keys that widen the search. The [setup runbook](https://github.com/ajbarea/techne/blob/main/plugins/heuresis/AGENTS.md) has every step.

## First use

Run `/heuresis:idea --now <your idea>`. Without `--now`, the idea is saved to the inbox for later triage.

## Troubleshooting

- **A source shows `skipped` in the verdict's coverage line.** Its API key is not set. `/heuresis:setup` lists which key each source needs.
- **A verdict says "insufficient evidence".** No paper source returned results, or the closest rival could not be verified. Run `/heuresis:idea --retriage <id>` later.
```

Append to `.claude-plugin/marketplace.json` `plugins` array:
```json
{
  "name": "heuresis",
  "description": "Idea triage: capture an idea, search papers, patents, products and your own work, and file it with a verdict grounded in checked records.",
  "source": "./plugins/heuresis",
  "category": "productivity"
}
```

In root `pyproject.toml`: add group `heuresis = ["pyyaml>=6.0.2"]` under `[dependency-groups]`, set `default-groups = ["dev", "epistole", "heuresis"]`, set pytest `pythonpath = ["tests", "plugins/epistole", "plugins/heuresis"]`, and ty `extra-paths = ["tests", "plugins/epistole", "plugins/heuresis"]`.

In `zensical.toml` Plugins nav, after dokimasia: `{ "heuresis" = "plugins/heuresis.md" },`.

- [ ] **Step 4: Lock and run the tests**

Run: `uv lock && uv sync && (cd plugins/heuresis && uv lock) && uv run pytest tests/test_heuresis_cli.py tests/test_plugin_packaging.py tests/test_docs_nav.py -v`
Expected: PASS (packaging test finds README, docs page, nav entry, homepage).

- [ ] **Step 5: Validate the manifest and commit**

Run: `make manifests plugin-validate`
Expected: `OK` lines, `Validation passed` for heuresis.

```bash
git add plugins/heuresis .claude-plugin/marketplace.json pyproject.toml uv.lock zensical.toml docs/plugins/heuresis.md tests/test_heuresis_cli.py
git commit -m "feat(heuresis): scaffold the plugin, package and docs page"
```

---

### Task 2: Shared scholarly retrieval

**Files:**
- Create: `plugins/techne/_shared/scholarly.py`, copies at `plugins/graphe/_shared/scholarly.py` and `plugins/heuresis/_shared/scholarly.py`
- Create: `tests/fixtures/heuresis/openalex_works.json`, `tests/fixtures/heuresis/arxiv_query.xml`, `tests/fixtures/heuresis/s2_search.json`
- Modify: `plugins/graphe/skills/paper-review/references/retrieval.md` (OpenAlex and S2 recipes call the script), `tests/conftest.py` (add `SCHOLARLY_SCRIPT`)
- Test: `tests/test_scholarly.py`

**Interfaces:**
- Produces (module `scholarly`, loaded by path):
  - `reconstruct_abstract(index: dict[str, list[int]] | None) -> str`
  - `openalex_search(query: str, *, limit: int = 8, semantic: bool = False, api_key: str | None = None, mailto: str | None = None, fetch=_get) -> list[dict]`
  - `s2_search(query: str, *, api_key: str, limit: int = 8, fetch=_get) -> list[dict]`
  - `arxiv_search(query: str, *, limit: int = 8, fetch=_get, throttle: Path | None = DEFAULT_THROTTLE) -> list[dict]`
  - `openalex_work(work_id: str, *, api_key: str | None = None, fetch=_get) -> dict`
  - Every search returns dicts with keys `title, url, source, date, text, evidence_url, doi`.
  - `fetch(url: str, headers: dict[str, str]) -> bytes` is the injectable HTTP function; `_get` is the real one.
  - CLI: `scholarly.py {openalex,s2,arxiv} QUERY [--limit N] [--semantic]` prints one JSON object per line.

- [ ] **Step 1: Record fixtures**

Run these once and save the bodies (trim to 2 results each, keep the structure):
```bash
mkdir -p tests/fixtures/heuresis
curl -s "https://api.openalex.org/works?filter=title_and_abstract.search:federated%20agents%20attribution&per-page=2&select=id,doi,title,publication_year,abstract_inverted_index,primary_location" > tests/fixtures/heuresis/openalex_works.json
curl -s "https://export.arxiv.org/api/query?search_query=all:%22federated%20learning%22&max_results=2" > tests/fixtures/heuresis/arxiv_query.xml
```
For S2, write the fixture by hand in the documented shape (the docs page could not be fetched, and keyless calls return 429):
```json
{"total": 1, "offset": 0, "data": [{"paperId": "abc123", "title": "Federated Agents for Source Attribution", "year": 2025, "abstract": "We study attribution of contributions in federated agent systems.", "url": "https://www.semanticscholar.org/paper/abc123", "externalIds": {"DOI": "10.1234/fa.2025"}}]}
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_scholarly.py
"""Shared paper retrieval: OpenAlex, Semantic Scholar, arXiv."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import ROOT, SCHOLARLY_SCRIPT, _load

FIX = ROOT / "tests" / "fixtures" / "heuresis"
s = _load("scholarly", SCHOLARLY_SCRIPT)


def fake(body: bytes, seen: list):
    def fetch(url, headers):
        seen.append((url, headers))
        return body

    return fetch


def test_reconstruct_abstract_orders_words_by_position():
    assert s.reconstruct_abstract({"world": [1], "hello": [0], "again": [2]}) == "hello world again"
    assert s.reconstruct_abstract(None) == ""


def test_openalex_search_uses_title_and_abstract_filter_and_key():
    seen: list = []
    body = (FIX / "openalex_works.json").read_bytes()
    out = s.openalex_search("federated agents", api_key="K", fetch=fake(body, seen))
    url, _ = seen[0]
    assert "filter=title_and_abstract.search:federated%20agents" in url
    assert "api_key=K" in url
    assert out and set(out[0]) == {"title", "url", "source", "date", "text", "evidence_url", "doi"}
    assert out[0]["source"] == "openalex"
    assert out[0]["evidence_url"].startswith("https://api.openalex.org/works/")


def test_openalex_semantic_mode_uses_search_semantic():
    seen: list = []
    s.openalex_search("q", semantic=True, fetch=fake(b'{"results": []}', seen))
    assert "search.semantic=q" in seen[0][0]


def test_s2_search_sends_key_header():
    seen: list = []
    body = (FIX / "s2_search.json").read_bytes()
    out = s.s2_search("federated agents", api_key="S", fetch=fake(body, seen))
    assert seen[0][1]["x-api-key"] == "S"
    assert out[0]["doi"] == "10.1234/fa.2025"
    assert out[0]["source"] == "semantic_scholar"


def test_arxiv_search_parses_atom(tmp_path: Path):
    seen: list = []
    body = (FIX / "arxiv_query.xml").read_bytes()
    out = s.arxiv_search("federated learning", fetch=fake(body, seen), throttle=tmp_path / "t")
    assert seen[0][0].startswith("https://export.arxiv.org/api/query?search_query=all:")
    assert out and out[0]["source"] == "arxiv"
    assert out[0]["evidence_url"].startswith("https://export.arxiv.org/api/query?id_list=")


def test_arxiv_throttle_waits_three_seconds(tmp_path: Path, monkeypatch):
    slept: list[float] = []
    clock = iter([100.0, 100.5])
    monkeypatch.setattr(s.time, "time", lambda: next(clock))
    monkeypatch.setattr(s.time, "sleep", slept.append)
    stamp = tmp_path / "t"
    stamp.write_text("99.0")
    s._throttle(stamp)
    assert slept == [pytest.approx(1.5)]


def test_malformed_json_raises_scholarly_error():
    with pytest.raises(s.ScholarlyError):
        s.openalex_search("q", fetch=fake(b"<html>", []))


def test_cli_prints_json_lines(capsys, monkeypatch):
    monkeypatch.setattr(s, "_get", lambda url, headers: (FIX / "openalex_works.json").read_bytes())
    assert s.main(["openalex", "federated agents", "--limit", "2"]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert all(json.loads(line)["source"] == "openalex" for line in lines)
```

Add to `tests/conftest.py` after `DOCTOR_LIB`:
```python
SCHOLARLY_SCRIPT = ROOT / "plugins" / "techne" / "_shared" / "scholarly.py"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_scholarly.py -v`
Expected: FAIL (`scholarly.py` not found).

- [ ] **Step 4: Implement `plugins/techne/_shared/scholarly.py`**

```python
#!/usr/bin/env python3
"""Paper search over OpenAlex, Semantic Scholar and arXiv, shared by graphe:paper-review and
heuresis. Standard library only, Python 3.11 or newer.

Usage: scholarly.py {openalex,s2,arxiv} QUERY [--limit N] [--semantic]
Keys: OPENALEX_API_KEY (optional, raises the daily budget), S2_API_KEY (required for s2).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path

USER_AGENT = "techne-scholarly (https://github.com/ajbarea/techne)"
TIMEOUT = 25
# arXiv's terms: no more than one request every three seconds, across all of a user's machines.
ARXIV_INTERVAL = 3.0
DEFAULT_THROTTLE = Path(tempfile.gettempdir()) / "techne-scholarly-arxiv"
ATOM = "{http://www.w3.org/2005/Atom}"
OPENALEX_SELECT = "id,doi,title,publication_year,abstract_inverted_index,primary_location"

Fetch = Callable[[str, dict[str, str]], bytes]


class ScholarlyError(Exception):
    """A source answered with something other than a usable result."""


def _get(url: str, headers: dict[str, str]) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **headers})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        raise ScholarlyError(f"http {exc.code} from {urllib.parse.urlsplit(url).netloc}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ScholarlyError(f"unreachable: {urllib.parse.urlsplit(url).netloc}") from exc


def _json(body: bytes) -> dict:
    try:
        data = json.loads(body)
    except ValueError as exc:
        raise ScholarlyError("response was not JSON") from exc
    if not isinstance(data, dict):
        raise ScholarlyError("response JSON was not an object")
    return data


def reconstruct_abstract(index: dict[str, list[int]] | None) -> str:
    if not index:
        return ""
    words = sorted((pos, word) for word, positions in index.items() for pos in positions)
    return " ".join(word for _, word in words)


def _record(title, url, source, date, text, evidence_url, doi) -> dict:
    return {
        "title": (title or "").strip(),
        "url": url or "",
        "source": source,
        "date": str(date or ""),
        "text": (text or "").strip(),
        "evidence_url": evidence_url or "",
        "doi": (doi or "").removeprefix("https://doi.org/"),
    }


def openalex_search(
    query: str,
    *,
    limit: int = 8,
    semantic: bool = False,
    api_key: str | None = None,
    mailto: str | None = None,
    fetch: Fetch = _get,
) -> list[dict]:
    params = {"per-page": str(limit), "select": OPENALEX_SELECT}
    if semantic:
        params["search.semantic"] = query
    else:
        # title_and_abstract.search ANDs its terms: keep queries to 3-4 high-signal words.
        params["filter"] = f"title_and_abstract.search:{query}"
        params["sort"] = "relevance_score:desc"
    if api_key:
        params["api_key"] = api_key
    if mailto:
        params["mailto"] = mailto
    url = "https://api.openalex.org/works?" + urllib.parse.urlencode(
        params, quote_via=urllib.parse.quote, safe=":,"
    )
    data = _json(fetch(url, {}))
    out = []
    for work in data.get("results", []):
        work_id = str(work.get("id", "")).rsplit("/", 1)[-1]
        location = work.get("primary_location") or {}
        link = location.get("landing_page_url") or work.get("doi") or work.get("id")
        out.append(
            _record(
                work.get("title"),
                link,
                "openalex",
                work.get("publication_year"),
                reconstruct_abstract(work.get("abstract_inverted_index")),
                f"https://api.openalex.org/works/{work_id}?select=title,abstract_inverted_index",
                work.get("doi"),
            )
        )
    return out


def openalex_work(work_id: str, *, api_key: str | None = None, fetch: Fetch = _get) -> dict:
    params = {"select": "title,abstract_inverted_index"}
    if api_key:
        params["api_key"] = api_key
    url = f"https://api.openalex.org/works/{work_id}?" + urllib.parse.urlencode(params)
    return _json(fetch(url, {}))


def s2_search(query: str, *, api_key: str, limit: int = 8, fetch: Fetch = _get) -> list[dict]:
    params = {"query": query, "limit": str(limit), "fields": "title,year,abstract,url,externalIds"}
    url = "https://api.semanticscholar.org/graph/v1/paper/search?" + urllib.parse.urlencode(params)
    data = _json(fetch(url, {"x-api-key": api_key}))
    out = []
    for paper in data.get("data", []):
        pid = paper.get("paperId", "")
        out.append(
            _record(
                paper.get("title"),
                paper.get("url") or f"https://www.semanticscholar.org/paper/{pid}",
                "semantic_scholar",
                paper.get("year"),
                paper.get("abstract"),
                f"https://api.semanticscholar.org/graph/v1/paper/{pid}?fields=title,abstract",
                (paper.get("externalIds") or {}).get("DOI"),
            )
        )
    return out


def _throttle(stamp: Path) -> None:
    try:
        last = float(stamp.read_text())
    except (OSError, ValueError):
        last = 0.0
    wait = ARXIV_INTERVAL - (time.time() - last)
    if wait > 0:
        time.sleep(wait)
    stamp.write_text(str(time.time()))


def arxiv_search(
    query: str, *, limit: int = 8, fetch: Fetch = _get, throttle: Path | None = DEFAULT_THROTTLE
) -> list[dict]:
    if throttle is not None:
        _throttle(throttle)
    terms = urllib.parse.quote(f'"{query}"')
    url = f"https://export.arxiv.org/api/query?search_query=all:{terms}&max_results={limit}"
    try:
        root = ET.fromstring(fetch(url, {}))
    except ET.ParseError as exc:
        raise ScholarlyError("arXiv response was not Atom XML") from exc
    out = []
    for entry in root.findall(f"{ATOM}entry"):
        link = entry.findtext(f"{ATOM}id", "")
        arxiv_id = link.rsplit("/abs/", 1)[-1]
        out.append(
            _record(
                " ".join(entry.findtext(f"{ATOM}title", "").split()),
                link,
                "arxiv",
                entry.findtext(f"{ATOM}published", "")[:10],
                " ".join(entry.findtext(f"{ATOM}summary", "").split()),
                f"https://export.arxiv.org/api/query?id_list={arxiv_id}",
                None,
            )
        )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scholarly.py")
    parser.add_argument("source", choices=["openalex", "s2", "arxiv"])
    parser.add_argument("query")
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--semantic", action="store_true", help="OpenAlex semantic search")
    args = parser.parse_args(argv)
    try:
        if args.source == "openalex":
            records = openalex_search(
                args.query,
                limit=args.limit,
                semantic=args.semantic,
                api_key=os.environ.get("OPENALEX_API_KEY"),
                mailto=os.environ.get("OPENALEX_MAILTO"),
                fetch=_get,
            )
        elif args.source == "s2":
            key = os.environ.get("S2_API_KEY")
            if not key:
                print("S2_API_KEY is not set; keyless Semantic Scholar returns 429", file=sys.stderr)
                return 2
            records = s2_search(args.query, api_key=key, limit=args.limit, fetch=_get)
        else:
            records = arxiv_search(args.query, limit=args.limit, fetch=_get)
    except ScholarlyError as exc:
        print(f"{args.source}: {exc}", file=sys.stderr)
        return 1
    for record in records:
        print(json.dumps(record, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Note the CLI passes `fetch=_get` explicitly so the CLI test's monkeypatch of `s._get` takes effect (a default argument binds at definition time).

- [ ] **Step 5: Copy, run tests and the guard**

```bash
cp plugins/techne/_shared/scholarly.py plugins/graphe/_shared/scholarly.py
mkdir -p plugins/heuresis/_shared && cp plugins/techne/_shared/scholarly.py plugins/heuresis/_shared/scholarly.py
uv run pytest tests/test_scholarly.py -v && make guards
```
Expected: PASS; `make guards` prints its OK lines.

- [ ] **Step 6: Point paper-review's recipes at the script**

In `plugins/graphe/skills/paper-review/references/retrieval.md`, replace the OpenAlex `bash` block with:
```bash
uv run --no-project --quiet python ${CLAUDE_PLUGIN_ROOT}/_shared/scholarly.py openalex 'federated learning Byzantine robust' --limit 8
```
and its explanation with: "Each line is one JSON record: `title`, `url`, `date`, `text` (the abstract), `doi`. Quote snippets from `text`. Set `OPENALEX_MAILTO` to identify yourself; set `OPENALEX_API_KEY` for a larger daily budget." Replace the S2 block with:
```bash
[ -n "$S2_API_KEY" ] && uv run --no-project --quiet python ${CLAUDE_PLUGIN_ROOT}/_shared/scholarly.py s2 'byzantine robust federated learning' --limit 5
```
Keep the query-construction guidance (3-4 terms, 2-3 phrasings, dedupe on DOI) unchanged.

Run: `bash scripts/check_plugin_refs.sh`
Expected: `OK: every ${CLAUDE_PLUGIN_ROOT} path resolves inside its plugin`

- [ ] **Step 7: Commit**

```bash
git add plugins/techne/_shared/scholarly.py plugins/graphe/_shared/scholarly.py plugins/heuresis/_shared/scholarly.py plugins/graphe/skills/paper-review/references/retrieval.md tests/test_scholarly.py tests/conftest.py tests/fixtures/heuresis
git commit -m "feat(shared): add scholarly.py paper search for paper-review and heuresis"
```

---

### Task 3: Data model and idea store

**Files:**
- Create: `plugins/heuresis/heuresis/model.py`, `plugins/heuresis/heuresis/store.py`
- Test: `tests/test_heuresis_store.py`

**Interfaces:**
- Produces:
  - `model.STATES, TYPES, CAPTURED_VIA, SECTIONS, KINDS, PAPER_SOURCES: tuple[str, ...]`
  - `model.Idea`, `model.Record`, `model.Coverage`, `model.Verdict` dataclasses (fields below)
  - `store.StoreError(Exception)`
  - `store.slugify(text: str) -> str`
  - `store.new_id(day: datetime.date, title: str, taken: Iterable[str]) -> str`
  - `store.title_from(text: str) -> str`
  - `store.render(idea: Idea) -> str`, `store.parse(text: str) -> Idea`
  - `store.validate(idea: Idea, stem: str | None = None) -> list[str]`
  - `store.load(path: Path) -> Idea`, `store.save(root: Path, idea: Idea) -> Path`, `store.load_all(root: Path) -> list[tuple[Path, Idea | None, str]]` (third item is an error message when parsing failed)
  - `store.idea_path(root: Path, idea_id: str) -> Path` (= `root / "ideas" / f"{idea_id}.md"`)
  - `store.render_verdict(v: Verdict) -> str`, `store.add_verdict(idea: Idea, v: Verdict) -> None`
  - `store.VERDICT_HEADING: re.Pattern` matching `### YYYY-MM-DD · origin · state`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_heuresis_store.py
"""Idea files: ids, round-trips, validation, verdict log."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from heuresis import store
from heuresis.model import Coverage, Idea, Verdict

DAY = dt.date(2026, 10, 15)


def idea(**kw) -> Idea:
    base = dict(
        id="2026-10-15-idea-triage-tool",
        title="Idea triage tool",
        captured="2026-10-15T14:02:00-04:00",
        captured_via="terminal",
        sections={"Idea": "An idea triage tool."},
    )
    base.update(kw)
    return Idea(**base)


def test_slugify_keeps_six_words_and_ascii():
    assert store.slugify("A tool: that triages ideas, fast & well!") == "a-tool-that-triages-ideas-fast"
    assert store.slugify("¿?") == "idea"


def test_new_id_appends_a_counter_on_collision():
    taken = {"2026-10-15-idea-triage-tool", "2026-10-15-idea-triage-tool-2"}
    assert store.new_id(DAY, "Idea triage tool", taken) == "2026-10-15-idea-triage-tool-3"


def test_title_from_takes_first_line_and_caps_length():
    assert store.title_from("  First line here\nsecond") == "First line here"
    assert len(store.title_from("x" * 200)) == 80


HOSTILE = '---\nkey: "value"\n## Restated\n- emoji 🚀 and 漢字\n```\ncode\n```'


def test_round_trip_preserves_hostile_idea_text_and_title():
    original = idea(title='Title: with "quotes" #1', sections={"Idea": HOSTILE})
    back = store.parse(store.render(original))
    assert back.title == original.title
    assert back.sections["Idea"] == HOSTILE
    assert "Restated" not in back.sections


def test_parse_coerces_unquoted_yaml_dates_to_strings():
    text = store.render(idea(state="later", revisit="2027-01-15"))
    text = text.replace("'2027-01-15'", "2027-01-15").replace(
        "'2026-10-15T14:02:00-04:00'", "2026-10-15T14:02:00-04:00"
    )
    back = store.parse(text)
    assert back.revisit == "2027-01-15"
    assert back.captured.startswith("2026-10-15T14:02:00")


def test_parse_rejects_missing_front_matter():
    with pytest.raises(store.StoreError):
        store.parse("# no front matter\n")


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"state": "maybe"}, "state"),
        ({"captured_via": "fax"}, "captured_via"),
        ({"state": "do"}, "type"),
        ({"state": "merged"}, "duplicate_of"),
        ({"state": "later"}, "revisit"),
        ({"state": "later", "revisit": "soon"}, "revisit"),
        ({"type": "gadget"}, "type"),
    ],
)
def test_validate_reports_each_rule(changes, message):
    errors = store.validate(idea(**changes))
    assert any(message in e for e in errors), errors


def test_validate_checks_id_matches_filename():
    assert store.validate(idea(), stem="other") == ["id 2026-10-15-idea-triage-tool does not match file name other"]


def test_save_and_load_all_skip_nothing_and_report_bad_files(tmp_path: Path):
    good = idea()
    store.save(tmp_path, good)
    (tmp_path / "ideas" / "broken.md").write_text("not an idea")
    rows = store.load_all(tmp_path)
    assert [(p.name, i is not None) for p, i, _ in rows] == [
        ("2026-10-15-idea-triage-tool.md", True),
        ("broken.md", False),
    ]


def test_add_verdict_prepends_newest_first_and_sets_fields():
    target = idea()
    first = Verdict(date="2026-10-15", origin="triage", state="later", reason="r1", revisit="2027-01-15")
    second = Verdict(
        date="2026-10-20", origin="override", state="do", reason="r2", type="tool", project="techne",
        coverage=[Coverage("openalex", "ok", 3, 8), Coverage("lens", "skipped", note="no token")],
        dropped=["https://x.example (quote not found)"],
    )
    store.add_verdict(target, first)
    store.add_verdict(target, second)
    log = target.sections["Verdict log"]
    assert log.index("2026-10-20 · override · do") < log.index("2026-10-15 · triage · later")
    assert "openalex: ok, 3 queries, 8 hits" in log
    assert "quote not found" in log
    assert "**Patents:** partial" in log
    assert (target.state, target.type, target.project) == ("do", "tool", "techne")
    assert [m.group(3) for m in store.VERDICT_HEADING.finditer(log)] == ["do", "later"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_heuresis_store.py -v`
Expected: FAIL (`ImportError`).

- [ ] **Step 3: Implement `model.py`**

```python
"""Data shapes shared by the store, the sources and the verdict rules."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

STATES = ("inbox", "trash", "later", "do", "building", "shipped", "merged")
TYPES = ("product", "tool", "research", "improve")
CAPTURED_VIA = ("terminal", "phone", "form", "import")
SECTIONS = (
    "Idea",
    "Restated",
    "Closest work",
    "Fit with your work",
    "Product evidence",
    "Verdict log",
)
KINDS = ("paper", "patent", "product", "repo", "web", "idea", "context")
PAPER_SOURCES = ("openalex", "semantic_scholar", "arxiv")
PATENT_SOURCES = ("lens", "epo")
FACETS = ("domain", "purpose", "mechanism", "evaluation")


@dataclass
class Idea:
    id: str
    title: str
    captured: str
    captured_via: str
    state: str = "inbox"
    type: str | None = None
    project: str | None = None
    duplicate_of: str | None = None
    revisit: str | None = None
    revisit_on: list[str] = field(default_factory=list)
    related: list[str] = field(default_factory=list)
    sections: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Record:
    title: str
    url: str
    source: str
    kind: str
    text: str = ""
    date: str = ""
    doi: str = ""
    evidence_url: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Record:
        known = {k: data[k] for k in cls.__dataclass_fields__ if k in data and data[k] is not None}
        return cls(**{k: str(v) for k, v in known.items()})


@dataclass(frozen=True)
class Coverage:
    source: str
    status: str  # ok | empty | failed | skipped
    queries: int = 0
    hits: int = 0
    note: str = ""

    def line(self) -> str:
        text = f"{self.source}: {self.status}, {self.queries} queries, {self.hits} hits"
        return f"{text} ({self.note})" if self.note else text

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Coverage:
        return cls(
            source=str(data["source"]),
            status=str(data["status"]),
            queries=int(data.get("queries", 0)),
            hits=int(data.get("hits", 0)),
            note=str(data.get("note", "")),
        )


@dataclass
class Verdict:
    date: str
    origin: str  # triage | override
    state: str
    reason: str
    type: str | None = None
    project: str | None = None
    next_step: str = ""
    duplicate_of: str | None = None
    revisit: str | None = None
    coverage: list[Coverage] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
```

- [ ] **Step 4: Implement `store.py`**

```python
"""Read, write and validate idea files: YAML front matter plus fixed Markdown sections."""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Iterable
from pathlib import Path

import yaml

from heuresis.model import CAPTURED_VIA, PATENT_SOURCES, SECTIONS, STATES, TYPES, Idea, Verdict

FRONT_KEYS = (
    "id", "title", "captured", "captured_via", "state", "type", "project",
    "duplicate_of", "revisit", "revisit_on", "related",
)
REQUIRED = ("id", "title", "captured", "captured_via")
TITLE_MAX = 80
# Sections split only on the known headings, so a "## " line inside the idea text stays text.
_SECTION = re.compile(r"^## (" + "|".join(re.escape(s) for s in SECTIONS) + r")$", re.MULTILINE)
VERDICT_HEADING = re.compile(r"^### (\d{4}-\d{2}-\d{2}) · (triage|override) · (\w+)$", re.MULTILINE)
NEEDS_TYPE = ("do", "building", "shipped")
# The idea text is AJ's, verbatim, so it may hold any heading; markers fence it off from the
# section split. GitHub hides HTML comments when rendering.
IDEA_START, IDEA_END = "<!-- idea:start -->", "<!-- idea:end -->"


class StoreError(Exception):
    """An idea file that cannot be read."""


def slugify(text: str) -> str:
    words = re.findall(r"[a-z0-9]+", text.lower())[:6]
    return "-".join(words)[:60].strip("-") or "idea"


def new_id(day: dt.date, title: str, taken: Iterable[str]) -> str:
    base = f"{day.isoformat()}-{slugify(title)}"
    used = set(taken)
    candidate, n = base, 2
    while candidate in used:
        candidate, n = f"{base}-{n}", n + 1
    return candidate


def title_from(text: str) -> str:
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    return first[:TITLE_MAX]


def idea_path(root: Path, idea_id: str) -> Path:
    return root / "ideas" / f"{idea_id}.md"


def render(idea: Idea) -> str:
    front = {key: getattr(idea, key) for key in FRONT_KEYS}
    head = yaml.safe_dump(front, sort_keys=False, allow_unicode=True, width=1000)
    parts = [f"---\n{head}---\n\n# {idea.title}\n"]
    for name in SECTIONS:
        body = idea.sections.get(name, "").strip("\n")
        if name == "Idea":
            parts.append(f"\n## Idea\n\n{IDEA_START}\n{body}\n{IDEA_END}\n")
        elif body:
            parts.append(f"\n## {name}\n\n{body}\n")
    return "".join(parts)


def _text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, dt.datetime | dt.date):
        return value.isoformat()
    return str(value)


def parse(text: str) -> Idea:
    if not text.startswith("---\n"):
        raise StoreError("no front matter")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise StoreError("front matter is not closed")
    try:
        front = yaml.safe_load(text[4:end]) or {}
    except yaml.YAMLError as exc:
        raise StoreError(f"front matter is not valid YAML: {exc}") from exc
    if not isinstance(front, dict):
        raise StoreError("front matter is not a mapping")
    missing = [key for key in REQUIRED if not front.get(key)]
    if missing:
        raise StoreError("front matter lacks " + ", ".join(missing))
    body = text[end + 5 :]
    sections = {}
    start, stop = body.find(IDEA_START), body.find(IDEA_END)
    if 0 <= start < stop:
        sections["Idea"] = body[start + len(IDEA_START) : stop].strip("\n")
        body = body[:start] + body[stop + len(IDEA_END) :]
    matches = list(_SECTION.finditer(body))
    for i, match in enumerate(matches):
        stop = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        if match.group(1) != "Idea" or "Idea" not in sections:
            sections[match.group(1)] = body[match.end() : stop].strip("\n")
    return Idea(
        id=str(front["id"]),
        title=str(front["title"]),
        captured=_text(front["captured"]) or "",
        captured_via=str(front["captured_via"]),
        state=str(front.get("state") or "inbox"),
        type=_text(front.get("type")),
        project=_text(front.get("project")),
        duplicate_of=_text(front.get("duplicate_of")),
        revisit=_text(front.get("revisit")),
        revisit_on=[str(v) for v in front.get("revisit_on") or []],
        related=[str(v) for v in front.get("related") or []],
        sections=sections,
    )


def validate(idea: Idea, stem: str | None = None) -> list[str]:
    errors = []
    if stem is not None and stem != idea.id:
        errors.append(f"id {idea.id} does not match file name {stem}")
    if idea.state not in STATES:
        errors.append(f"state {idea.state!r} is not one of {', '.join(STATES)}")
    if idea.captured_via not in CAPTURED_VIA:
        errors.append(f"captured_via {idea.captured_via!r} is not one of {', '.join(CAPTURED_VIA)}")
    if idea.type is not None and idea.type not in TYPES:
        errors.append(f"type {idea.type!r} is not one of {', '.join(TYPES)}")
    if idea.state in NEEDS_TYPE and idea.type is None:
        errors.append(f"state {idea.state} needs a type")
    if idea.state == "merged" and not idea.duplicate_of:
        errors.append("state merged needs duplicate_of")
    if idea.state == "later" and not idea.revisit:
        errors.append("state later needs a revisit date")
    if idea.revisit:
        try:
            dt.date.fromisoformat(idea.revisit)
        except ValueError:
            errors.append(f"revisit {idea.revisit!r} is not a YYYY-MM-DD date")
    return errors


def load(path: Path) -> Idea:
    return parse(path.read_text(encoding="utf-8"))


def save(root: Path, idea: Idea) -> Path:
    path = idea_path(root, idea.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(idea), encoding="utf-8")
    return path


def load_all(root: Path) -> list[tuple[Path, Idea | None, str]]:
    rows = []
    for path in sorted((root / "ideas").glob("*.md")):
        try:
            rows.append((path, load(path), ""))
        except StoreError as exc:
            rows.append((path, None, str(exc)))
    return rows


def render_verdict(v: Verdict) -> str:
    lines = [f"### {v.date} · {v.origin} · {v.state}", ""]
    if v.type or v.project:
        lines.append(f"- **Type:** {v.type or 'none'}. **Project:** {v.project or 'none'}.")
    lines.append(f"- **Reason:** {v.reason}")
    if v.next_step:
        lines.append(f"- **Next step:** {v.next_step}")
    if v.duplicate_of:
        lines.append(f"- **Duplicate of:** {v.duplicate_of}")
    if v.revisit:
        lines.append(f"- **Revisit:** {v.revisit}")
    if v.coverage:
        lines.append("- **Coverage:** " + "; ".join(c.line() for c in v.coverage))
    if any(c.source in PATENT_SOURCES for c in v.coverage):
        lines.append("- **Patents:** partial; only what Lens and EPO index was searched.")
    if v.dropped:
        lines.append("- **Dropped:** " + "; ".join(v.dropped))
    return "\n".join(lines)


def add_verdict(idea: Idea, v: Verdict) -> None:
    previous = idea.sections.get("Verdict log", "").strip("\n")
    entry = render_verdict(v)
    idea.sections["Verdict log"] = f"{entry}\n\n{previous}" if previous else entry
    idea.state = v.state
    idea.type = v.type or idea.type
    idea.project = v.project or idea.project
    idea.duplicate_of = v.duplicate_of
    idea.revisit = v.revisit if v.state == "later" else None
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_heuresis_store.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add plugins/heuresis/heuresis/model.py plugins/heuresis/heuresis/store.py tests/test_heuresis_store.py
git commit -m "feat(heuresis): add the idea model and markdown store"
```

---

### Task 4: Verdict rules

**Files:**
- Create: `plugins/heuresis/heuresis/rules.py`
- Test: `tests/test_heuresis_rules.py`

**Interfaces:**
- Consumes: `model.Verdict, Coverage, FACETS, PAPER_SOURCES`
- Produces:
  - `rules.REVISIT_AFTER_INSUFFICIENT: datetime.timedelta`
  - `rules.Closest` = `dict` with keys `url`, `differs` (dict of FACETS to str)
  - `rules.enforce(v: Verdict, *, closest: dict | None, closest_verified: bool, known_ids: set[str], today: datetime.date) -> Verdict` returns the verdict to record (possibly demoted); raises `ValueError` for a `merged` verdict without a known `duplicate_of`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_heuresis_rules.py
"""The verdict rules the judge cannot talk its way past."""

from __future__ import annotations

import datetime as dt

import pytest
from heuresis import rules
from heuresis.model import Coverage, Verdict

TODAY = dt.date(2026, 10, 15)
FULL = {"domain": "d", "purpose": "p", "mechanism": "m", "evaluation": "e"}
OK_PAPERS = [Coverage("openalex", "ok", 3, 8), Coverage("lens", "skipped", note="no LENS_API_TOKEN")]


def do(**kw) -> Verdict:
    base = dict(date="2026-10-15", origin="triage", state="do", reason="new", type="tool", coverage=OK_PAPERS)
    base.update(kw)
    return Verdict(**base)


def enforce(v, closest=None, verified=True, known=frozenset()):
    return rules.enforce(v, closest=closest, closest_verified=verified, known_ids=set(known), today=TODAY)


def test_do_with_verified_full_rival_and_paper_results_stands():
    out = enforce(do(), closest={"url": "u", "differs": FULL})
    assert out.state == "do"


@pytest.mark.parametrize(
    ("verdict", "closest", "verified", "problem"),
    [
        (do(), None, True, "no closest rival"),
        (do(), {"url": "u", "differs": FULL}, False, "closest rival could not be verified"),
        (do(), {"url": "u", "differs": {**FULL, "evaluation": ""}}, True, "evaluation"),
        (do(coverage=[Coverage("openalex", "failed", 3, 0, "http 503")]), {"url": "u", "differs": FULL}, True, "no paper source"),
        (do(type=None), {"url": "u", "differs": FULL}, True, "type"),
    ],
)
def test_do_without_evidence_is_demoted_to_later(verdict, closest, verified, problem):
    out = enforce(verdict, closest, verified)
    assert out.state == "later"
    assert out.reason.startswith("insufficient evidence:")
    assert problem in out.reason
    assert out.revisit == (TODAY + rules.REVISIT_AFTER_INSUFFICIENT).isoformat()
    assert out.type == verdict.type


def test_merged_needs_a_known_duplicate():
    with pytest.raises(ValueError, match="duplicate_of"):
        enforce(do(state="merged", duplicate_of="nope"))
    out = enforce(do(state="merged", duplicate_of="2026-10-01-x"), known={"2026-10-01-x"})
    assert out.state == "merged"


def test_later_without_revisit_gets_the_default():
    out = enforce(do(state="later"))
    assert out.revisit == (TODAY + rules.REVISIT_AFTER_INSUFFICIENT).isoformat()


def test_trash_passes_through():
    assert enforce(do(state="trash", type=None)).state == "trash"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_heuresis_rules.py -v`
Expected: FAIL (`ImportError`).

- [ ] **Step 3: Implement `rules.py`**

```python
"""Rules a verdict must meet before it is recorded. They run in code so no prompt can skip them."""

from __future__ import annotations

import dataclasses
import datetime as dt

from heuresis.model import FACETS, PAPER_SOURCES, Verdict

# An idea parked for thin evidence is searched again after a quarter, long enough for new
# preprints, launches and patents to appear, short enough that it is still remembered.
REVISIT_AFTER_INSUFFICIENT = dt.timedelta(days=90)


def _do_problems(v: Verdict, closest: dict | None, closest_verified: bool) -> list[str]:
    problems = []
    if v.type is None:
        problems.append("type missing")
    if closest is None:
        problems.append("no closest rival named")
    else:
        if not closest_verified:
            problems.append("closest rival could not be verified")
        differs = closest.get("differs") or {}
        empty = [facet for facet in FACETS if not str(differs.get(facet, "")).strip()]
        if empty:
            problems.append("closest rival lacks a comparison on " + ", ".join(empty))
    if not any(c.source in PAPER_SOURCES and c.status == "ok" for c in v.coverage):
        problems.append("no paper source returned results")
    return problems


def enforce(
    v: Verdict,
    *,
    closest: dict | None,
    closest_verified: bool,
    known_ids: set[str],
    today: dt.date,
) -> Verdict:
    revisit = (today + REVISIT_AFTER_INSUFFICIENT).isoformat()
    if v.state == "merged" and v.duplicate_of not in known_ids:
        raise ValueError(f"merged verdict names duplicate_of {v.duplicate_of!r}, not an idea here")
    if v.state == "do":
        problems = _do_problems(v, closest, closest_verified)
        if problems:
            reason = f"insufficient evidence: {'; '.join(problems)}. Judge proposed do: {v.reason}"
            return dataclasses.replace(v, state="later", reason=reason, revisit=revisit)
    if v.state == "later" and not v.revisit:
        return dataclasses.replace(v, revisit=revisit)
    return v
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_heuresis_rules.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add plugins/heuresis/heuresis/rules.py tests/test_heuresis_rules.py
git commit -m "feat(heuresis): enforce verdict evidence rules in code"
```

---

### Task 5: Board and log generation

**Files:**
- Create: `plugins/heuresis/heuresis/board.py`
- Test: `tests/test_heuresis_board.py`

**Interfaces:**
- Consumes: `store.load_all`, `store.validate`, `store.VERDICT_HEADING`
- Produces:
  - `board.render_board(rows: list[tuple[Path, Idea | None, str]], today: datetime.date) -> str`
  - `board.render_log(rows) -> str`
  - `board.write(root: Path, today: datetime.date) -> list[Path]` (writes `BOARD.md`, `LOG.md`, returns both paths)
  - `board.GENERATED = ("BOARD.md", "LOG.md")`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_heuresis_board.py
"""BOARD.md orders by what needs a decision; LOG.md lists every verdict, newest first."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from heuresis import board, store
from heuresis.model import Idea, Verdict

TODAY = dt.date(2026, 10, 15)


def make(root: Path, idea_id: str, **kw) -> Idea:
    i = Idea(id=idea_id, title=kw.pop("title", idea_id), captured="2026-10-01T00:00:00", captured_via="terminal", **kw)
    i.sections["Idea"] = "text"
    store.save(root, i)
    return i


def test_board_sections_in_decision_order(tmp_path: Path):
    make(tmp_path, "a-inbox")
    make(tmp_path, "b-due", state="later", revisit="2026-10-01")
    make(tmp_path, "c-later", state="later", revisit="2027-01-01")
    make(tmp_path, "d-do", state="do", type="tool", project="techne")
    make(tmp_path, "e-trash", state="trash")
    make(tmp_path, "f-merged", state="merged", duplicate_of="d-do")
    (tmp_path / "ideas" / "g-broken.md").write_text("junk")
    text = board.render_board(store.load_all(tmp_path), TODAY)
    order = ["## Needs triage", "## Due for revisit", "## Do", "## Later", "## Closed"]
    assert [text.index(h) for h in order] == sorted(text.index(h) for h in order)
    needs = text[text.index("## Needs triage") : text.index("## Due for revisit")]
    assert "a-inbox" in needs and "g-broken.md" in needs
    assert "b-due" in text[text.index("## Due for revisit") : text.index("## Do")]
    assert "### techne" in text and "d-do" in text
    assert "c-later" in text[text.index("## Later") : text.index("## Closed")]
    assert "Trash: 1" in text and "Merged: 1" in text


def test_board_flags_invalid_ideas_under_needs_triage(tmp_path: Path):
    make(tmp_path, "h-bad", state="do")  # do without a type
    text = board.render_board(store.load_all(tmp_path), TODAY)
    needs = text[text.index("## Needs triage") : text.index("## Due for revisit")]
    assert "h-bad" in needs and "needs a type" in needs


def test_log_lists_verdicts_newest_first(tmp_path: Path):
    a = make(tmp_path, "a")
    store.add_verdict(a, Verdict(date="2026-10-02", origin="triage", state="trash", reason="exists"))
    store.save(tmp_path, a)
    b = make(tmp_path, "b")
    store.add_verdict(b, Verdict(date="2026-10-05", origin="override", state="do", reason="mine", type="tool"))
    store.save(tmp_path, b)
    text = board.render_log(store.load_all(tmp_path))
    assert text.index("2026-10-05") < text.index("2026-10-02")
    assert "[b](ideas/b.md) · override · do" in text


def test_write_creates_both_files(tmp_path: Path):
    make(tmp_path, "a")
    paths = board.write(tmp_path, TODAY)
    assert [p.name for p in paths] == list(board.GENERATED)
    assert all(p.is_file() for p in paths)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_heuresis_board.py -v`
Expected: FAIL (`ImportError`).

- [ ] **Step 3: Implement `board.py`**

```python
"""Generate BOARD.md and LOG.md from the idea files. Never edit either by hand."""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from pathlib import Path

from heuresis import store
from heuresis.model import Idea

GENERATED = ("BOARD.md", "LOG.md")
HEADER = "<!-- Generated by heuresis from ideas/. Edits here are overwritten. -->\n"
Rows = list[tuple[Path, Idea | None, str]]


def _line(idea: Idea) -> str:
    bits = [b for b in (idea.type, idea.project) if b]
    tail = f" · {' · '.join(bits)}" if bits else ""
    return f"- [{idea.id}](ideas/{idea.id}.md): {idea.title}{tail}"


def render_board(rows: Rows, today: dt.date) -> str:
    needs, due, later, do, closed = [], [], [], defaultdict(list), defaultdict(int)
    for path, idea, error in rows:
        if idea is None:
            needs.append(f"- {path.name}: unreadable ({error})")
            continue
        problems = store.validate(idea, stem=path.stem)
        if problems:
            needs.append(f"{_line(idea)} · invalid: {'; '.join(problems)}")
        elif idea.state == "inbox":
            needs.append(_line(idea))
        elif idea.state == "later" and idea.revisit and idea.revisit <= today.isoformat():
            due.append(f"{_line(idea)} · revisit {idea.revisit}")
        elif idea.state == "later":
            later.append(f"{_line(idea)} · revisit {idea.revisit}")
        elif idea.state in ("do", "building"):
            label = "" if idea.state == "do" else " · building"
            do[idea.project or "no project"].append(_line(idea) + label)
        else:
            closed[idea.state] += 1
    out = [HEADER, "# Ideas\n", "## Needs triage\n", *(needs or ["Nothing waiting."]), ""]
    out += ["## Due for revisit\n", *(due or ["Nothing due."]), "", "## Do\n"]
    for project in sorted(do):
        out += [f"### {project}\n", *sorted(do[project]), ""]
    if not do:
        out += ["Nothing in progress.", ""]
    out += ["## Later\n", *(sorted(later) or ["Nothing parked."]), "", "## Closed\n"]
    counts = [f"{state.capitalize()}: {closed[state]}" for state in ("shipped", "trash", "merged")]
    out += [" · ".join(counts), ""]
    return "\n".join(out)


def render_log(rows: Rows) -> str:
    events = []
    for _, idea, _ in rows:
        if idea is None:
            continue
        for match in store.VERDICT_HEADING.finditer(idea.sections.get("Verdict log", "")):
            date, origin, state = match.groups()
            events.append((date, idea.id, f"- {date} · [{idea.id}](ideas/{idea.id}.md) · {origin} · {state}"))
    events.sort(key=lambda e: (e[0], e[1]), reverse=True)
    return "\n".join([HEADER, "# Log\n", *(e[2] for e in events)]) + "\n"


def write(root: Path, today: dt.date) -> list[Path]:
    rows = store.load_all(root)
    paths = [root / name for name in GENERATED]
    paths[0].write_text(render_board(rows, today), encoding="utf-8")
    paths[1].write_text(render_log(rows), encoding="utf-8")
    return paths
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_heuresis_board.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add plugins/heuresis/heuresis/board.py tests/test_heuresis_board.py
git commit -m "feat(heuresis): generate BOARD.md and LOG.md from idea files"
```

---

### Task 6: Projects, context sources and duplicate candidates

**Files:**
- Create: `plugins/heuresis/heuresis/context.py`, `plugins/heuresis/heuresis/similar.py`
- Test: `tests/test_heuresis_context.py`, `tests/test_heuresis_similar.py`

**Interfaces:**
- Produces:
  - `context.Project(name: str, kind: str, repo: str | None, status: str = "active")` dataclass; kinds `repo | plugin | paper | new`
  - `context.seed_projects(techne_toml: Path | None, repos_root: Path) -> list[Project]`
  - `context.write_projects(path: Path, projects: list[Project]) -> None`, `context.load_projects(path: Path) -> list[Project]`
  - `context.DEFAULT_SOURCES: list[dict]`; `context.write_context(path: Path) -> None`
  - `context.resolve_sources(context_toml: Path, projects: list[Project], repos_root: Path) -> list[dict]` returning `{"kind", "repo", "path"}` for files that exist, `path` absolute
  - `context.init_repo(root: Path, techne_toml: Path | None, repos_root: Path) -> None` (creates `ideas/`, `runs/`, `projects.toml`, `context.toml`, `README.md`, runs `board.write`, `git init` if not a repo)
  - `similar.similar(text: str, ideas: list[Idea], k: int = 5) -> list[tuple[str, float]]`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_heuresis_context.py
"""Projects seeded from techne.toml, the marketplace and paper dirs; context sources resolved."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from heuresis import context


def repos(tmp_path: Path) -> Path:
    root = tmp_path / "repos"
    for name in ("techne", "papers", "talks", "ariadne"):
        (root / name).mkdir(parents=True)
    (root / "techne" / ".claude-plugin").mkdir()
    (root / "techne" / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps({"plugins": [{"name": "techne"}, {"name": "graphe"}]})
    )
    (root / "papers" / "org-house-style").mkdir()
    (root / "papers" / "org-house-style" / "main.tex").write_text("")
    (root / "papers" / "references.bib").write_text("@article{x,}")
    (root / "talks" / "federated-agents").mkdir()
    (root / "talks" / "federated-agents" / "index.html").write_text("<html>")
    (root / "ariadne" / "ROADMAP.md").write_text("# r")
    return root


TOML = '[[sisters]]\nname = "ariadne"\nstatus = "active"\n[[sisters]]\nname = "techne"\nstatus = "active"\n[[sisters]]\nname = "kourai"\nstatus = "backburner"\n'


def test_seed_projects_names_each_kind_without_collisions(tmp_path: Path):
    root = repos(tmp_path)
    toml = tmp_path / "techne.toml"
    toml.write_text(TOML)
    names = {p.name: p for p in context.seed_projects(toml, root)}
    assert names["ariadne"].kind == "repo"
    assert names["kourai"].status == "backburner"
    assert names["plugin:graphe"].repo == "techne"
    assert "plugin:techne" in names and names["techne"].kind == "repo"
    assert names["paper:org-house-style"].repo == "papers"


def test_seed_projects_without_techne_toml_still_finds_plugins_and_papers(tmp_path: Path):
    names = {p.name for p in context.seed_projects(None, repos(tmp_path))}
    assert {"plugin:graphe", "paper:org-house-style"} <= names


def test_projects_round_trip(tmp_path: Path):
    projects = context.seed_projects(None, repos(tmp_path))
    path = tmp_path / "projects.toml"
    context.write_projects(path, projects)
    assert context.load_projects(path) == projects


def test_resolve_sources_expands_globs_and_star_repos(tmp_path: Path):
    root = repos(tmp_path)
    ctx = tmp_path / "context.toml"
    context.write_context(ctx)
    projects = [context.Project("ariadne", "repo", "ariadne")]
    found = {(s["kind"], Path(s["path"]).relative_to(root).as_posix()) for s in context.resolve_sources(ctx, projects, root)}
    assert ("bib", "papers/references.bib") in found
    assert ("deck", "talks/federated-agents/index.html") in found
    assert ("roadmap", "ariadne/ROADMAP.md") in found
    assert all(Path(s["path"]).is_absolute() for s in context.resolve_sources(ctx, projects, root))


def test_init_repo_creates_the_layout_and_a_git_repo(tmp_path: Path):
    root = repos(tmp_path)
    ideas = tmp_path / "ideas-repo"
    context.init_repo(ideas, None, root)
    for name in ("ideas", "runs", "projects.toml", "context.toml", "README.md", "BOARD.md", "LOG.md"):
        assert (ideas / name).exists(), name
    assert subprocess.run(["git", "-C", str(ideas), "rev-parse"], check=False).returncode == 0
    context.init_repo(ideas, None, root)  # a second run changes nothing and does not fail
```

```python
# tests/test_heuresis_similar.py
"""Duplicate candidates by word overlap."""

from __future__ import annotations

from heuresis.model import Idea
from heuresis.similar import similar


def idea(i, text):
    return Idea(id=i, title=text, captured="x", captured_via="terminal", sections={"Idea": text})


def test_similar_ranks_overlap_and_ignores_stopwords():
    ideas = [
        idea("a", "A tool that triages research ideas against prior work"),
        idea("b", "Travel planner that works offline"),
        idea("c", "The and of with for"),
    ]
    out = similar("triage my research ideas against prior art", ideas, k=2)
    assert out[0][0] == "a"
    assert all(score > 0 for _, score in out)
    assert "c" not in [i for i, _ in out]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_heuresis_context.py tests/test_heuresis_similar.py -v`
Expected: FAIL (`ImportError`).

- [ ] **Step 3: Implement `context.py`**

```python
"""Where AJ's projects and research sources live. Paths only; nothing is copied."""

from __future__ import annotations

import datetime as dt
import json
import subprocess
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path

from heuresis import board

DEFAULT_SOURCES = [
    {"kind": "bib", "repo": "papers", "path": "references.bib"},
    {"kind": "notes", "repo": "papers", "path": "related-work/intake.md"},
    {"kind": "lineage", "repo": "papers", "path": "LINEAGE.md"},
    {"kind": "deck", "repo": "talks", "path": "*/index.html"},
    {"kind": "marketplace", "repo": "techne", "path": ".claude-plugin/marketplace.json"},
    {"kind": "roadmap", "repo": "*", "path": "ROADMAP.md"},
    {"kind": "readme", "repo": "*", "path": "README.md"},
]
README = """# ideas

Every idea, one file each, under `ideas/`. `BOARD.md` and `LOG.md` are generated by heuresis;
edit the idea files, never those two. `runs/` holds each triage's search records.
"""


@dataclass
class Project:
    name: str
    kind: str
    repo: str | None
    status: str = "active"


def seed_projects(techne_toml: Path | None, repos_root: Path) -> list[Project]:
    projects: list[Project] = []
    if techne_toml and techne_toml.is_file():
        for sister in tomllib.loads(techne_toml.read_text()).get("sisters", []):
            name = sister["name"]
            projects.append(Project(name, "repo", name, sister.get("status", "active")))
    marketplace = repos_root / "techne" / ".claude-plugin" / "marketplace.json"
    if marketplace.is_file():
        for plugin in json.loads(marketplace.read_text()).get("plugins", []):
            projects.append(Project(f"plugin:{plugin['name']}", "plugin", "techne"))
    for tex in sorted((repos_root / "papers").glob("*/main.tex")):
        projects.append(Project(f"paper:{tex.parent.name}", "paper", "papers"))
    return projects


def write_projects(path: Path, projects: list[Project]) -> None:
    blocks = []
    for p in projects:
        fields = {k: v for k, v in asdict(p).items() if v is not None}
        body = "\n".join(f"{k} = {json.dumps(v)}" for k, v in fields.items())
        blocks.append(f"[[project]]\n{body}\n")
    path.write_text("\n".join(blocks), encoding="utf-8")


def load_projects(path: Path) -> list[Project]:
    rows = tomllib.loads(path.read_text()).get("project", [])
    return [Project(r["name"], r["kind"], r.get("repo"), r.get("status", "active")) for r in rows]


def write_context(path: Path) -> None:
    blocks = [
        "[[source]]\n" + "\n".join(f"{k} = {json.dumps(v)}" for k, v in s.items()) + "\n"
        for s in DEFAULT_SOURCES
    ]
    path.write_text("\n".join(blocks), encoding="utf-8")


def resolve_sources(context_toml: Path, projects: list[Project], repos_root: Path) -> list[dict]:
    sources = tomllib.loads(context_toml.read_text()).get("source", [])
    repo_names = sorted({p.repo for p in projects if p.kind == "repo" and p.repo})
    found = []
    for source in sources:
        repos = repo_names if source["repo"] == "*" else [source["repo"]]
        for repo in repos:
            for path in sorted((repos_root / repo).glob(source["path"])):
                if path.is_file():
                    found.append({"kind": source["kind"], "repo": repo, "path": str(path.resolve())})
    return found


def init_repo(root: Path, techne_toml: Path | None, repos_root: Path) -> None:
    (root / "ideas").mkdir(parents=True, exist_ok=True)
    (root / "runs").mkdir(exist_ok=True)
    for keep in ("ideas", "runs"):
        (root / keep / ".gitkeep").touch()
    if not (root / "projects.toml").exists():
        write_projects(root / "projects.toml", seed_projects(techne_toml, repos_root))
    if not (root / "context.toml").exists():
        write_context(root / "context.toml")
    if not (root / "README.md").exists():
        (root / "README.md").write_text(README, encoding="utf-8")
    board.write(root, dt.date.today())
    if subprocess.run(["git", "-C", str(root), "rev-parse"], capture_output=True).returncode:
        subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
```

- [ ] **Step 4: Implement `similar.py`**

```python
"""Earlier ideas that share words with a new one: candidates for the context scout to read."""

from __future__ import annotations

import re

from heuresis.model import Idea

STOPWORDS = frozenset(
    "the and for with that this from into over under about than then them they their there "
    "what when where which while would could should have has had are was were will can "
    "not but our you your its it's a an of to in on at by is be as or my me we i".split()
)


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2 and w not in STOPWORDS}


def similar(text: str, ideas: list[Idea], k: int = 5) -> list[tuple[str, float]]:
    target = _words(text)
    scored = []
    for idea in ideas:
        words = _words(idea.title + " " + idea.sections.get("Idea", ""))
        union = target | words
        if union:
            score = len(target & words) / len(union)
            if score > 0:
                scored.append((idea.id, round(score, 3)))
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:k]
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_heuresis_context.py tests/test_heuresis_similar.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add plugins/heuresis/heuresis/context.py plugins/heuresis/heuresis/similar.py tests/test_heuresis_context.py tests/test_heuresis_similar.py
git commit -m "feat(heuresis): seed projects, resolve context sources, find similar ideas"
```

---

### Task 7: HTTP helper, source protocol and paper sources

**Files:**
- Create: `plugins/heuresis/heuresis/sources/__init__.py`, `plugins/heuresis/heuresis/sources/http.py`, `plugins/heuresis/heuresis/sources/papers.py`
- Test: `tests/test_heuresis_sources.py`

**Interfaces:**
- Consumes: `_shared/scholarly.py` (loaded by path from `Path(__file__).resolve().parents[2] / "_shared" / "scholarly.py"`), `model.Record, Coverage`
- Produces:
  - `http.SourceError(Exception)`; `http.get(url: str, headers: dict | None = None) -> bytes`; `http.post_json(url: str, body: dict, headers: dict | None = None) -> bytes`; `http.USER_AGENT`; `http.MAX_BYTES = 2_000_000`; `http.TIMEOUT = 20`
  - `sources.Source` Protocol: `name: str`, `group: str`, `available(self) -> tuple[bool, str]`, `search(self, query: str, limit: int) -> list[Record]`, `evidence(self, record: Record) -> str | None`
  - `sources.REGISTRY: dict[str, list[Source]]` keyed by group `papers | patents | products`, filled by each module's `register()` call at import
  - `sources.run_queries(sources: list[Source], queries: list[str], limit: int) -> tuple[list[Record], list[Coverage]]`
  - `sources.by_name(name: str) -> Source | None`
  - `papers.OpenAlex`, `papers.SemanticScholar`, `papers.Arxiv` classes

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_heuresis_sources.py
"""Source protocol: failures become coverage lines, never crashes."""

from __future__ import annotations

from heuresis import sources
from heuresis.model import Record
from heuresis.sources import http, papers


class Fake:
    group = "papers"

    def __init__(self, name, results=None, error=None, available=(True, "")):
        self.name, self._results, self._error, self._available = name, results or [], error, available

    def available(self):
        return self._available

    def search(self, query, limit):
        if self._error:
            raise self._error
        return self._results[:limit]

    def evidence(self, record):
        return None


R = Record(title="T", url="https://a.example/1", source="openalex", kind="paper", text="abstract")


def test_run_queries_collects_records_and_coverage():
    ok = Fake("openalex", [R])
    empty = Fake("arxiv")
    broken = Fake("semantic_scholar", error=http.SourceError("http 429 from api.semanticscholar.org"))
    off = Fake("lens", available=(False, "no LENS_API_TOKEN"))
    records, coverage = sources.run_queries([ok, empty, broken, off], ["q1", "q2"], limit=5)
    assert records == [R, R]
    lines = {c.source: (c.status, c.queries, c.hits, c.note) for c in coverage}
    assert lines["openalex"] == ("ok", 2, 2, "")
    assert lines["arxiv"] == ("empty", 2, 0, "")
    assert lines["semantic_scholar"][0] == "failed" and "429" in lines["semantic_scholar"][3]
    assert lines["lens"] == ("skipped", 0, 0, "no LENS_API_TOKEN")


def test_unexpected_exception_is_a_failed_line_not_a_crash():
    weird = Fake("openalex", error=KeyError("results"))
    _, coverage = sources.run_queries([weird], ["q"], limit=5)
    assert coverage[0].status == "failed" and "KeyError" in coverage[0].note


def test_paper_sources_register_in_order():
    assert [s.name for s in sources.REGISTRY["papers"]] == ["openalex", "semantic_scholar", "arxiv"]


def test_semantic_scholar_unavailable_without_key(monkeypatch):
    monkeypatch.delenv("S2_API_KEY", raising=False)
    ok, why = papers.SemanticScholar().available()
    assert not ok and "S2_API_KEY" in why


def test_openalex_converts_records(monkeypatch):
    rows = [{"title": "T", "url": "https://doi.org/10.1/x", "source": "openalex", "date": "2025", "text": "abs", "evidence_url": "https://api.openalex.org/works/W1?select=title,abstract_inverted_index", "doi": "10.1/x"}]
    monkeypatch.setattr(papers.S, "openalex_search", lambda q, **kw: rows)
    out = papers.OpenAlex().search("q", 3)
    assert out[0].kind == "paper" and out[0].doi == "10.1/x"


def test_openalex_evidence_reconstructs_abstract(monkeypatch):
    monkeypatch.setattr(papers.S, "openalex_work", lambda wid, **kw: {"title": "T", "abstract_inverted_index": {"hello": [0], "world": [1]}})
    rec = Record(title="T", url="u", source="openalex", kind="paper", evidence_url="https://api.openalex.org/works/W1?select=x")
    assert papers.OpenAlex().evidence(rec) == "T hello world"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_heuresis_sources.py -v`
Expected: FAIL (`ImportError`).

- [ ] **Step 3: Implement `sources/http.py`**

```python
"""One HTTP helper for every source: identifying user agent, timeout, size cap, plain errors."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "heuresis (https://github.com/ajbarea/techne)"
TIMEOUT = 20
# Evidence pages and API answers above 2 MB are not read whole; the quote check needs text, not media.
MAX_BYTES = 2_000_000


class SourceError(Exception):
    """A source could not answer: unreachable, an HTTP error, or an unusable body."""


def _open(req: urllib.request.Request) -> bytes:
    host = urllib.parse.urlsplit(req.full_url).netloc
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.read(MAX_BYTES)
    except urllib.error.HTTPError as exc:
        raise SourceError(f"http {exc.code} from {host}") from exc
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        raise SourceError(f"unreachable: {host}") from exc


def get(url: str, headers: dict[str, str] | None = None) -> bytes:
    return _open(urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})}))


def post_json(url: str, body: dict, headers: dict[str, str] | None = None) -> bytes:
    data = json.dumps(body).encode()
    merged = {"User-Agent": USER_AGENT, "Content-Type": "application/json", **(headers or {})}
    return _open(urllib.request.Request(url, data=data, headers=merged, method="POST"))
```

- [ ] **Step 4: Implement `sources/__init__.py`**

```python
"""Source protocol and registry. A source that fails becomes a coverage line, never a crash."""

from __future__ import annotations

from typing import Protocol

from heuresis.model import Coverage, Record


class Source(Protocol):
    name: str
    group: str

    def available(self) -> tuple[bool, str]: ...

    def search(self, query: str, limit: int) -> list[Record]: ...

    def evidence(self, record: Record) -> str | None: ...


REGISTRY: dict[str, list[Source]] = {"papers": [], "patents": [], "products": []}


def register(source: Source) -> None:
    REGISTRY[source.group].append(source)


def by_name(name: str) -> Source | None:
    return next((s for group in REGISTRY.values() for s in group if s.name == name), None)


def run_queries(
    sources: list[Source], queries: list[str], limit: int
) -> tuple[list[Record], list[Coverage]]:
    records: list[Record] = []
    coverage: list[Coverage] = []
    for source in sources:
        ok, why = source.available()
        if not ok:
            coverage.append(Coverage(source.name, "skipped", note=why))
            continue
        hits, error = 0, ""
        for query in queries:
            try:
                found = source.search(query, limit)
            except Exception as exc:  # any adapter bug or API change is reported, not raised
                error = str(exc) if type(exc).__name__ in ("SourceError", "ScholarlyError") else f"{type(exc).__name__}: {exc}"
                break
            hits += len(found)
            records.extend(found)
        status = "failed" if error else ("ok" if hits else "empty")
        coverage.append(Coverage(source.name, status, len(queries), hits, error))
    return records, coverage


def _load_adapters() -> None:
    from heuresis.sources import papers, patents, products  # noqa: F401  # register on import


_load_adapters()
```

Note: `patents` and `products` modules are created in Tasks 8 and 9. Until then create each as a one-line placeholder module `"""Filled in by a later task."""` so the import succeeds, and replace it in its task.

Fix the `error` line to fit 100 columns:
```python
            except Exception as exc:  # any adapter bug or API change is reported, not raised
                known = type(exc).__name__ in ("SourceError", "ScholarlyError")
                error = str(exc) if known else f"{type(exc).__name__}: {exc}"
                break
```

- [ ] **Step 5: Implement `sources/papers.py`**

```python
"""Paper sources over the shared scholarly.py."""

from __future__ import annotations

import importlib.util
import os
import urllib.parse
from pathlib import Path

from heuresis.model import Record
from heuresis.sources import register

_SHARED = Path(__file__).resolve().parents[2] / "_shared" / "scholarly.py"
_spec = importlib.util.spec_from_file_location("scholarly", _SHARED)
assert _spec and _spec.loader
S = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(S)


def _records(rows: list[dict]) -> list[Record]:
    return [Record.from_dict({**row, "kind": "paper"}) for row in rows]


class OpenAlex:
    name, group = "openalex", "papers"

    def available(self) -> tuple[bool, str]:
        return True, ""

    def search(self, query: str, limit: int) -> list[Record]:
        return _records(
            S.openalex_search(
                query,
                limit=limit,
                api_key=os.environ.get("OPENALEX_API_KEY"),
                mailto=os.environ.get("OPENALEX_MAILTO"),
            )
        )

    def evidence(self, record: Record) -> str | None:
        path = urllib.parse.urlsplit(record.evidence_url).path
        work = S.openalex_work(path.rsplit("/", 1)[-1], api_key=os.environ.get("OPENALEX_API_KEY"))
        abstract = S.reconstruct_abstract(work.get("abstract_inverted_index"))
        return f"{work.get('title', '')} {abstract}".strip()


class SemanticScholar:
    name, group = "semantic_scholar", "papers"

    def available(self) -> tuple[bool, str]:
        if os.environ.get("S2_API_KEY"):
            return True, ""
        return False, "no S2_API_KEY (keyless requests return 429)"

    def search(self, query: str, limit: int) -> list[Record]:
        return _records(S.s2_search(query, api_key=os.environ["S2_API_KEY"], limit=limit))

    def evidence(self, record: Record) -> str | None:
        return None  # the evidence_url is a plain GET JSON endpoint; verify fetches it


class Arxiv:
    name, group = "arxiv", "papers"

    def available(self) -> tuple[bool, str]:
        return True, ""

    def search(self, query: str, limit: int) -> list[Record]:
        return _records(S.arxiv_search(query, limit=limit))

    def evidence(self, record: Record) -> str | None:
        return None  # Atom XML at evidence_url; verify extracts its text


for _source in (OpenAlex(), SemanticScholar(), Arxiv()):
    register(_source)
```

`S.s2_search` sends `x-api-key` only when passed through `fetch`'s headers, and verify fetches S2 evidence without the key; add the key there in Task 10 (`verify` passes `{"x-api-key": key}` for `api.semanticscholar.org` hosts).

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/test_heuresis_sources.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add plugins/heuresis/heuresis/sources tests/test_heuresis_sources.py
git commit -m "feat(heuresis): add the source protocol and paper sources"
```

---

### Task 8: Product sources (GitHub, Hacker News)

**Files:**
- Modify: `plugins/heuresis/heuresis/sources/products.py` (replace placeholder)
- Create: `tests/fixtures/heuresis/github_repos.json`, `tests/fixtures/heuresis/hn_search.json`
- Test: `tests/test_heuresis_products.py`

**Interfaces:**
- Consumes: `http.get`, `sources.register`, `model.Record`
- Produces: `products.GitHub`, `products.HackerNews`; `products.github_token() -> str | None` (env `GITHUB_TOKEN`, else `gh auth token`, else None)

- [ ] **Step 1: Record fixtures**

```bash
curl -s -H "Authorization: Bearer $(gh auth token)" -H "Accept: application/vnd.github+json" "https://api.github.com/search/repositories?q=idea+triage+prior+art&per_page=2" > tests/fixtures/heuresis/github_repos.json
curl -s "https://hn.algolia.com/api/v1/search?query=idea%20validation&tags=story&hitsPerPage=2" > tests/fixtures/heuresis/hn_search.json
```
If a search returns zero items, change the query until it returns two, then trim each item to the fields the adapter reads.

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_heuresis_products.py
"""GitHub and Hacker News adapters."""

from __future__ import annotations

from conftest import ROOT
from heuresis.sources import products

FIX = ROOT / "tests" / "fixtures" / "heuresis"


def test_github_search_builds_records_with_api_evidence(monkeypatch):
    seen = []
    monkeypatch.setattr(products, "github_token", lambda: "T")
    monkeypatch.setattr(products.http, "get", lambda url, headers=None: seen.append((url, headers)) or (FIX / "github_repos.json").read_bytes())
    out = products.GitHub().search("idea triage", 2)
    url, headers = seen[0]
    assert url.startswith("https://api.github.com/search/repositories?q=idea+triage")
    assert headers["Authorization"] == "Bearer T"
    assert out and out[0].kind == "repo" and out[0].url.startswith("https://github.com/")
    assert out[0].evidence_url.startswith("https://api.github.com/repos/")


def test_github_unavailable_without_token(monkeypatch):
    monkeypatch.setattr(products, "github_token", lambda: None)
    ok, why = products.GitHub().available()
    assert not ok and "GITHUB_TOKEN" in why


def test_hn_records_fall_back_to_item_page(monkeypatch):
    monkeypatch.setattr(products.http, "get", lambda url, headers=None: (FIX / "hn_search.json").read_bytes())
    out = products.HackerNews().search("idea validation", 2)
    assert out and all(r.kind == "web" for r in out)
    assert all(r.url.startswith("http") for r in out)
    assert out[0].evidence_url.startswith("https://hn.algolia.com/api/v1/items/")


def test_github_token_prefers_env(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "E")
    assert products.github_token() == "E"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_heuresis_products.py -v`
Expected: FAIL (`AttributeError: module ... has no attribute 'GitHub'`).

- [ ] **Step 4: Implement `sources/products.py`**

```python
"""Product and project sources: GitHub repositories and Hacker News stories."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.parse

from heuresis.model import Record
from heuresis.sources import http, register


def github_token() -> str | None:
    if os.environ.get("GITHUB_TOKEN"):
        return os.environ["GITHUB_TOKEN"]
    gh = shutil.which("gh")
    if not gh:
        return None
    done = subprocess.run([gh, "auth", "token"], capture_output=True, text=True, timeout=10)
    return done.stdout.strip() or None if done.returncode == 0 else None


def _json(body: bytes) -> dict:
    try:
        data = json.loads(body)
    except ValueError as exc:
        raise http.SourceError("response was not JSON") from exc
    if not isinstance(data, dict):
        raise http.SourceError("response JSON was not an object")
    return data


class GitHub:
    name, group = "github", "products"

    def available(self) -> tuple[bool, str]:
        return (True, "") if github_token() else (False, "no GITHUB_TOKEN and gh is not signed in")

    def search(self, query: str, limit: int) -> list[Record]:
        params = urllib.parse.urlencode({"q": query, "per_page": limit})
        headers = {
            "Authorization": f"Bearer {github_token()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        data = _json(http.get(f"https://api.github.com/search/repositories?{params}", headers))
        return [
            Record(
                title=item["full_name"],
                url=item["html_url"],
                source=self.name,
                kind="repo",
                text=item.get("description") or "",
                date=(item.get("pushed_at") or "")[:10],
                evidence_url=f"https://api.github.com/repos/{item['full_name']}",
            )
            for item in data.get("items", [])
        ]

    def evidence(self, record: Record) -> str | None:
        return None


class HackerNews:
    name, group = "hacker_news", "products"

    def available(self) -> tuple[bool, str]:
        return True, ""

    def search(self, query: str, limit: int) -> list[Record]:
        params = urllib.parse.urlencode({"query": query, "tags": "story", "hitsPerPage": limit})
        data = _json(http.get(f"https://hn.algolia.com/api/v1/search?{params}"))
        out = []
        for hit in data.get("hits", []):
            item = f"https://news.ycombinator.com/item?id={hit['objectID']}"
            out.append(
                Record(
                    title=hit.get("title") or "",
                    url=hit.get("url") or item,
                    source=self.name,
                    kind="web",
                    text=hit.get("story_text") or hit.get("title") or "",
                    date=(hit.get("created_at") or "")[:10],
                    evidence_url=f"https://hn.algolia.com/api/v1/items/{hit['objectID']}",
                )
            )
        return out

    def evidence(self, record: Record) -> str | None:
        return None


for _source in (GitHub(), HackerNews()):
    register(_source)
```

Fix the precedence in `github_token`'s last line so `ruff` and readers agree:
```python
    if done.returncode != 0:
        return None
    return done.stdout.strip() or None
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_heuresis_products.py tests/test_heuresis_sources.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add plugins/heuresis/heuresis/sources/products.py tests/test_heuresis_products.py tests/fixtures/heuresis/github_repos.json tests/fixtures/heuresis/hn_search.json
git commit -m "feat(heuresis): add GitHub and Hacker News sources"
```

---

### Task 9: Patent sources (Lens, EPO OPS)

**Files:**
- Modify: `plugins/heuresis/heuresis/sources/patents.py` (replace placeholder)
- Create: `tests/fixtures/heuresis/lens_search.json`, `tests/fixtures/heuresis/epo_search.xml`
- Test: `tests/test_heuresis_patents.py`

**Interfaces:**
- Consumes: `http.get`, `http.post_json`, `sources.register`
- Produces: `patents.Lens`, `patents.Epo` (both `group = "patents"`); `patents.Epo.token(self) -> str` (cached per process)

The Lens free-text request body and the EPO search parameters are UNVERIFIED on primary pages (see spec "To verify during planning"). This task records a real response first and builds against it.

- [ ] **Step 1: Get credentials (AJ)**

Lens: request API access at lens.org (profile, API access), then create a token; export `LENS_API_TOKEN`. EPO: register at developers.epo.org, create an app, export `EPO_OPS_KEY` and `EPO_OPS_SECRET`. If either is not available yet, skip to Step 4 with hand-written fixtures in the shapes below, mark the task "built against unrecorded shapes" in the PR, and record real fixtures before relying on patent coverage.

- [ ] **Step 2: Probe Lens and record a fixture**

```bash
curl -s -X POST https://api.lens.org/patent/search \
  -H "Authorization: Bearer $LENS_API_TOKEN" -H "Content-Type: application/json" \
  -d '{"query":{"query_string":{"query":"idea triage prior art search"}},"size":2,"include":["lens_id","biblio.invention_title","abstract","date_published"]}' \
  | tee tests/fixtures/heuresis/lens_search.json | head -c 600
```
Expected: JSON with `data` holding `lens_id`, `biblio.invention_title` (a list of `{text, lang}`), `abstract` (a list of `{text, lang}`), `date_published`. If the field names differ, use the recorded names in Step 4 and in the test.

- [ ] **Step 3: Probe EPO and record a fixture**

```bash
TOKEN=$(curl -s -u "$EPO_OPS_KEY:$EPO_OPS_SECRET" -d grant_type=client_credentials https://ops.epo.org/3.2/auth/accesstoken | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')
curl -s -H "Authorization: Bearer $TOKEN" -H "Range: 1-2" \
  "https://ops.epo.org/3.2/rest-services/published-data/search/biblio?q=ta%3D%22idea%20triage%22" \
  | tee tests/fixtures/heuresis/epo_search.xml | head -c 600
```
Expected: XML whose `ops:search-result` holds `exchange-document` elements with `country`, `doc-number`, `kind` attributes, `invention-title` and `abstract/p`.

- [ ] **Step 4: Write the failing tests**

```python
# tests/test_heuresis_patents.py
"""Lens and EPO adapters against recorded responses."""

from __future__ import annotations

from conftest import ROOT
from heuresis.sources import patents

FIX = ROOT / "tests" / "fixtures" / "heuresis"


def test_lens_unavailable_without_token(monkeypatch):
    monkeypatch.delenv("LENS_API_TOKEN", raising=False)
    ok, why = patents.Lens().available()
    assert not ok and "LENS_API_TOKEN" in why


def test_lens_search_parses_recorded_response(monkeypatch):
    seen = []
    monkeypatch.setenv("LENS_API_TOKEN", "L")
    monkeypatch.setattr(patents.http, "post_json", lambda url, body, headers=None: seen.append((url, body, headers)) or (FIX / "lens_search.json").read_bytes())
    out = patents.Lens().search("idea triage", 2)
    url, body, headers = seen[0]
    assert url == "https://api.lens.org/patent/search"
    assert body["query"]["query_string"]["query"] == "idea triage"
    assert headers["Authorization"] == "Bearer L"
    assert out and out[0].kind == "patent" and out[0].url.startswith("https://www.lens.org/lens/patent/")
    assert out[0].evidence_url.startswith("lens:")


def test_epo_unavailable_without_both_keys(monkeypatch):
    monkeypatch.setenv("EPO_OPS_KEY", "k")
    monkeypatch.delenv("EPO_OPS_SECRET", raising=False)
    assert not patents.Epo().available()[0]


def test_epo_search_parses_recorded_response(monkeypatch):
    monkeypatch.setattr(patents.Epo, "token", lambda self: "T")
    monkeypatch.setattr(patents.http, "get", lambda url, headers=None: (FIX / "epo_search.xml").read_bytes())
    out = patents.Epo().search("idea triage", 2)
    assert out and out[0].kind == "patent"
    assert out[0].url.startswith("https://worldwide.espacenet.com/patent/search?q=pn%3D")
```

- [ ] **Step 5: Run tests to verify they fail**

Run: `uv run pytest tests/test_heuresis_patents.py -v`
Expected: FAIL (`AttributeError`).

- [ ] **Step 6: Implement `sources/patents.py`**

```python
"""Patent sources: Lens (worldwide) and EPO Open Patent Services. Coverage is always partial."""

from __future__ import annotations

import base64
import json
import os
import urllib.parse
import xml.etree.ElementTree as ET

from heuresis.model import Record
from heuresis.sources import http, register

LENS_URL = "https://api.lens.org/patent/search"
LENS_INCLUDE = ["lens_id", "biblio.invention_title", "abstract", "date_published"]
EPO_AUTH = "https://ops.epo.org/3.2/auth/accesstoken"
EPO_SEARCH = "https://ops.epo.org/3.2/rest-services/published-data/search/biblio"
EX = "{http://www.epo.org/exchange}"


def _english(values: list[dict] | None) -> str:
    values = values or []
    chosen = next((v for v in values if v.get("lang") == "en"), values[0] if values else {})
    return str(chosen.get("text", ""))


class Lens:
    name, group = "lens", "patents"

    def available(self) -> tuple[bool, str]:
        return (True, "") if os.environ.get("LENS_API_TOKEN") else (False, "no LENS_API_TOKEN")

    def _post(self, body: dict) -> dict:
        headers = {"Authorization": f"Bearer {os.environ['LENS_API_TOKEN']}"}
        try:
            return json.loads(http.post_json(LENS_URL, body, headers))
        except ValueError as exc:
            raise http.SourceError("Lens response was not JSON") from exc

    def search(self, query: str, limit: int) -> list[Record]:
        body = {"query": {"query_string": {"query": query}}, "size": limit, "include": LENS_INCLUDE}
        out = []
        for doc in self._post(body).get("data", []):
            lens_id = doc["lens_id"]
            title = _english((doc.get("biblio") or {}).get("invention_title"))
            out.append(
                Record(
                    title=title,
                    url=f"https://www.lens.org/lens/patent/{lens_id}",
                    source=self.name,
                    kind="patent",
                    text=_english(doc.get("abstract")),
                    date=str(doc.get("date_published", "")),
                    evidence_url=f"lens:{lens_id}",
                )
            )
        return out

    def evidence(self, record: Record) -> str | None:
        lens_id = record.evidence_url.removeprefix("lens:")
        body = {"query": {"terms": {"lens_id": [lens_id]}}, "include": LENS_INCLUDE}
        docs = self._post(body).get("data", [])
        if not docs:
            return ""
        doc = docs[0]
        return f"{_english((doc.get('biblio') or {}).get('invention_title'))} {_english(doc.get('abstract'))}"


class Epo:
    name, group = "epo", "patents"
    _token: str | None = None

    def available(self) -> tuple[bool, str]:
        if os.environ.get("EPO_OPS_KEY") and os.environ.get("EPO_OPS_SECRET"):
            return True, ""
        return False, "no EPO_OPS_KEY and EPO_OPS_SECRET"

    def token(self) -> str:
        if Epo._token is None:
            pair = f"{os.environ['EPO_OPS_KEY']}:{os.environ['EPO_OPS_SECRET']}".encode()
            req_headers = {
                "Authorization": "Basic " + base64.b64encode(pair).decode(),
                "Content-Type": "application/x-www-form-urlencoded",
            }
            raw = http.post_form(EPO_AUTH, {"grant_type": "client_credentials"}, req_headers)
            Epo._token = json.loads(raw)["access_token"]
        return Epo._token

    def search(self, query: str, limit: int) -> list[Record]:
        cql = f'ta all "{query}"'
        url = f"{EPO_SEARCH}?{urllib.parse.urlencode({'q': cql})}"
        headers = {"Authorization": f"Bearer {self.token()}", "Range": f"1-{limit}"}
        try:
            root = ET.fromstring(http.get(url, headers))
        except ET.ParseError as exc:
            raise http.SourceError("EPO response was not XML") from exc
        out = []
        for doc in root.iter(f"{EX}exchange-document"):
            number = f"{doc.get('country', '')}{doc.get('doc-number', '')}{doc.get('kind', '')}"
            title = next((t.text or "" for t in doc.iter(f"{EX}invention-title") if t.get("lang") == "en"), "")
            abstract = " ".join("".join(p.itertext()) for p in doc.iter(f"{EX}p"))
            out.append(
                Record(
                    title=title,
                    url=f"https://worldwide.espacenet.com/patent/search?q=pn%3D{number}",
                    source=self.name,
                    kind="patent",
                    text=abstract,
                    evidence_url=f"epo:{number}",
                )
            )
        return out

    def evidence(self, record: Record) -> str | None:
        number = record.evidence_url.removeprefix("epo:")
        url = f"https://ops.epo.org/3.2/rest-services/published-data/publication/docdb/{number}/abstract"
        root = ET.fromstring(http.get(url, {"Authorization": f"Bearer {self.token()}"}))
        return " ".join(root.itertext())


for _source in (Lens(), Epo()):
    register(_source)
```

Add `post_form` to `sources/http.py`:
```python
def post_form(url: str, fields: dict[str, str], headers: dict[str, str] | None = None) -> bytes:
    data = urllib.parse.urlencode(fields).encode()
    merged = {"User-Agent": USER_AGENT, **(headers or {})}
    return _open(urllib.request.Request(url, data=data, headers=merged, method="POST"))
```

Wrap the two long lines (`title = next(...)` and the Lens `evidence` return) to 100 columns when running `make fix`. If the recorded Lens or EPO fixture uses other field or element names than these, change the adapter to the recorded names; the recorded fixture is the authority.

- [ ] **Step 7: Run tests**

Run: `uv run pytest tests/test_heuresis_patents.py tests/test_heuresis_sources.py -v`
Expected: PASS; `REGISTRY["patents"]` names `lens`, `epo`.

- [ ] **Step 8: Commit**

```bash
git add plugins/heuresis/heuresis/sources/patents.py plugins/heuresis/heuresis/sources/http.py tests/test_heuresis_patents.py tests/fixtures/heuresis/lens_search.json tests/fixtures/heuresis/epo_search.xml
git commit -m "feat(heuresis): add Lens and EPO patent sources"
```

---

### Task 10: Pooling and verification

**Files:**
- Create: `plugins/heuresis/heuresis/pool.py`, `plugins/heuresis/heuresis/verify.py`
- Test: `tests/test_heuresis_pool.py`, `tests/test_heuresis_verify.py`

**Interfaces:**
- Consumes: `model.Record, Coverage`, `sources.by_name`, `http.get`, `store.idea_path`
- Produces:
  - `pool.PER_SOURCE_CAP = 10`; `pool.normalize_url(url: str) -> str`
  - `pool.build(scout_files: list[Path]) -> dict` returning `{"records": [Record dicts with "ref": "r1".."rN"], "coverage": [Coverage dicts], "queries": {group: [str]}}`
  - `verify.MIN_QUOTE = 20`; `verify.normalize(text: str) -> str`; `verify.html_text(raw: str) -> str`; `verify.evidence_text(record: Record, ideas_root: Path, repos_root: Path) -> str`
  - `verify.check(record: Record, quote: str, ideas_root: Path, repos_root: Path) -> tuple[bool, str]` (reason is `""` when ok, else `quote too short`, `quote not found`, `http 404 from host`, `unreachable: host`)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_heuresis_pool.py
"""Pool: merge scout outputs, dedupe, cap per source, number records."""

from __future__ import annotations

import json
from pathlib import Path

from heuresis import pool


def scout(path: Path, group: str, records: list[dict], coverage: list[dict], queries: list[str]):
    path.write_text(json.dumps({"group": group, "queries": queries, "records": records, "coverage": coverage}))
    return path


def rec(url, source="openalex", doi=""):
    return {"title": url, "url": url, "source": source, "kind": "paper", "doi": doi}


def test_normalize_url_drops_scheme_www_slash_and_tracking():
    assert pool.normalize_url("https://www.Example.com/a/?utm_source=x&id=2") == "example.com/a?id=2"


def test_build_dedupes_by_url_and_doi_and_caps(tmp_path: Path):
    many = [rec(f"https://a.example/{i}") for i in range(15)]
    a = scout(tmp_path / "scout-papers.json", "papers", [*many, rec("http://www.a.example/1/"), rec("https://b.example/x", "arxiv", doi="10.1/x"), rec("https://c.example/y", "semantic_scholar", doi="10.1/X")], [{"source": "openalex", "status": "ok", "queries": 2, "hits": 15}], ["q1", "q2"])
    out = pool.build([a])
    urls = [r["url"] for r in out["records"]]
    assert len([u for u in urls if "a.example" in u]) == pool.PER_SOURCE_CAP
    assert len([r for r in out["records"] if r["doi"].lower() == "10.1/x"]) == 1
    assert [r["ref"] for r in out["records"]] == [f"r{i}" for i in range(1, len(urls) + 1)]
    assert out["queries"] == {"papers": ["q1", "q2"]}
    assert out["coverage"][0]["source"] == "openalex"
```

```python
# tests/test_heuresis_verify.py
"""Quote verification: normalization, local evidence, network failures."""

from __future__ import annotations

from pathlib import Path

from heuresis import verify
from heuresis.model import Record
from heuresis.sources import http

PAGE = """<html><head><script>var x = "decoy quote that is long enough";</script></head>
<body><p>We present &ldquo;IdeaScout&rdquo;&mdash;a tool that
triages   ideas against prior&nbsp;art.</p></body></html>"""


def web(url="https://p.example/x"):
    return Record(title="t", url=url, source="web", kind="web")


def test_normalize_folds_quotes_dashes_space_and_case():
    text = "\u201cIdeaScout\u201d \u2014 Triages\n  IDEAS"
    assert verify.normalize(text) == '"ideascout" - triages ideas'


def test_quote_across_entities_and_line_breaks_matches(monkeypatch):
    monkeypatch.setattr(verify.http, "get", lambda url, headers=None: PAGE.encode())
    quote = "\u201cIdeaScout\u201d\u2014a tool that triages ideas against prior art"
    ok, why = verify.check(web(), quote, Path("."), Path("."))
    assert ok, why


def test_script_text_does_not_count(monkeypatch):
    monkeypatch.setattr(verify.http, "get", lambda url, headers=None: PAGE.encode())
    ok, why = verify.check(web(), "decoy quote that is long enough", Path("."), Path("."))
    assert (ok, why) == (False, "quote not found")


def test_short_quote_is_rejected_before_fetching(monkeypatch):
    monkeypatch.setattr(verify.http, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("fetched")))
    assert verify.check(web(), "prior art", Path("."), Path(".")) == (False, "quote too short")


def test_network_failure_is_a_reason_not_a_crash(monkeypatch):
    def boom(url, headers=None):
        raise http.SourceError("http 404 from p.example")

    monkeypatch.setattr(verify.http, "get", boom)
    assert verify.check(web(), "a tool that triages ideas against", Path("."), Path(".")) == (False, "http 404 from p.example")


def test_js_only_page_drops_the_record(monkeypatch):
    monkeypatch.setattr(verify.http, "get", lambda url, headers=None: b"<html><body><div id=root></div></body></html>")
    assert verify.check(web(), "a tool that triages ideas against", Path("."), Path(".")) == (False, "quote not found")


def test_idea_and_context_records_read_local_files(tmp_path: Path):
    ideas, repos = tmp_path / "ideas-repo", tmp_path / "repos"
    (ideas / "ideas").mkdir(parents=True)
    (ideas / "ideas" / "2026-10-01-x.md").write_text("---\nid: x\n---\nAn earlier idea about triaging ideas.")
    (repos / "papers").mkdir(parents=True)
    (repos / "papers" / "references.bib").write_text("@article{k, title={Federated agents and source attribution}}")
    idea = Record(title="x", url="idea:2026-10-01-x", source="ideas", kind="idea")
    ctx = Record(title="bib", url="repo:papers/references.bib", source="context", kind="context")
    assert verify.check(idea, "An earlier idea about triaging ideas", ideas, repos) == (True, "")
    assert verify.check(ctx, "Federated agents and source attribution", ideas, repos) == (True, "")


def test_json_evidence_joins_string_leaves(monkeypatch):
    monkeypatch.setattr(verify.http, "get", lambda url, headers=None: b'{"full_name": "a/b", "description": "Triage your ideas against prior art quickly"}')
    rec = Record(title="a/b", url="https://github.com/a/b", source="github", kind="repo", evidence_url="https://api.github.com/repos/a/b")
    assert verify.check(rec, "Triage your ideas against prior art", Path("."), Path(".")) == (True, "")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_heuresis_pool.py tests/test_heuresis_verify.py -v`
Expected: FAIL (`ImportError`).

- [ ] **Step 3: Implement `pool.py`**

```python
"""Merge the scouts' outputs into one numbered, deduplicated list for the judge."""

from __future__ import annotations

import json
import urllib.parse
from pathlib import Path

from heuresis.model import Coverage, Record

# Ten records per source keeps the judge's input near 60 records across six to eight sources,
# enough to find the closest rival without burying it.
PER_SOURCE_CAP = 10
TRACKING = ("utm_", "ref", "fbclid", "gclid")


def normalize_url(url: str) -> str:
    parts = urllib.parse.urlsplit(url.strip())
    host = parts.netloc.lower().removeprefix("www.")
    query = [
        (k, v)
        for k, v in urllib.parse.parse_qsl(parts.query)
        if not any(k.startswith(t) for t in TRACKING)
    ]
    path = parts.path.rstrip("/")
    tail = f"?{urllib.parse.urlencode(query)}" if query else ""
    return f"{host}{path}{tail}" if host else url.strip()


def build(scout_files: list[Path]) -> dict:
    seen: set[str] = set()
    per_source: dict[str, int] = {}
    records: list[dict] = []
    coverage: list[dict] = []
    queries: dict[str, list[str]] = {}
    for path in scout_files:
        data = json.loads(path.read_text())
        queries[data["group"]] = list(data.get("queries", []))
        coverage += [Coverage.from_dict(c).to_dict() for c in data.get("coverage", [])]
        for raw in data.get("records", []):
            record = Record.from_dict(raw)
            keys = {normalize_url(record.url)} | ({f"doi:{record.doi.lower()}"} if record.doi else set())
            if keys & seen or per_source.get(record.source, 0) >= PER_SOURCE_CAP:
                continue
            seen |= keys
            per_source[record.source] = per_source.get(record.source, 0) + 1
            records.append({**record.to_dict(), "ref": f"r{len(records) + 1}"})
    return {"records": records, "coverage": coverage, "queries": queries}
```

- [ ] **Step 4: Implement `verify.py`**

```python
"""Check that every quoted passage appears in its source. Code, not a second model."""

from __future__ import annotations

import html
import json
import os
import re
import unicodedata
import urllib.parse
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

from heuresis import sources
from heuresis.model import Record
from heuresis.sources import http

# Under 20 characters a phrase like "federated learning" matches almost any page in the field.
MIN_QUOTE = 20
FOLD = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", "\u00a0": " "})


class _Text(HTMLParser):
    SKIP = ("script", "style", "noscript", "template")

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.depth += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.depth:
            self.depth -= 1

    def handle_data(self, data):
        if not self.depth:
            self.parts.append(data)


def html_text(raw: str) -> str:
    parser = _Text()
    parser.feed(raw)
    return " ".join(parser.parts)


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", html.unescape(text)).translate(FOLD)
    return re.sub(r"\s+", " ", text).strip().lower()


def _strings(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


def _decode(body: bytes) -> str:
    text = body.decode("utf-8", errors="replace")
    stripped = text.lstrip()
    if stripped.startswith(("{", "[")):
        try:
            return " ".join(_strings(json.loads(text)))
        except ValueError:
            pass
    if stripped.startswith("<?xml") or stripped.startswith("<feed"):
        try:
            return " ".join(ET.fromstring(body).itertext())
        except ET.ParseError:
            pass
    return html_text(text)


def _headers(url: str) -> dict[str, str]:
    host = urllib.parse.urlsplit(url).netloc
    if host == "api.semanticscholar.org" and os.environ.get("S2_API_KEY"):
        return {"x-api-key": os.environ["S2_API_KEY"]}
    return {}


def evidence_text(record: Record, ideas_root: Path, repos_root: Path) -> str:
    if record.url.startswith("idea:"):
        return (ideas_root / "ideas" / f"{record.url.removeprefix('idea:')}.md").read_text()
    if record.url.startswith("repo:"):
        return (repos_root / record.url.removeprefix("repo:")).read_text(errors="replace")
    source = sources.by_name(record.source)
    if source is not None:
        own = source.evidence(record)
        if own is not None:
            return own
    url = record.evidence_url or record.url
    return _decode(http.get(url, _headers(url)))


def check(record: Record, quote: str, ideas_root: Path, repos_root: Path) -> tuple[bool, str]:
    wanted = normalize(quote)
    if len(wanted) < MIN_QUOTE:
        return False, "quote too short"
    try:
        text = evidence_text(record, ideas_root, repos_root)
    except http.SourceError as exc:
        return False, str(exc)
    except OSError as exc:
        return False, f"unreadable: {exc.strerror or exc}"
    except Exception as exc:  # a source's own evidence call failing must not stop the run
        return False, f"{type(exc).__name__}: {exc}"
    return (True, "") if wanted in normalize(text) else (False, "quote not found")
```

The `ScholarlyError` raised by `openalex_work` is caught by the generic branch; its message reads `ScholarlyError: http 404 from api.openalex.org`.

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_heuresis_pool.py tests/test_heuresis_verify.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add plugins/heuresis/heuresis/pool.py plugins/heuresis/heuresis/verify.py tests/test_heuresis_pool.py tests/test_heuresis_verify.py
git commit -m "feat(heuresis): pool scout records and verify every quote"
```

---

### Task 11: Git sync

**Files:**
- Create: `plugins/heuresis/heuresis/sync.py`
- Test: `tests/test_heuresis_sync.py`

**Interfaces:**
- Consumes: `board.write`, `board.GENERATED`
- Produces:
  - `sync.SyncError(Exception)`
  - `sync.publish(root: Path, paths: list[Path], message: str, today: datetime.date) -> str` returning `"local"` (no remote), `"pushed"`, or raising `SyncError` with the rebase aborted and the local commit kept

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_heuresis_sync.py
"""publish: commit, rebase onto the remote, regenerate the board, push."""

from __future__ import annotations

import datetime as dt
import subprocess
from pathlib import Path

import pytest
from heuresis import board, store, sync
from heuresis.model import Idea

TODAY = dt.date(2026, 10, 15)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


def clone_pair(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    a, b = tmp_path / "a", tmp_path / "b"
    for repo in (a, b):
        subprocess.run(["git", "clone", "-q", str(remote), str(repo)], check=True, capture_output=True)
        git(repo, "config", "user.email", "t@example.com")
        git(repo, "config", "user.name", "t")
    (a / "ideas").mkdir()
    board.write(a, TODAY)
    git(a, "add", "-A")
    git(a, "commit", "-qm", "init")
    git(a, "push", "-q", "origin", "main")
    git(b, "pull", "-q", "origin", "main")
    return a, b


def add(repo: Path, idea_id: str) -> list[Path]:
    i = Idea(id=idea_id, title=idea_id, captured="2026-10-15T00:00:00", captured_via="terminal", sections={"Idea": "x"})
    return [store.save(repo, i)]


def test_publish_without_remote_commits_locally(tmp_path: Path):
    repo = tmp_path / "solo"
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "t")
    assert sync.publish(repo, add(repo, "a"), "capture a", TODAY) == "local"
    assert "capture a" in git(repo, "log", "--oneline")


def test_publish_rebases_over_a_remote_change_and_regenerates_board(tmp_path: Path):
    a, b = clone_pair(tmp_path)
    assert sync.publish(b, add(b, "from-phone"), "capture from-phone", TODAY) == "pushed"
    assert sync.publish(a, add(a, "from-terminal"), "capture from-terminal", TODAY) == "pushed"
    git(b, "pull", "-q", "origin", "main")
    text = (b / "BOARD.md").read_text()
    assert "from-phone" in text and "from-terminal" in text


def test_conflicting_idea_edit_aborts_and_keeps_local_commit(tmp_path: Path):
    a, b = clone_pair(tmp_path)
    sync.publish(a, add(a, "same"), "capture same", TODAY)
    git(b, "pull", "-q", "origin", "main")
    (a / "ideas" / "same.md").write_text((a / "ideas" / "same.md").read_text() + "\nedit A\n")
    sync.publish(a, [a / "ideas" / "same.md"], "edit A", TODAY)
    (b / "ideas" / "same.md").write_text((b / "ideas" / "same.md").read_text() + "\nedit B\n")
    with pytest.raises(sync.SyncError, match="same.md"):
        sync.publish(b, [b / "ideas" / "same.md"], "edit B", TODAY)
    assert "edit B" in git(b, "log", "--oneline", "-1")
    assert not (b / ".git" / "rebase-merge").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_heuresis_sync.py -v`
Expected: FAIL (`ImportError`).

- [ ] **Step 3: Implement `sync.py`**

```python
"""Commit idea changes and share them. BOARD.md and LOG.md are regenerated, never merged."""

from __future__ import annotations

import datetime as dt
import os
import subprocess
from pathlib import Path

from heuresis import board

PUSH_ATTEMPTS = 3  # a push that loses a race refetches and rebases; three races in a row is a real problem


class SyncError(Exception):
    """Publishing stopped and needs AJ: the local commit is kept, the rebase is aborted."""


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    env = {**os.environ, "GIT_EDITOR": "true"}
    done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, env=env)
    if check and done.returncode:
        raise SyncError(f"git {' '.join(args)} failed: {done.stderr.strip()}")
    return done


def _commit(root: Path, paths: list[Path], message: str) -> None:
    rel = [str(p.relative_to(root)) for p in paths]
    _git(root, "add", "--", *rel)
    if _git(root, "diff", "--cached", "--quiet", check=False).returncode:
        _git(root, "commit", "-q", "-m", message)


def _rebase(root: Path, branch: str) -> None:
    done = _git(root, "rebase", f"origin/{branch}", check=False)
    while done.returncode:
        conflicted = _git(root, "diff", "--name-only", "--diff-filter=U").stdout.split()
        if not conflicted or set(conflicted) - set(board.GENERATED):
            _git(root, "rebase", "--abort", check=False)
            names = ", ".join(conflicted) or "unknown files"
            raise SyncError(f"rebase onto origin/{branch} conflicts in {names}; resolve by hand")
        _git(root, "checkout", "--ours", "--", *conflicted)
        _git(root, "add", "--", *conflicted)
        done = _git(root, "rebase", "--continue", check=False)


def publish(root: Path, paths: list[Path], message: str, today: dt.date) -> str:
    generated = board.write(root, today)
    _commit(root, [*paths, *generated], message)
    if not _git(root, "remote", check=False).stdout.strip():
        return "local"
    branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    for _ in range(PUSH_ATTEMPTS):
        _git(root, "fetch", "-q", "origin", branch)
        _rebase(root, branch)
        _commit(root, board.write(root, today), "chore: regenerate board")
        if _git(root, "push", "-q", "origin", branch, check=False).returncode == 0:
            return "pushed"
    raise SyncError(f"push to origin/{branch} lost {PUSH_ATTEMPTS} races in a row")
```

On a fresh remote with no `main` yet, `git fetch origin main` fails; handle it by skipping fetch and rebase when `_git(root, "ls-remote", "--heads", "origin", branch)` prints nothing, then push with `-u`. Add that branch before the loop:
```python
    if not _git(root, "ls-remote", "--heads", "origin", branch).stdout.strip():
        _git(root, "push", "-q", "-u", "origin", branch)
        return "pushed"
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_heuresis_sync.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add plugins/heuresis/heuresis/sync.py tests/test_heuresis_sync.py
git commit -m "feat(heuresis): publish with rebase and board regeneration"
```

---

### Task 12: Section rendering and the CLI

**Files:**
- Create: `plugins/heuresis/heuresis/render.py`
- Modify: `plugins/heuresis/heuresis/cli.py`
- Test: `tests/test_heuresis_render.py`, extend `tests/test_heuresis_cli.py`

**Interfaces:**
- Consumes: everything above
- Produces CLI subcommands (all take `--ideas PATH`; triage steps take `--id ID`; all print JSON or one-line summaries):
  - `init PATH [--techne-toml F] [--repos-root D]`
  - `capture --ideas D [--via terminal|phone|form|import] TEXT...` prints the new id, publishes
  - `context --ideas D --repos-root D` prints JSON list of `{kind, repo, path}`
  - `similar --ideas D [--k 5] TEXT...` prints JSON `[[id, score], ...]`
  - `restate --ideas D --id ID --json JSON` writes `runs/ID/restate.json` and the Restated section; JSON is `{"restated": str, "queries": [str]}`
  - `search --ideas D --id ID --group papers|patents|products [--limit 8] --query Q [--query Q ...]` writes `runs/ID/scout-<group>.json`
  - `add-record --ideas D --id ID --group G --json JSON` appends one Record dict to `runs/ID/scout-<G>.json` (creating it with empty queries and coverage); group `context` is allowed here
  - `pool --ideas D --id ID` writes `runs/ID/pool.json` from every `scout-*.json` and prints it
  - `verify --ideas D --id ID --repos-root D` writes `runs/ID/verify.json`; exit 0, or 3 when the closest rival failed
  - `apply --ideas D --id ID [--today YYYY-MM-DD]` reads restate, pool, judge, verify; enforces rules; renders sections; adds the verdict; publishes; prints `ID: state (type, project)` and the reason
  - `override --ideas D ID STATE [--type T] [--project P] [--duplicate-of X] REASON...`
  - `board --ideas D`
- `render.closest_section(judge: dict, records: dict[str, dict], dropped: set[str]) -> str`; `render.product_section(judge: dict) -> str`
- judge.json shape (written by the judge agent, read by `verify` and `apply`):
```json
{
  "closest": {"ref": "r3", "quote": "...", "differs": {"domain": "...", "purpose": "...", "mechanism": "...", "evaluation": "..."}},
  "others": [{"ref": "r7", "quote": "...", "differs": "one line"}],
  "fit": "markdown",
  "product_evidence": {"rivals": ["[Name](url): pricing ..."], "demand": ["[thread](url): ..."], "riskiest_assumption": "...", "cheapest_test": "..."},
  "verdict": {"state": "later", "type": "tool", "project": "plugin:graphe", "reason": "...", "next_step": "...", "duplicate_of": null, "revisit_on": ["keyword:..."]}
}
```
- verify.json shape: `{"r3": {"ok": true, "reason": ""}, "r7": {"ok": false, "reason": "quote not found"}}`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_heuresis_render.py
"""Closest work and product evidence sections."""

from __future__ import annotations

from heuresis import render

RECORDS = {
    "r1": {"title": "Rival", "url": "https://r.example", "source": "openalex", "date": "2025"},
    "r2": {"title": "Other", "url": "https://o.example", "source": "github", "date": ""},
    "r3": {"title": "Gone", "url": "https://g.example", "source": "web", "date": ""},
}
JUDGE = {
    "closest": {"ref": "r1", "quote": "a quoted passage long enough", "differs": {"domain": "d", "purpose": "p", "mechanism": "m", "evaluation": "e"}},
    "others": [{"ref": "r2", "quote": "q2", "differs": "smaller scope"}, {"ref": "r3", "quote": "q3", "differs": "x"}],
}


def test_closest_section_lists_rival_facets_and_skips_dropped():
    text = render.closest_section(JUDGE, RECORDS, dropped={"r3"})
    assert text.startswith("**Closest:** [Rival](https://r.example) (openalex, 2025)")
    assert "> a quoted passage long enough" in text
    assert "- Mechanism: m" in text
    assert "[Other](https://o.example)" in text and "Gone" not in text


def test_product_section_leaves_unknowns_blank():
    text = render.product_section({"product_evidence": {"rivals": ["[A](https://a.example): $9/mo"], "demand": [], "riskiest_assumption": "people pay", "cheapest_test": ""}})
    assert "- [A](https://a.example): $9/mo" in text
    assert "**Demand:** unknown" in text
    assert "**Cheapest test:** unknown" in text
```

Append to `tests/test_heuresis_cli.py`:
```python
import json
import subprocess
from pathlib import Path


def init_ideas(tmp_path: Path) -> Path:
    repos = tmp_path / "repos"
    (repos / "papers").mkdir(parents=True)
    ideas = tmp_path / "ideas-repo"
    assert cli.main(["init", str(ideas), "--repos-root", str(repos)]) == 0
    for key, value in (("user.email", "t@example.com"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(ideas), "config", key, value], check=True)
    return ideas


def test_capture_rejects_empty_text(tmp_path: Path, capsys):
    ideas = init_ideas(tmp_path)
    assert cli.main(["capture", "--ideas", str(ideas), "   "]) == 2


def test_capture_then_apply_runs_the_rules(tmp_path: Path, capsys, monkeypatch):
    ideas = init_ideas(tmp_path)
    capsys.readouterr()
    assert cli.main(["capture", "--ideas", str(ideas), "A tool that triages ideas"]) == 0
    idea_id = capsys.readouterr().out.strip()
    run = ideas / "runs" / idea_id
    assert cli.main(["restate", "--ideas", str(ideas), "--id", idea_id, "--json", json.dumps({"restated": "A triage tool.", "queries": ["idea triage"]})]) == 0
    (run / "scout-papers.json").write_text(json.dumps({"group": "papers", "queries": ["idea triage"], "records": [{"title": "Rival", "url": "https://r.example", "source": "openalex", "kind": "paper", "text": "a quoted passage long enough"}], "coverage": [{"source": "openalex", "status": "ok", "queries": 1, "hits": 1}]}))
    assert cli.main(["pool", "--ideas", str(ideas), "--id", idea_id]) == 0
    judge = {"closest": {"ref": "r1", "quote": "a quoted passage long enough", "differs": {"domain": "d", "purpose": "p", "mechanism": "m", "evaluation": ""}}, "others": [], "fit": "Fits plugin:graphe.", "verdict": {"state": "do", "type": "tool", "project": "plugin:graphe", "reason": "new", "next_step": "build it"}}
    (run / "judge.json").write_text(json.dumps(judge))
    (run / "verify.json").write_text(json.dumps({"r1": {"ok": True, "reason": ""}}))
    capsys.readouterr()
    assert cli.main(["apply", "--ideas", str(ideas), "--id", idea_id, "--today", "2026-10-15"]) == 0
    out = capsys.readouterr().out
    assert "later" in out and "evaluation" in out
    text = (ideas / "ideas" / f"{idea_id}.md").read_text()
    assert "## Restated\n\nA triage tool." in text
    assert "**Closest:** [Rival](https://r.example)" in text
    assert "2026-10-15 · triage · later" in text
    assert idea_id in (ideas / "BOARD.md").read_text()


def test_override_records_an_override_verdict(tmp_path: Path, capsys):
    ideas = init_ideas(tmp_path)
    cli.main(["capture", "--ideas", str(ideas), "Something"])
    idea_id = capsys.readouterr().out.strip().splitlines()[-1]
    assert cli.main(["override", "--ideas", str(ideas), idea_id, "trash", "already", "exists"]) == 0
    assert "· override · trash" in (ideas / "ideas" / f"{idea_id}.md").read_text()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_heuresis_render.py tests/test_heuresis_cli.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `render.py`**

```python
"""Markdown for the Closest work and Product evidence sections, from the judge's JSON."""

from __future__ import annotations

from heuresis.model import FACETS


def _link(record: dict) -> str:
    meta = ", ".join(b for b in (record.get("source"), record.get("date")) if b)
    return f"[{record['title']}]({record['url']})" + (f" ({meta})" if meta else "")


def closest_section(judge: dict, records: dict[str, dict], dropped: set[str]) -> str:
    closest = judge.get("closest") or {}
    ref = closest.get("ref")
    lines = []
    if ref in records and ref not in dropped:
        lines += [f"**Closest:** {_link(records[ref])}", "", f"> {closest.get('quote', '')}", ""]
        differs = closest.get("differs") or {}
        lines += [f"- {facet.capitalize()}: {differs.get(facet, '')}" for facet in FACETS]
    else:
        lines.append("**Closest:** none verified.")
    others = [o for o in judge.get("others", []) if o.get("ref") in records and o["ref"] not in dropped]
    if others:
        lines += ["", "**Also:**", ""]
        lines += [f"- {_link(records[o['ref']])}: {o.get('differs', '')}" for o in others]
    return "\n".join(lines)


def product_section(judge: dict) -> str:
    evidence = judge.get("product_evidence") or {}
    if not evidence:
        return ""
    rivals = evidence.get("rivals") or []
    demand = evidence.get("demand") or []
    lines = ["**Paying rivals:**" + ("" if rivals else " unknown"), *[f"- {r}" for r in rivals]]
    lines += ["", "**Demand:**" + ("" if demand else " unknown"), *[f"- {d}" for d in demand]]
    lines += ["", f"**Riskiest assumption:** {evidence.get('riskiest_assumption') or 'unknown'}"]
    lines += [f"**Cheapest test:** {evidence.get('cheapest_test') or 'unknown'}"]
    return "\n".join(lines)
```

- [ ] **Step 4: Replace `cli.py` with the full command set**

```python
"""Command line for every mechanical heuresis step. Skills and agents call this."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections.abc import Sequence
from pathlib import Path

import heuresis
from heuresis import board, context, pool, render, rules, similar, sources, store, sync, verify
from heuresis.model import STATES, TYPES, Coverage, Idea, Record, Verdict

EXIT_CLOSEST_DROPPED = 3


def _now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def _run_dir(root: Path, idea_id: str) -> Path:
    path = root / "runs" / idea_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _load_idea(root: Path, idea_id: str) -> Idea:
    path = store.idea_path(root, idea_id)
    if not path.is_file():
        raise SystemExit(f"no idea {idea_id} in {root / 'ideas'}")
    return store.load(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="heuresis")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("version", help="print the heuresis version")

    p = sub.add_parser("init", help="create an ideas repository")
    p.add_argument("path", type=Path)
    p.add_argument("--techne-toml", type=Path, default=Path.home() / ".claude" / "techne.toml")
    p.add_argument("--repos-root", type=Path, required=True)

    def ideas(p: argparse.ArgumentParser, with_id: bool = False) -> argparse.ArgumentParser:
        p.add_argument("--ideas", type=Path, required=True)
        if with_id:
            p.add_argument("--id", required=True)
        return p

    p = ideas(sub.add_parser("capture", help="save an idea to the inbox"))
    p.add_argument("--via", choices=["terminal", "phone", "form", "import"], default="terminal")
    p.add_argument("text", nargs="+")

    p = ideas(sub.add_parser("context", help="list AJ's research sources that exist"))
    p.add_argument("--repos-root", type=Path, required=True)

    p = ideas(sub.add_parser("similar", help="earlier ideas sharing words with TEXT"))
    p.add_argument("--k", type=int, default=5)
    p.add_argument("text", nargs="+")

    p = ideas(sub.add_parser("restate", help="save the neutral restatement and queries"), True)
    p.add_argument("--json", required=True)

    p = ideas(sub.add_parser("search", help="run queries against one source group"), True)
    p.add_argument("--group", choices=sorted(sources.REGISTRY), required=True)
    p.add_argument("--limit", type=int, default=8)
    p.add_argument("--query", action="append", required=True)

    p = ideas(sub.add_parser("add-record", help="append one record to a scout file"), True)
    p.add_argument("--group", choices=[*sorted(sources.REGISTRY), "context"], required=True)
    p.add_argument("--json", required=True)

    ideas(sub.add_parser("pool", help="merge scout files for the judge"), True)

    p = ideas(sub.add_parser("verify", help="check every quote the judge used"), True)
    p.add_argument("--repos-root", type=Path, required=True)

    p = ideas(sub.add_parser("apply", help="enforce the rules and record the verdict"), True)
    p.add_argument("--today", type=dt.date.fromisoformat, default=None)

    p = ideas(sub.add_parser("override", help="record AJ's own decision"))
    p.add_argument("idea_id")
    p.add_argument("state", choices=STATES)
    p.add_argument("--type", choices=TYPES)
    p.add_argument("--project")
    p.add_argument("--duplicate-of")
    p.add_argument("reason", nargs="+")

    ideas(sub.add_parser("board", help="regenerate BOARD.md and LOG.md"))
    return parser


def _capture(args) -> int:
    text = " ".join(args.text).strip()
    if not text:
        print("heuresis: the idea text is empty", file=sys.stderr)
        return 2
    taken = [p.stem for p in (args.ideas / "ideas").glob("*.md")]
    title = store.title_from(text)
    idea = Idea(
        id=store.new_id(dt.date.today(), title, taken),
        title=title,
        captured=_now(),
        captured_via=args.via,
        sections={"Idea": text},
    )
    path = store.save(args.ideas, idea)
    sync.publish(args.ideas, [path], f"capture: {idea.id}", dt.date.today())
    print(idea.id)
    return 0


def _search(args) -> int:
    group = sources.REGISTRY[args.group]
    records, coverage = sources.run_queries(group, args.query, args.limit)
    out = _run_dir(args.ideas, args.id) / f"scout-{args.group}.json"
    payload = {
        "group": args.group,
        "queries": args.query,
        "records": [r.to_dict() for r in records],
        "coverage": [c.to_dict() for c in coverage],
    }
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    for c in coverage:
        print(c.line())
    return 0


def _add_record(args) -> int:
    record = Record.from_dict(json.loads(args.json))
    out = _run_dir(args.ideas, args.id) / f"scout-{args.group}.json"
    data = json.loads(out.read_text()) if out.exists() else {"group": args.group, "queries": [], "records": [], "coverage": []}
    data["records"].append(record.to_dict())
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    return 0


def _verify(args) -> int:
    run = _run_dir(args.ideas, args.id)
    judge = json.loads((run / "judge.json").read_text())
    records = {r["ref"]: r for r in json.loads((run / "pool.json").read_text())["records"]}
    cited = [judge.get("closest") or {}, *judge.get("others", [])]
    results = {}
    for item in cited:
        ref = item.get("ref")
        if ref not in records:
            results[str(ref)] = {"ok": False, "reason": "not in pool"}
            continue
        ok, why = verify.check(Record.from_dict(records[ref]), item.get("quote", ""), args.ideas, args.repos_root)
        results[ref] = {"ok": ok, "reason": why}
    (run / "verify.json").write_text(json.dumps(results, indent=2))
    closest_ref = (judge.get("closest") or {}).get("ref")
    for ref, result in results.items():
        print(f"{ref}: {'ok' if result['ok'] else result['reason']}")
    if closest_ref and not results.get(closest_ref, {}).get("ok"):
        return EXIT_CLOSEST_DROPPED
    return 0


def _apply(args) -> int:
    today = args.today or dt.date.today()
    run = _run_dir(args.ideas, args.id)
    idea = _load_idea(args.ideas, args.id)
    judge = json.loads((run / "judge.json").read_text())
    pooled = json.loads((run / "pool.json").read_text())
    checked = json.loads((run / "verify.json").read_text())
    records = {r["ref"]: r for r in pooled["records"]}
    dropped = {ref for ref, r in checked.items() if not r["ok"]}
    proposed = judge["verdict"]
    closest = judge.get("closest")
    closest_ref = (closest or {}).get("ref")
    verdict = Verdict(
        date=today.isoformat(),
        origin="triage",
        state=proposed["state"],
        reason=proposed.get("reason", ""),
        type=proposed.get("type"),
        project=proposed.get("project"),
        next_step=proposed.get("next_step", ""),
        duplicate_of=proposed.get("duplicate_of"),
        coverage=[Coverage.from_dict(c) for c in pooled["coverage"]],
        dropped=[f"{records[r]['url']} ({checked[r]['reason']})" for r in sorted(dropped) if r in records],
    )
    known = {p.stem for p in (args.ideas / "ideas").glob("*.md")} - {idea.id}
    verdict = rules.enforce(
        verdict,
        closest=closest if closest_ref in records else None,
        closest_verified=bool(checked.get(closest_ref, {}).get("ok")),
        known_ids=known,
        today=today,
    )
    idea.sections["Closest work"] = render.closest_section(judge, records, dropped)
    idea.sections["Fit with your work"] = judge.get("fit", "")
    product = render.product_section(judge)
    if product:
        idea.sections["Product evidence"] = product
    idea.revisit_on = list(proposed.get("revisit_on") or idea.revisit_on)
    store.add_verdict(idea, verdict)
    path = store.save(args.ideas, idea)
    paths = [path, *sorted(run.glob("*.json"))]
    sync.publish(args.ideas, paths, f"triage: {idea.id} -> {verdict.state}", today)
    print(f"{idea.id}: {verdict.state} ({verdict.type or 'no type'}, {verdict.project or 'no project'})")
    print(verdict.reason)
    return 0


def _override(args) -> int:
    today = dt.date.today()
    idea = _load_idea(args.ideas, args.idea_id)
    verdict = Verdict(
        date=today.isoformat(),
        origin="override",
        state=args.state,
        reason=" ".join(args.reason),
        type=args.type,
        project=args.project,
        duplicate_of=args.duplicate_of,
    )
    known = {p.stem for p in (args.ideas / "ideas").glob("*.md")} - {idea.id}
    if args.state == "merged" and args.duplicate_of not in known:
        print(f"heuresis: --duplicate-of must name an existing idea", file=sys.stderr)
        return 2
    if args.state == "later":
        verdict.revisit = (today + rules.REVISIT_AFTER_INSUFFICIENT).isoformat()
    store.add_verdict(idea, verdict)
    sync.publish(args.ideas, [store.save(args.ideas, idea)], f"override: {idea.id} -> {args.state}", today)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    match args.command:
        case "version":
            print(heuresis.__version__)
            return 0
        case "init":
            context.init_repo(args.path, args.techne_toml, args.repos_root)
            print(args.path)
            return 0
        case "capture":
            return _capture(args)
        case "context":
            projects = context.load_projects(args.ideas / "projects.toml")
            found = context.resolve_sources(args.ideas / "context.toml", projects, args.repos_root)
            print(json.dumps(found, indent=2))
            return 0
        case "similar":
            ideas = [i for _, i, _ in store.load_all(args.ideas) if i is not None]
            print(json.dumps(similar.similar(" ".join(args.text), ideas, args.k)))
            return 0
        case "restate":
            data = json.loads(args.json)
            run = _run_dir(args.ideas, args.id)
            (run / "restate.json").write_text(json.dumps(data, indent=2, ensure_ascii=False))
            idea = _load_idea(args.ideas, args.id)
            idea.sections["Restated"] = data["restated"]
            store.save(args.ideas, idea)
            return 0
        case "search":
            return _search(args)
        case "add-record":
            return _add_record(args)
        case "pool":
            run = _run_dir(args.ideas, args.id)
            pooled = pool.build(sorted(run.glob("scout-*.json")))
            (run / "pool.json").write_text(json.dumps(pooled, indent=2, ensure_ascii=False))
            print(json.dumps(pooled, ensure_ascii=False))
            return 0
        case "verify":
            return _verify(args)
        case "apply":
            return _apply(args)
        case "override":
            return _override(args)
        case "board":
            board.write(args.ideas, dt.date.today())
            return 0
    raise AssertionError(f"unhandled command {args.command}")
```

`init --techne-toml` defaults to `~/.claude/techne.toml`, which is a path in code, not published Markdown, so the packaging test is unaffected. Break the long `data = ...` line in `_add_record` and the `dropped=[...]` and `verify.check(...)` lines to 100 columns with `make fix`; remove the `f` prefix from the `--duplicate-of` error string (ruff F541).

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_heuresis_render.py tests/test_heuresis_cli.py -v`
Expected: PASS

- [ ] **Step 6: Lint and commit**

Run: `make fix && make lint`
Expected: clean.

```bash
git add plugins/heuresis/heuresis/render.py plugins/heuresis/heuresis/cli.py tests/test_heuresis_render.py tests/test_heuresis_cli.py
git commit -m "feat(heuresis): add the triage CLI and section rendering"
```

---

### Task 13: Agents and the idea skill

**Files:**
- Create: `plugins/heuresis/agents/scout-papers.md`, `scout-patents.md`, `scout-products.md`, `scout-context.md`, `judge.md`, `plugins/heuresis/skills/idea/SKILL.md`
- Test: `tests/test_heuresis_agents.py`

**Interfaces:**
- Consumes: the CLI from Task 12
- Produces: agents `heuresis:scout-papers`, `heuresis:scout-patents`, `heuresis:scout-products`, `heuresis:scout-context`, `heuresis:judge`; skill `heuresis:idea`

- [ ] **Step 1: Write the failing structural test**

```python
# tests/test_heuresis_agents.py
"""Agent frontmatter pins model, tools and turns; the skill names every agent it dispatches."""

from __future__ import annotations

import re

import yaml
from conftest import ROOT

PLUGIN = ROOT / "plugins" / "heuresis"
SCOUTS = ("scout-papers", "scout-patents", "scout-products", "scout-context")


def front(path):
    text = path.read_text()
    return yaml.safe_load(text.split("---", 2)[1]), text


def test_scouts_pin_sonnet_and_judge_pins_opus_without_web():
    for name in SCOUTS:
        meta, _ = front(PLUGIN / "agents" / f"{name}.md")
        assert meta["model"] == "sonnet" and isinstance(meta["maxTurns"], int)
    meta, _ = front(PLUGIN / "agents" / "judge.md")
    assert meta["model"] == "opus"
    tools = {t.strip() for t in meta["tools"].split(",")}
    assert not tools & {"WebSearch", "WebFetch", "Bash"}


def test_skill_dispatches_every_agent_and_uses_the_plugin_venv():
    _, text = front(PLUGIN / "skills" / "idea" / "SKILL.md")
    for name in (*SCOUTS, "judge"):
        assert f"heuresis:{name}" in text
    assert "UV_PROJECT_ENVIRONMENT=${CLAUDE_PLUGIN_DATA}/venv" in text
    assert "${user_config.ideas_repo}" in text


def test_no_agent_or_skill_text_uses_em_dashes():
    for path in [*PLUGIN.glob("agents/*.md"), *PLUGIN.glob("skills/*/SKILL.md")]:
        assert "\u2014" not in path.read_text(), path
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_heuresis_agents.py -v`
Expected: FAIL (files missing).

- [ ] **Step 3: Write the agents**

Each agent body uses the same invocation line. `H` below stands for:
`env UV_PROJECT_ENVIRONMENT=${CLAUDE_PLUGIN_DATA}/venv uv run --quiet --directory ${CLAUDE_PLUGIN_ROOT} python -m heuresis`

`plugins/heuresis/agents/scout-papers.md`:
```markdown
---
name: scout-papers
description: Searches OpenAlex, Semantic Scholar and arXiv for the papers closest to one heuresis idea and saves the records. Dispatched by heuresis:idea; not for direct use.
model: sonnet
effort: medium
maxTurns: 15
tools: Bash, Read
---

You search the literature for one idea. The prompt gives you `IDEAS` (absolute path), `ID`, the neutral restatement and starting queries.

1. Write 3 to 5 queries of 3 or 4 high-signal words each: broad first, then narrower. OpenAlex ANDs every term, so a five-word query often returns nothing. Include the starting queries that fit.
2. Run them all in one call:
   `env UV_PROJECT_ENVIRONMENT=${CLAUDE_PLUGIN_DATA}/venv uv run --quiet --directory ${CLAUDE_PLUGIN_ROOT} python -m heuresis search --ideas IDEAS --id ID --group papers --query "..." --query "..."`
3. Read `IDEAS/runs/ID/scout-papers.json`. If fewer than 5 records look relevant, run one more search with 2 or 3 rephrased queries.
4. Reply with one line per source from the coverage, then the 5 most relevant record titles. Do not judge novelty; the judge does that.
```

`plugins/heuresis/agents/scout-patents.md`: same frontmatter with `name: scout-patents`, description "Searches Lens and EPO patents ...", body identical in shape with `--group patents`, and the line: "Patent search covers granted and published patents only in the offices these sources index. Say so in your reply."

`plugins/heuresis/agents/scout-products.md`:
```markdown
---
name: scout-products
description: Searches GitHub, Hacker News and the web for products, projects and launches closest to one heuresis idea and saves the records. Dispatched by heuresis:idea; not for direct use.
model: sonnet
effort: medium
maxTurns: 20
tools: Bash, Read, WebSearch, WebFetch
---

You look for things that already exist: products, open-source projects, launches, paid tools. The prompt gives you `IDEAS`, `ID`, the restatement and starting queries.

1. Run GitHub and Hacker News:
   `env UV_PROJECT_ENVIRONMENT=${CLAUDE_PLUGIN_DATA}/venv uv run --quiet --directory ${CLAUDE_PLUGIN_ROOT} python -m heuresis search --ideas IDEAS --id ID --group products --query "..." --query "..."`
2. Run 3 to 5 WebSearch queries for products and pricing pages ("<capability> tool", "<capability> app pricing", "alternatives to <closest product>").
3. For each promising web result, WebFetch the page and copy one passage of at least 25 characters, verbatim from the page text, that shows what the product does. Save it:
   `... python -m heuresis add-record --ideas IDEAS --id ID --group products --json '{"title": "...", "url": "...", "source": "web", "kind": "product", "text": "<the verbatim passage>"}'`
   Only save passages you saw in the fetched page. A page that renders its text with JavaScript usually has no usable passage; skip it.
4. For a paid product, also save its pricing page the same way, with the price passage as `text`.
5. Reply with the saved titles, which ones charge money, and the coverage lines.
```

`plugins/heuresis/agents/scout-context.md`:
```markdown
---
name: scout-context
description: Reads AJ's own bibliography, related-work notes, decks, ROADMAPs, plugin marketplace and earlier ideas for anything one heuresis idea touches, and saves facts with exact passages. Dispatched by heuresis:idea; not for direct use.
model: sonnet
effort: medium
maxTurns: 15
tools: Bash, Read, Grep, Glob
---

You report facts from AJ's own work. Never an opinion about the idea. The prompt gives you `IDEAS`, `REPOS`, `ID`, the restatement and its key terms.

1. List the sources: `env UV_PROJECT_ENVIRONMENT=${CLAUDE_PLUGIN_DATA}/venv uv run --quiet --directory ${CLAUDE_PLUGIN_ROOT} python -m heuresis context --ideas IDEAS --repos-root REPOS`
2. Find earlier ideas: `... python -m heuresis similar --ideas IDEAS "<restatement>"`. Read each candidate with a score of 0.15 or more.
3. Grep the sources for the key terms. Read the matching parts.
4. Save each relevant fact with a verbatim passage of at least 25 characters:
   - an earlier idea: `... add-record --ideas IDEAS --id ID --group context --json '{"title": "<idea id>", "url": "idea:<idea id>", "source": "ideas", "kind": "idea", "text": "<passage>"}'`
   - a file in a repo: `{"title": "<what it is>", "url": "repo:<repo>/<path inside repo>", "source": "context", "kind": "context", "text": "<passage>"}`
5. Reply with: which project the idea most likely belongs to (a name from `IDEAS/projects.toml`, or "new: <name>"), the bib keys it touches, any earlier idea it nearly duplicates (id and why), and nothing else.
```

`plugins/heuresis/agents/judge.md`:
```markdown
---
name: judge
description: Decides one heuresis idea's verdict from the pooled records only, naming the closest rival and arguing first that the idea is not new. Dispatched by heuresis:idea; not for direct use.
model: opus
effort: high
maxTurns: 6
tools: Read, Write
---

You judge one idea using only what the scouts retrieved. You have no web access. The prompt gives you `IDEAS`, `ID`, and the context scout's report.

Read `IDEAS/runs/ID/restate.json` (the idea, restated neutrally) and `IDEAS/runs/ID/pool.json` (numbered records `r1`, `r2`, ... with their text, and per-source coverage). If the prompt lists dropped refs, do not use them.

1. Pick the closest rival: the record that does most of what the idea does. Argue, in your head, that the idea is not new because of it. Only then compare it on four facets: domain, purpose, mechanism, evaluation. Say "same" for a facet where they match.
2. For the closest rival and up to ten others, copy one quote of at least 25 characters verbatim from that record's `text`. A quote that is not character-for-character in `text` will be dropped by the verifier.
3. Decide:
   - `trash`: it exists and the closest rival does what the idea does on every facet, or it is infeasible.
   - `merged`: it nearly duplicates an earlier idea named by the context scout. Set `duplicate_of`.
   - `do`: it differs from the closest rival on at least one facet in a way that matters, and the evidence is there. Set `type` (`product`, `tool`, `research`, `improve`) and `project`.
   - `later`: plausible, not now, or the evidence is thin.
   Do not choose `do` because the idea sounds good. When coverage shows paper sources failed or empty, choose `later`.
4. For type `product`, fill `product_evidence` from saved records only: paying rivals with their pricing passage, demand links, the riskiest assumption, the cheapest test (waitlist, pre-sale). Leave unknowns empty.
5. Write `IDEAS/runs/ID/judge.json`:
   `{"closest": {"ref", "quote", "differs": {"domain", "purpose", "mechanism", "evaluation"}}, "others": [{"ref", "quote", "differs"}], "fit": "<markdown: project, bib keys, earlier ideas, from the context scout>", "product_evidence": {...} or {}, "verdict": {"state", "type", "project", "reason", "next_step", "duplicate_of", "revisit_on": ["keyword:...", "project:..."]}}`
6. Reply with the state and one sentence of reason.
```

- [ ] **Step 4: Write `plugins/heuresis/skills/idea/SKILL.md`**

```markdown
---
name: idea
description: Capture an idea and triage it against prior work. Saves the idea to AJ's ideas repository, then searches papers, patents, products and his own research for anything like it, names the closest existing work, and files the idea as trash, later, do or merged with the evidence. Use when the user shares an idea for an app, tool, product, research direction or improvement and wants it saved or checked, such as "I have an idea", "save this idea", "has anyone built", "is this worth building", "triage my idea", or "/heuresis:idea". Not for reviewing a written paper's novelty (graphe:paper-review).
argument-hint: "[--now] <idea text> | --triage <id> | --retriage <id> | --override <id> <state> <reason>"
disable-model-invocation: false
allowed-tools: Bash Read Write Agent
---

# Capture and triage an idea

`IDEAS` is `${user_config.ideas_repo}` and `REPOS` is `${user_config.repos_root}`. If either is empty, stop and run `/heuresis:setup`.

Every command below starts with:
`env UV_PROJECT_ENVIRONMENT=${CLAUDE_PLUGIN_DATA}/venv uv run --quiet --directory ${CLAUDE_PLUGIN_ROOT} python -m heuresis`
(written `heuresis` below). Pass `IDEAS` and `REPOS` as absolute paths.

## Pick the mode

- `<idea text>` without `--now`: capture only. Run `heuresis capture --ideas IDEAS <text>`, print the id, and say it is in the inbox and can be triaged with `--triage <id>`. Stop.
- `--now <idea text>`: capture, then triage the new id.
- `--triage <id>` or `--retriage <id>`: triage an existing idea. A retriage adds a new verdict and keeps the old ones.
- `--override <id> <state> [--type T] [--project P] [--duplicate-of X] <reason>`: run `heuresis override --ideas IDEAS <id> <state> ... <reason>` and stop. This records AJ's own decision.

## Triage

1. **Restate.** Read the idea file `IDEAS/ideas/<id>.md`. Write a neutral one-paragraph restatement: what it does, for whom, how. Drop praise, excitement and claims of novelty. Write 3 to 5 search queries of 3 or 4 words. Save both:
   `heuresis restate --ideas IDEAS --id <id> --json '{"restated": "...", "queries": ["...", "..."]}'`
2. **Scout in parallel.** In one message, dispatch four Agent calls with `subagent_type` `heuresis:scout-papers`, `heuresis:scout-patents`, `heuresis:scout-products` and `heuresis:scout-context`. Give each `IDEAS`, `REPOS`, the id, the restatement and the queries. Do not pass AJ's original wording or any opinion about the idea.
3. **Pool.** `heuresis pool --ideas IDEAS --id <id> > /dev/null`
4. **Judge.** Dispatch `heuresis:judge` with `IDEAS`, the id and the context scout's reply.
5. **Verify.** `heuresis verify --ideas IDEAS --id <id> --repos-root REPOS`. Exit 3 means the closest rival's quote failed: dispatch `heuresis:judge` once more, listing the failed refs as dropped, then verify again. Do not loop a third time.
6. **Apply.** `heuresis apply --ideas IDEAS --id <id>`. The rules run here: a `do` without a verified closest rival and paper results becomes `later`.
7. **Report** to AJ in four lines: the state, type and project; the closest rival with its link; the reason; the next step. Link the idea file. If any source was skipped for a missing key, name the key once.
```

- [ ] **Step 5: Run tests and validation**

Run: `uv run pytest tests/test_heuresis_agents.py -v && make frontmatter plugin-validate && bash scripts/check_plugin_refs.sh`
Expected: PASS and `Validation passed`.

- [ ] **Step 6: Commit**

```bash
git add plugins/heuresis/agents plugins/heuresis/skills/idea tests/test_heuresis_agents.py
git commit -m "feat(heuresis): add the scout and judge agents and the idea skill"
```

---

### Task 14: Setup skill, doctor and runbook

**Files:**
- Create: `plugins/heuresis/skills/setup/SKILL.md`, `plugins/heuresis/skills/setup/scripts/doctor.py`, `plugins/heuresis/AGENTS.md`, `plugins/heuresis/_shared/doctor_lib.py` (copy), `plugins/heuresis/evals/fires-setup/{prompt.md,graders/fires-setup.md}`, `plugins/heuresis/evals/never-setup-idea/{prompt.md,graders/fires-expected.md,graders/not-setup.md}`
- Test: `tests/test_heuresis_doctor.py`

**Interfaces:**
- Consumes: `doctor_lib` (`Check`, `OK`, `MISSING`, `OPTIONAL`, `program`, `guarded`, `report`, `detect_platform`, `FIXES["uv"]`, `FIXES["git"]`, `FIXES["gh"]`; check the exact keys in `plugins/techne/_shared/doctor_lib.py` `FIXES` and use the names it defines)
- Produces: `doctor.py IDEAS_REPO=<path> REPOS_ROOT=<path>` printing doctor lines; `doctor.checks(values: dict[str, str], environ: Mapping[str, str]) -> list[Check]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_heuresis_doctor.py
"""heuresis setup doctor: tools, folders, keys."""

from __future__ import annotations

import subprocess
import sys

from conftest import DOCTOR_LINE, HOOK_PYTHON, ROOT, _load

DOCTOR = ROOT / "plugins" / "heuresis" / "skills" / "setup" / "scripts" / "doctor.py"
d = _load("heuresis_doctor", DOCTOR)


def names(checks):
    return {c.name: c.status for c in checks}


def test_missing_ideas_repo_is_missing_and_keys_are_optional(tmp_path):
    found = names(d.checks({"IDEAS_REPO": str(tmp_path / "nope"), "REPOS_ROOT": str(tmp_path)}, environ={}))
    assert found["ideas_repo"] == "missing"
    assert found["OPENALEX_API_KEY"] == "optional"
    assert found["LENS_API_TOKEN"] == "optional"


def test_ready_ideas_repo_and_keys(tmp_path):
    repo = tmp_path / "ideas"
    (repo / "ideas").mkdir(parents=True)
    (repo / "projects.toml").write_text("")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    env = {k: "x" for k in ("OPENALEX_API_KEY", "S2_API_KEY", "LENS_API_TOKEN", "EPO_OPS_KEY", "EPO_OPS_SECRET")}
    found = names(d.checks({"IDEAS_REPO": str(repo), "REPOS_ROOT": str(tmp_path)}, environ=env))
    assert found["ideas_repo"] == "ok" and found["LENS_API_TOKEN"] == "ok" and found["EPO_OPS"] == "ok"


def test_output_lines_follow_the_doctor_format(tmp_path):
    done = subprocess.run([HOOK_PYTHON, str(DOCTOR), f"IDEAS_REPO={tmp_path}", f"REPOS_ROOT={tmp_path}"], capture_output=True, text=True)
    assert all(DOCTOR_LINE.match(line) for line in done.stdout.splitlines()), done.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_heuresis_doctor.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `doctor.py`** (system python3 3.9+, stdlib only, matching the phylax doctor's structure)

```python
#!/usr/bin/env python3
"""Check what heuresis needs: uv, git, gh, the ideas repository, the repos folder, API keys.

Runs on the system python3 (3.9 or newer, standard library only) and installs nothing.
Usage: python3 doctor.py IDEAS_REPO=<path> REPOS_ROOT=<path>
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from pathlib import Path

sys.dont_write_bytecode = True
PLUGIN = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN / "_shared"))
import doctor_lib as d  # noqa: E402  # ty: ignore[unresolved-import]

KEYS = (
    ("OPENALEX_API_KEY", "raises OpenAlex's daily search budget tenfold; free at openalex.org/settings/api"),
    ("S2_API_KEY", "adds Semantic Scholar; request one at semanticscholar.org/product/api"),
    ("LENS_API_TOKEN", "adds worldwide patents; request API access in your lens.org profile"),
)


def parse(argv: list[str]) -> dict[str, str]:
    values = {}
    for arg in argv:
        key, sep, value = arg.partition("=")
        if sep:
            values[key] = value.strip()
    return values


def folder(name: str, value: str, need_ideas: bool) -> d.Check:
    if not value or value.startswith("${"):
        return d.Check(d.MISSING, name, "not set; set it in /config under the heuresis plugin")
    path = Path(value).expanduser()
    if not path.is_dir():
        return d.Check(d.MISSING, name, f"{path} does not exist")
    if need_ideas and not ((path / "ideas").is_dir() and (path / ".git").exists()):
        return d.Check(d.MISSING, name, f"{path} is not an ideas repository; the runbook creates one")
    return d.Check(d.OK, name, str(path))


def checks(values: Mapping[str, str], environ: Mapping[str, str]) -> list[d.Check]:
    platform = d.detect_platform()
    found = [
        d.program(platform, "uv", "uv", version_argv=("--version",)),
        d.program(platform, "git", "git", version_argv=("--version",)),
        d.program(platform, "gh", "gh", required=False, why="GitHub search and the private ideas remote"),
        folder("ideas_repo", values.get("IDEAS_REPO", ""), need_ideas=True),
        folder("repos_root", values.get("REPOS_ROOT", ""), need_ideas=False),
    ]
    for key, why in KEYS:
        status = d.OK if environ.get(key) else d.OPTIONAL
        found.append(d.Check(status, key, "set" if status == d.OK else f"not set; {why}"))
    epo = environ.get("EPO_OPS_KEY") and environ.get("EPO_OPS_SECRET")
    found.append(
        d.Check(
            d.OK if epo else d.OPTIONAL,
            "EPO_OPS",
            "set" if epo else "EPO_OPS_KEY and EPO_OPS_SECRET not set; adds European patents; register at developers.epo.org",
        )
    )
    return found


def main() -> int:
    return d.report(checks(parse(sys.argv[1:]), os.environ))


if __name__ == "__main__":
    sys.exit(main())
```

If `FIXES` has no `git` or `gh` key, use the closest existing key and add the missing entries to `plugins/techne/_shared/doctor_lib.py` (then re-copy it to every plugin `_shared/` that carries it, and run `make guards`). Wrap long lines with `make fix`.

Copy: `cp plugins/techne/_shared/doctor_lib.py plugins/heuresis/_shared/doctor_lib.py`.

- [ ] **Step 4: Write `skills/setup/SKILL.md`, `AGENTS.md` and the setup evals**

`plugins/heuresis/skills/setup/SKILL.md`:
```markdown
---
name: setup
description: Check and set up heuresis, the idea triage plugin. Checks uv, git and gh, the ideas repository and repos folder set in /config, and which search API keys are present (OpenAlex, Semantic Scholar, Lens, EPO), and creates the private ideas repository when it does not exist. Use after installing heuresis, when /heuresis:idea says the ideas repository is not set, or when a source shows skipped in a verdict.
---

# Set up heuresis

Read `${CLAUDE_PLUGIN_ROOT}/AGENTS.md` and follow it. It starts by running this doctor:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/setup/scripts/doctor.py" 'IDEAS_REPO=${user_config.ideas_repo}' 'REPOS_ROOT=${user_config.repos_root}'
```
```

`plugins/heuresis/AGENTS.md` (the runbook; no personal paths or emails):
```markdown
# heuresis setup runbook

1. Run the doctor from the setup skill. Fix every `missing` line first; each prints its fix.
2. **Repos folder.** Set `repos_root` in `/config` under heuresis to the folder that holds your clones (papers, talks, your project repos).
3. **Ideas repository.** If `ideas_repo` is missing:
   - Pick a folder next to your other clones, for example `<repos_root>/ideas`, and set `ideas_repo` in `/config` to it.
   - Create it: `env UV_PROJECT_ENVIRONMENT=${CLAUDE_PLUGIN_DATA}/venv uv run --quiet --directory ${CLAUDE_PLUGIN_ROOT} python -m heuresis init <ideas_repo> --repos-root <repos_root>`
   - Make the first commit: `git -C <ideas_repo> add -A && git -C <ideas_repo> commit -m "init: ideas repository"`
   - Ask the user before creating the GitHub remote. Then: `gh repo create ideas --private --source <ideas_repo> --push`
4. **Keys.** Each `optional` key line names what it adds and where to get it. Export each key in the shell profile Claude Code starts from (`~/.bashrc` or `~/.zshrc`) and restart Claude Code. Never paste a key into a chat or a file in a repository.
5. Run the doctor again. `result: ready` means `/heuresis:idea --now <idea>` works.
```

Evals (copy the epistole shapes exactly; the eval plugin is generated by `scripts/eval-plugin.sh` and named `heuresis`):

`plugins/heuresis/evals/fires-setup/prompt.md`:
```markdown
---
max_turns: 6
timeout_seconds: 240
runs: 3
allowed_tools: [Read, Glob, Grep, Skill]
plugins: ["../../eval-fixtures/with-rivals"]
tags: [routing]
---

I just installed heuresis. Get it ready so I can start triaging ideas.
```
`plugins/heuresis/evals/fires-setup/graders/fires-setup.md`:
```markdown
---
type: tool_used
tool: Skill
input_match: '"skill"\s*:\s*"heuresis:setup"'
---
```
`plugins/heuresis/evals/never-setup-idea/prompt.md`: same frontmatter with `tags: [routing, collision]`, body `I have an idea: a browser extension that summarizes long GitHub issue threads. Has anyone built this?`
`plugins/heuresis/evals/never-setup-idea/graders/fires-expected.md`: `type: tool_used`, `tool: Skill`, `input_match: '"skill"\s*:\s*"heuresis:idea"'`, `arm: both`.
`plugins/heuresis/evals/never-setup-idea/graders/not-setup.md`: `type: tool_used`, `tool: Skill`, `input_match: '"skill"\s*:\s*"heuresis:setup"'`, `min: 0`, `max: 0`, `arm: both`.

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_heuresis_doctor.py tests/test_plugin_packaging.py -v && make guards test-hooks-oldest`
Expected: PASS (packaging test now sees a setup skill, AGENTS.md, fires-setup and never-setup-* evals, and the docs page link to AGENTS.md).

- [ ] **Step 6: Commit**

```bash
git add plugins/heuresis/skills/setup plugins/heuresis/AGENTS.md plugins/heuresis/_shared/doctor_lib.py plugins/heuresis/evals tests/test_heuresis_doctor.py
git commit -m "feat(heuresis): add the setup skill, doctor and runbook"
```

---

### Task 15: Idea routing evals

**Files:**
- Create: `plugins/heuresis/evals/fires-idea/{prompt.md,graders/fires-idea.md}`, `plugins/heuresis/evals/never-idea-paper-review/{prompt.md,graders/fires-expected.md,graders/not-idea.md}`

- [ ] **Step 1: Write the cases**

`fires-idea/prompt.md`: routing frontmatter as above, body: `Random idea: an app that turns my scattered notes into a ranked backlog of things worth building. Save it and tell me if something like it already exists.`
`fires-idea/graders/fires-idea.md`: `input_match: '"skill"\s*:\s*"heuresis:idea"'`.
`never-idea-paper-review/prompt.md`: frontmatter `tags: [routing, collision]`, body: `My paper draft is in this repo. Before I submit, check whether its contributions are actually novel and what related work it misses.`
`never-idea-paper-review/graders/fires-expected.md`: `input_match: '"skill"\s*:\s*"heuresis:paper-review"'`, `arm: both` (the generated eval plugin carries graphe's paper-review under the host name).
`never-idea-paper-review/graders/not-idea.md`: `input_match: '"skill"\s*:\s*"heuresis:idea"'`, `min: 0`, `max: 0`, `arm: both`.

- [ ] **Step 2: Run the routing evals for heuresis**

Run: `bash scripts/eval-plugin.sh && (cd plugins/heuresis && claude plugin eval . --tag routing --ablation none --trust-plugin --no-publish -j 2 --threshold 0.9)`
Expected: every case passes at 0.9 or better. This draws on AJ's plan usage. If the collision case fails, tighten the `heuresis:idea` description's last sentence and rerun; do not loosen paper-review.

- [ ] **Step 3: Commit**

```bash
git add plugins/heuresis/evals/fires-idea plugins/heuresis/evals/never-idea-paper-review
git commit -m "test(heuresis): add idea routing evals"
```

---

### Task 16: End-to-end smoke on a scratch ideas repo

**Files:** none committed; this task proves the pipeline runs against live APIs.

- [ ] **Step 1: Load the plugin from the worktree and create a scratch repo**

```bash
SCRATCH=$(mktemp -d)
env UV_PROJECT_ENVIRONMENT=$SCRATCH/venv uv run --quiet --directory plugins/heuresis python -m heuresis init $SCRATCH/ideas --repos-root "$HOME/ajsoftworks"
```
Expected: `$SCRATCH/ideas` with `projects.toml` listing AJ's sisters, plugins and papers.

- [ ] **Step 2: Drive one triage in a tmux session**

```bash
tmux new-session -d -s heuresis-smoke "script -qc 'claude --plugin-dir plugins/heuresis' /tmp/heuresis-smoke.log"
tmux send-keys -t heuresis-smoke "/heuresis:idea --now A Claude Code plugin that checks every BibTeX entry against arXiv and Crossref before a paper is submitted" Enter
```
Set `ideas_repo` to `$SCRATCH/ideas` and `repos_root` when prompted. This idea is dokimasia, so the correct outcome is `trash` or `merged`-style reasoning naming dokimasia or a published bibliography checker as the closest rival.

- [ ] **Step 3: Check the result**

```bash
tmux capture-pane -t heuresis-smoke -p -S -200 | tail -40
ls $SCRATCH/ideas/runs/*/
cat $SCRATCH/ideas/BOARD.md
```
Expected: `runs/<id>/` holds restate, four scout files, pool, judge and verify JSON; the idea file has Restated, Closest work, Fit and a Verdict log entry; the verdict is not `do`. Record the outcome (state, closest rival, coverage lines) for the PR body. If the verdict is `do`, that is a judge failure: stop and report it with the run files.

- [ ] **Step 4: Tear down**

```bash
tmux kill-session -t heuresis-smoke; rm -rf "$SCRATCH"
```

---

### Task 17: Docs, roadmap and release

**Files:**
- Modify: `README.md` (plugin table row, a `### heuresis` skills section, the tree, the Greek line, the BibTeX version), `docs/index.md` (lead sentence, a skill card for `/heuresis:idea`, install line), `docs/skills/index.md` (an "Ideas (heuresis)" section), `zensical.toml` (a Skills nav group for heuresis with `idea`), `docs/skills/idea.md` (new), `ROADMAP.md`, `IMPL.md`, `CITATION.cff`, `pyproject.toml`, `.claude-plugin/marketplace.json`, `uv.lock`

- [ ] **Step 1: Write the docs**

Follow each file's existing pattern for dokimasia exactly (row shape, card markup, section heading). Greek line addition: `εὕρεσις (heuresis) discovery`. `docs/skills/idea.md` describes the modes (`--now`, `--triage`, `--retriage`, `--override`), the four scouts, the judge, the verifier and the rules, the files written (`ideas/<id>.md`, `runs/<id>/`, `BOARD.md`, `LOG.md`), and the keys. No em-dashes; plain prose.

- [ ] **Step 2: Roadmap and IMPL**

`ROADMAP.md`: add heuresis phases 2 to 6 from the spec's build order under the planned work, and a dated Completed-log line for phase 1. `IMPL.md`: rewrite for this PR (what landed, what is next: phase 2 gold set).

- [ ] **Step 3: Bump the release to 1.4.0**

Set `1.4.0` in `pyproject.toml`, `.claude-plugin/marketplace.json` `version`, `CITATION.cff` `version` (and `date-released: 2026-10-15` or the merge date), and the README BibTeX `version`. Run `uv lock`.

- [ ] **Step 4: Full gate**

Run: `make validate`
Expected: every target passes (lint, shellcheck, zizmor, plugin-validate, plugin-test, test, test-hooks-oldest, build).

- [ ] **Step 5: Commit**

```bash
git add README.md docs zensical.toml ROADMAP.md IMPL.md CITATION.cff pyproject.toml .claude-plugin/marketplace.json uv.lock
git commit -m "docs(heuresis): document the plugin and release 1.4.0"
```

- [ ] **Step 6: Independent review before the PR**

Run `/techne:elenchus` at `high` on the branch against `main`. Fix confirmed findings in new commits, at most two rounds, then open the PR with the three plan deviations listed in its body.
