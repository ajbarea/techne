# heuresis phase 2 (evaluation: gold set) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure how often heuresis finds known prior art and avoids calling an existing thing new, with a gold set of ideas whose answers are known, a runner that triages each one in real headless Claude Code sessions, and a report generated from the run artifacts.

**Architecture:** Cases live in `plugins/heuresis/gold/cases.yaml` (public seed set); AJ's own labelled cases live in a second YAML file in his private ideas repository and are passed with another `--cases`. `scripts/heuresis_gold.py` creates a scratch ideas repository per run, captures the case's idea with the heuresis CLI, runs `claude -p "/heuresis:idea --ideas <scratch> --repos <scratch> --triage <id>"`, and grades the resulting idea file with `heuresis.gold` (pure Python, unit-tested). Grades go to `grades.jsonl`; `summary.json` and `summary.md` are generated from it.

**Tech Stack:** Python 3.12, PyYAML, stdlib `subprocess`/`json`, pytest, the `claude` CLI (headless, `--output-format stream-json`).

**Spec:** `specs/2026-10-15-heuresis-design.md` ("Testing and evaluation", build-order phase 2).

## Global Constraints

- Work in the worktree `.claude/worktrees/heuresis-eval` (branch `feat/heuresis-eval`); never the main checkout.
- `requires-python = ">=3.12"`; ruff (line 100, `E F I UP B RUF`), `ty check` clean; run `make lint` and `make test` after the last edit of each task, once each, in the foreground.
- heuresis runtime dependencies stay `pyyaml` only. The runner is repo tooling under `scripts/`, not shipped in the plugin.
- A gold run must never write to AJ's real ideas repository. Every run uses its own scratch repository and passes it explicitly; the runner also snapshots a guard repository before and after each run and stops on any change.
- No secret is read, printed or written by the runner. Keys reach heuresis only through the plugin's own SessionStart hook or the shell environment.
- Every number in the committed report comes from `grades.jsonl` through `report`; nothing is typed by hand.
- Shipped prose follows `plugins/graphe/_shared/plain-prose.md`: no em-dashes, no time estimates, no personal emails or machine paths in published Markdown.
- Commit messages: Conventional Commits, no attribution trailers or session links of any kind.

## Decisions (research behind them)

| Decision | Chosen | Passed over | Why |
|---|---|---|---|
| Harness | headless `claude -p` sessions in AJ's normal environment | `claude plugin eval` behavior cases | In `claude plugin eval`, granted Bash runs under the OS sandbox: writes confined to the workspace, home unreadable, network limited to granted domains (code.claude.com/docs/en/plugin-evals, "Grant tools", "How runs are isolated"). heuresis's CLI builds its venv under the plugin data folder and calls OpenAlex, GitHub and HN, so a triage cannot run there. |
| Which plugin copy runs | the installed `heuresis@techne` by default; `--plugin-dir` for testing a branch | always `--plugin-dir` | Search keys are stored per installed plugin (#152); an inline copy would run keyless. |
| Where the idea goes | `/heuresis:idea --ideas <path> --repos <path>` flags that override the configured folders for one run | a `--settings` file with `pluginConfigs` | The flags are explicit in the prompt and testable; the settings route depends on undocumented keying for inline plugins. The guard repository catches any slip. |
| Grading | deterministic checks on the idea file and run files: state in the accepted set, a match term in Closest work, run files present, closest rival verified | an LLM rubric judge now | The spec calibrates the judge against AJ's labels, which do not exist yet; deterministic checks need no calibration. The judge is added once AJ's labelled cases exist. |
| Plugin behavior evals (`never-verdict-without-retrieval`, `never-do-on-thin-evidence`, `merges-duplicate`) | not in this phase | `claude plugin eval` cases | Same sandbox limit; the rules behind them are unit-tested in `tests/test_heuresis_rules.py` and the gold set exercises them end to end. |

## Review Focus

1. **The skill ignores `--ideas` and writes into the configured ideas repository**: the guard snapshot differs, the runner stops at once with a message naming the guard repository, and no later case runs. Test in Task 3.
2. **A run times out, `claude` exits non-zero, or the stream has no result line**: that run is graded as an error (not accepted, no prior-art hit), recorded, and the next run proceeds. Test in Task 3.
3. **The plugin did not load** (init event lists no `heuresis`, or a `--plugin-dir` path other than the one given): the run is an error with that reason. Test in Task 3.
4. **A malformed cases file** (duplicate id, unknown expected_state, an "exists" case with no match terms, empty idea): `load_cases` raises `GoldError` naming the case. Test in Task 2.
5. **The triage never finished** (idea still `inbox`, or run files missing): not accepted, error "triage did not finish". Test in Task 2.

---

### Task 1: `--ideas` and `--repos` flags on the idea skill

**Files:**
- Modify: `plugins/heuresis/skills/idea/SKILL.md` (argument-hint and the `IDEAS`/`REPOS` paragraph), `docs/skills/idea.md` (modes section)
- Test: `tests/test_heuresis_agents.py`

- [ ] **Step 1: Write the failing test** (append to `tests/test_heuresis_agents.py`)

```python
def test_idea_skill_documents_folder_overrides():
    meta, text = front(PLUGIN / "skills" / "idea" / "SKILL.md")
    assert "--ideas" in meta["argument-hint"] and "--repos" in meta["argument-hint"]
    assert "take precedence" in text
    docs = (ROOT / "docs" / "skills" / "idea.md").read_text()
    assert "--ideas" in docs and "--repos" in docs
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_heuresis_agents.py::test_idea_skill_documents_folder_overrides -v`
Expected: FAIL (`--ideas` not in the argument hint).

- [ ] **Step 3: Edit the skill and docs**

In `SKILL.md` frontmatter, prefix the argument hint: `"[--ideas <path>] [--repos <path>] [--now] <idea text> | --triage <id> | --retriage <id> | --override <id> <state> <reason>"`.

Replace the first body paragraph with:

```markdown
`IDEAS` is `${user_config.ideas_repo}` and `REPOS` is `${user_config.repos_root}`. When the arguments include `--ideas <path>` or `--repos <path>`, those values take precedence for this run: use them as `IDEAS` and `REPOS`, resolve them to absolute paths with `realpath`, and never touch the configured folders. This is how a second ideas repository or the gold-set runner points a run elsewhere. If `IDEAS` or `REPOS` is still empty, stop and tell the user to run `/heuresis:setup`; do not run it yourself.
```

In `docs/skills/idea.md`, add to the modes list: "`--ideas <path>` and `--repos <path>` point one run at another ideas repository and repos folder instead of the configured ones."

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_heuresis_agents.py -v && make frontmatter`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/heuresis/skills/idea/SKILL.md docs/skills/idea.md tests/test_heuresis_agents.py
git commit -m "feat(heuresis): let one idea run point at another ideas repository"
```

---

### Task 2: Gold cases and grading (`heuresis.gold`)

**Files:**
- Create: `plugins/heuresis/heuresis/gold.py`, `tests/test_heuresis_gold.py`, `tests/fixtures/heuresis/gold_cases.yaml`

**Interfaces:**
- Consumes: `store.load`, `store.idea_path`, `store.StoreError`
- Produces:
  - `gold.ACCEPTED: dict[str, frozenset[str]]`
  - `gold.GoldError(Exception)`
  - `gold.PriorArt(name: str, url: str, why: str = "")`, `gold.Case(id, idea, expected_state, match_terms: tuple[str, ...], prior_art: tuple[PriorArt, ...] = (), kind: str = "exists", notes: str = "")` (frozen dataclasses)
  - `gold.load_cases(path: Path) -> list[Case]`
  - `gold.RunGrade` dataclass: `case: str, run: int, state: str | None, accepted: bool, prior_art_hit: bool | None, closest_hit: bool | None, files_ok: bool, verified_ok: bool, error: str = "", cost_usd: float | None = None, duration_s: float | None = None, turns: int | None = None`; `to_dict()`, `from_dict()`
  - `gold.grade_run(case: Case, run: int, ideas_root: Path, idea_id: str, *, error: str = "", meta: dict | None = None) -> RunGrade`
  - `gold.summarize(grades: list[RunGrade], cases: list[Case]) -> dict`
  - `gold.render_markdown(summary: dict) -> str`

- [ ] **Step 1: Write the fixture** `tests/fixtures/heuresis/gold_cases.yaml`

```yaml
cases:
  - id: bib-checker
    kind: exists
    idea: A tool that checks every bibliography entry against arXiv and Crossref before submission.
    expected_state: trash
    match_terms: [dokimasia, bib-verify, crossref]
    prior_art:
      - {name: dokimasia, url: "https://github.com/ajbarea/techne", why: verifies bib entries}
  - id: teleport
    kind: infeasible
    idea: A phone app that teleports packages.
    expected_state: trash
    match_terms: []
  - id: new-thing
    kind: candidate
    idea: Something nobody has built.
    expected_state: do_or_later
    match_terms: []
```

- [ ] **Step 2: Write the failing tests** `tests/test_heuresis_gold.py`

```python
"""Gold cases: loading, grading one run, the summary."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import ROOT
from heuresis import gold, store
from heuresis.model import Idea

FIX = ROOT / "tests" / "fixtures" / "heuresis" / "gold_cases.yaml"


def write(tmp: Path, text: str) -> Path:
    path = tmp / "cases.yaml"
    path.write_text(text)
    return path


def test_load_cases_reads_the_fixture():
    cases = gold.load_cases(FIX)
    assert [c.id for c in cases] == ["bib-checker", "teleport", "new-thing"]
    assert cases[0].match_terms == ("dokimasia", "bib-verify", "crossref")
    assert cases[0].prior_art[0].name == "dokimasia"


@pytest.mark.parametrize(
    ("body", "problem"),
    [
        ("cases:\n  - {id: a, idea: x, expected_state: trash, match_terms: [t]}\n"
         "  - {id: a, idea: y, expected_state: trash, match_terms: [t]}\n", "duplicate"),
        ("cases:\n  - {id: a, idea: x, expected_state: maybe, match_terms: [t]}\n", "expected_state"),
        ("cases:\n  - {id: a, kind: exists, idea: x, expected_state: trash, match_terms: []}\n", "match_terms"),
        ("cases:\n  - {id: a, idea: '  ', expected_state: trash, match_terms: [t]}\n", "idea"),
        ("cases:\n  - {id: 'Bad Id', idea: x, expected_state: trash, match_terms: [t]}\n", "id"),
        ("nothing: here\n", "cases"),
    ],
)
def test_load_cases_rejects_malformed_files(tmp_path, body, problem):
    with pytest.raises(gold.GoldError, match=problem):
        gold.load_cases(write(tmp_path, body))


def idea_repo(tmp: Path, state: str, closest: str, runs: dict[str, object] | None) -> tuple[Path, str]:
    root = tmp / "ideas"
    i = Idea(id="2026-10-17-x", title="x", captured="2026-10-17T00:00:00", captured_via="terminal",
             state=state, sections={"Idea": "x", "Closest work": closest})
    if state in ("do", "building", "shipped"):
        i.type = "tool"
    if state == "later":
        i.revisit = "2027-01-01"
    store.save(root, i)
    run = root / "runs" / i.id
    run.mkdir(parents=True)
    for name, data in (runs or {}).items():
        (run / f"{name}.json").write_text(json.dumps(data))
    return root, i.id


FULL_RUNS = {
    "restate": {"restated": "x", "queries": ["q"]},
    "pool": {"records": [], "coverage": [], "queries": {}},
    "judge": {"closest": {"ref": "r1"}},
    "verify": {"r1": {"ok": True, "reason": ""}},
}


def test_grade_run_accepts_trash_with_prior_art_in_closest(tmp_path):
    case = gold.load_cases(FIX)[0]
    root, idea_id = idea_repo(tmp_path, "trash",
                              "**Closest:** [dokimasia](https://x) (github)\n\n**Also:**\n\n- [bib-verify](u)", FULL_RUNS)
    g = gold.grade_run(case, 1, root, idea_id, meta={"total_cost_usd": 0.5, "duration_ms": 61000, "num_turns": 9})
    assert (g.state, g.accepted, g.prior_art_hit, g.closest_hit, g.files_ok, g.verified_ok) == (
        "trash", True, True, True, True, True)
    assert (g.cost_usd, g.duration_s, g.turns) == (0.5, 61.0, 9)


def test_grade_run_do_on_an_existing_thing_is_not_accepted(tmp_path):
    case = gold.load_cases(FIX)[0]
    root, idea_id = idea_repo(tmp_path, "do", "**Closest:** none verified.", FULL_RUNS)
    g = gold.grade_run(case, 1, root, idea_id)
    assert (g.accepted, g.prior_art_hit, g.closest_hit) == (False, False, False)


def test_grade_run_inbox_means_triage_did_not_finish(tmp_path):
    case = gold.load_cases(FIX)[0]
    root, idea_id = idea_repo(tmp_path, "inbox", "", None)
    g = gold.grade_run(case, 1, root, idea_id)
    assert not g.accepted and not g.files_ok and g.error == "triage did not finish"


def test_grade_run_records_a_runner_error_without_reading_files(tmp_path):
    case = gold.load_cases(FIX)[0]
    g = gold.grade_run(case, 2, tmp_path / "missing", "2026-10-17-x", error="timed out after 5s")
    assert (g.state, g.accepted, g.error) == (None, False, "timed out after 5s")


def test_cases_without_match_terms_have_no_prior_art_measure(tmp_path):
    case = gold.load_cases(FIX)[1]
    root, idea_id = idea_repo(tmp_path, "trash", "**Closest:** none verified.", FULL_RUNS)
    g = gold.grade_run(case, 1, root, idea_id)
    assert g.accepted and g.prior_art_hit is None and g.closest_hit is None


def test_summarize_and_render(tmp_path):
    cases = gold.load_cases(FIX)
    grades = [
        gold.RunGrade("bib-checker", 1, "trash", True, True, True, True, True, cost_usd=0.4, duration_s=60),
        gold.RunGrade("bib-checker", 2, "do", False, False, False, True, True, cost_usd=0.6, duration_s=80),
        gold.RunGrade("teleport", 1, "trash", True, None, None, True, True),
        gold.RunGrade("new-thing", 1, None, False, None, None, False, False, error="timed out after 5s"),
    ]
    s = gold.summarize(grades, cases)
    assert s["runs"] == 4 and s["errors"] == 1
    assert s["agreement"] == pytest.approx(2 / 4)
    assert s["prior_art_recall"] == pytest.approx(1 / 2)
    assert s["do_on_existing"] == 1
    bib = next(c for c in s["cases"] if c["case"] == "bib-checker")
    assert bib["states"] == ["trash", "do"] and bib["distinct_states"] == 2
    md = gold.render_markdown(s)
    assert "| bib-checker |" in md and "Prior-art recall" in md
    assert "—" not in md


def test_run_grade_round_trips():
    g = gold.RunGrade("a", 1, "trash", True, None, None, True, False, error="", cost_usd=None)
    assert gold.RunGrade.from_dict(json.loads(json.dumps(g.to_dict()))) == g
```

- [ ] **Step 3: Run them to verify they fail**

Run: `uv run pytest tests/test_heuresis_gold.py -v`
Expected: FAIL (`cannot import name 'gold'`).

- [ ] **Step 4: Implement `plugins/heuresis/heuresis/gold.py`**

```python
"""Gold set: cases with known answers, grading of one triage run, and the summary report."""

from __future__ import annotations

import json
import re
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

from heuresis import store

# The states a run may file for each expected label. An existing thing filed as trash or merged
# is right; "later" cases have close prior art with a plausible difference, so trash also agrees.
ACCEPTED: dict[str, frozenset[str]] = {
    "trash": frozenset({"trash", "merged"}),
    "later": frozenset({"later", "trash", "merged"}),
    "do_or_later": frozenset({"do", "later"}),
}
# Labels whose cases describe something that already exists; filing one as "do" is the failure
# the gold set measures first.
EXISTING = frozenset({"trash", "later"})
CASE_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
RUN_FILES = ("restate", "pool", "judge", "verify")


class GoldError(Exception):
    """A cases file that cannot be used."""


@dataclass(frozen=True)
class PriorArt:
    name: str
    url: str
    why: str = ""


@dataclass(frozen=True)
class Case:
    id: str
    idea: str
    expected_state: str
    match_terms: tuple[str, ...]
    prior_art: tuple[PriorArt, ...] = ()
    kind: str = "exists"
    notes: str = ""


def load_cases(path: Path) -> list[Case]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rows = data.get("cases") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise GoldError(f"{path}: no cases list")
    cases: list[Case] = []
    seen: set[str] = set()
    for row in rows:
        cid = str(row.get("id", ""))
        if not CASE_ID.fullmatch(cid):
            raise GoldError(f"{path}: case id {cid!r} is not lowercase kebab-case")
        if cid in seen:
            raise GoldError(f"{path}: duplicate case id {cid}")
        seen.add(cid)
        idea = str(row.get("idea") or "").strip()
        if not idea:
            raise GoldError(f"{path}: case {cid} has an empty idea")
        expected = str(row.get("expected_state", ""))
        if expected not in ACCEPTED:
            raise GoldError(f"{path}: case {cid} expected_state {expected!r} is not one of "
                            + ", ".join(ACCEPTED))
        kind = str(row.get("kind") or "exists")
        terms = tuple(str(t).lower() for t in row.get("match_terms") or [])
        if kind == "exists" and not terms:
            raise GoldError(f"{path}: case {cid} describes an existing thing but has no match_terms")
        prior = tuple(
            PriorArt(str(p["name"]), str(p["url"]), str(p.get("why", "")))
            for p in row.get("prior_art") or []
        )
        cases.append(Case(cid, idea, expected, terms, prior, kind, str(row.get("notes", ""))))
    return cases


@dataclass
class RunGrade:
    case: str
    run: int
    state: str | None
    accepted: bool
    prior_art_hit: bool | None
    closest_hit: bool | None
    files_ok: bool
    verified_ok: bool
    error: str = ""
    cost_usd: float | None = None
    duration_s: float | None = None
    turns: int | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> RunGrade:
        return cls(**{k: data[k] for k in cls.__dataclass_fields__ if k in data})


def _meta(meta: dict | None) -> dict:
    meta = meta or {}
    ms = meta.get("duration_ms")
    return {
        "cost_usd": meta.get("total_cost_usd"),
        "duration_s": round(ms / 1000, 1) if isinstance(ms, int | float) else None,
        "turns": meta.get("num_turns"),
    }


def grade_run(
    case: Case, run: int, ideas_root: Path, idea_id: str, *, error: str = "",
    meta: dict | None = None,
) -> RunGrade:
    extra = _meta(meta)
    if error:
        return RunGrade(case.id, run, None, False, None, None, False, False, error, **extra)
    try:
        idea = store.load(store.idea_path(ideas_root, idea_id))
    except (OSError, store.StoreError) as exc:
        return RunGrade(case.id, run, None, False, None, None, False, False,
                        f"idea file unreadable: {exc}", **extra)
    run_dir = ideas_root / "runs" / idea_id
    files_ok = all((run_dir / f"{name}.json").is_file() for name in RUN_FILES)
    closest = idea.sections.get("Closest work", "").lower()
    first = closest.split("**also:**", 1)[0]
    measured = bool(case.match_terms)
    prior_hit = any(t in closest for t in case.match_terms) if measured else None
    closest_hit = any(t in first for t in case.match_terms) if measured else None
    verified = False
    if files_ok:
        try:
            judge = json.loads((run_dir / "judge.json").read_text())
            checks = json.loads((run_dir / "verify.json").read_text())
            ref = (judge.get("closest") or {}).get("ref")
            verified = ref is None or (checks.get(ref) or {}).get("ok") is True
        except (OSError, ValueError, AttributeError):
            verified = False
    finished = idea.state != "inbox" and files_ok
    return RunGrade(
        case.id, run, idea.state,
        finished and idea.state in ACCEPTED[case.expected_state],
        prior_hit if finished else (False if measured else None),
        closest_hit if finished else (False if measured else None),
        files_ok, verified, "" if finished else "triage did not finish", **extra,
    )


def _rate(values: list[bool]) -> float | None:
    return sum(values) / len(values) if values else None


def summarize(grades: list[RunGrade], cases: list[Case]) -> dict:
    by_case = {c.id: c for c in cases}
    rows = []
    for case in cases:
        mine = [g for g in grades if g.case == case.id]
        states = [g.state or "error" for g in mine]
        rows.append({
            "case": case.id,
            "expected": case.expected_state,
            "runs": len(mine),
            "states": states,
            "distinct_states": len(set(states)),
            "agreement": _rate([g.accepted for g in mine]),
            "prior_art_recall": _rate([bool(g.prior_art_hit) for g in mine if g.prior_art_hit is not None]),
            "closest_recall": _rate([bool(g.closest_hit) for g in mine if g.closest_hit is not None]),
            "errors": sum(1 for g in mine if g.error),
        })
    costs = [g.cost_usd for g in grades if g.cost_usd is not None]
    durations = [g.duration_s for g in grades if g.duration_s is not None]
    return {
        "runs": len(grades),
        "errors": sum(1 for g in grades if g.error),
        "agreement": _rate([g.accepted for g in grades]),
        "prior_art_recall": _rate([bool(g.prior_art_hit) for g in grades if g.prior_art_hit is not None]),
        "closest_recall": _rate([bool(g.closest_hit) for g in grades if g.closest_hit is not None]),
        "do_on_existing": sum(
            1 for g in grades if g.state == "do" and by_case[g.case].expected_state in EXISTING
        ),
        "cost_usd_total": round(sum(costs), 2) if costs else None,
        "duration_s_median": statistics.median(durations) if durations else None,
        "cases": rows,
    }


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def render_markdown(summary: dict) -> str:
    lines = [
        "# heuresis gold-set results",
        "",
        "Generated by `scripts/heuresis_gold.py report` from `grades.jsonl`; do not edit by hand.",
        "",
        f"- Runs: {summary['runs']} ({summary['errors']} errors)",
        f"- Verdict agreement: {_pct(summary['agreement'])}",
        f"- Prior-art recall (named anywhere in Closest work): {_pct(summary['prior_art_recall'])}",
        f"- Closest-rival recall (named as the closest): {_pct(summary['closest_recall'])}",
        f"- Existing things filed as do: {summary['do_on_existing']}",
        f"- Total cost (client estimate): {summary['cost_usd_total']}",
        f"- Median run time (s): {summary['duration_s_median']}",
        "",
        "| Case | Expected | States by run | Agreement | Prior-art recall | Closest recall | Errors |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in summary["cases"]:
        lines.append(
            f"| {row['case']} | {row['expected']} | {', '.join(row['states']) or 'none'} | "
            f"{_pct(row['agreement'])} | {_pct(row['prior_art_recall'])} | "
            f"{_pct(row['closest_recall'])} | {row['errors']} |"
        )
    return "\n".join(lines) + "\n"
```

Wrap any line over 100 columns with `uv run ruff format plugins/ tests/`.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_heuresis_gold.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add plugins/heuresis/heuresis/gold.py tests/test_heuresis_gold.py tests/fixtures/heuresis/gold_cases.yaml
git commit -m "feat(heuresis): grade a triage run against a gold case"
```

---

### Task 3: The runner (`scripts/heuresis_gold.py`)

**Files:**
- Create: `scripts/heuresis_gold.py`, `tests/test_heuresis_gold_runner.py`, `tests/fixtures/heuresis/fake_claude.py`
- Modify: `tests/conftest.py` (add `GOLD_RUNNER`)

**Interfaces:**
- Consumes: `heuresis.gold` (Task 2); the heuresis CLI (`init`, `capture --text -`)
- Produces: CLI `heuresis_gold.py run [--cases FILE]... [--runs N] [--case GLOB]... [--out DIR] [--plugin-dir DIR] [--guard-repo DIR] [--timeout SECONDS] [--model NAME]` and `heuresis_gold.py report RESULTS_DIR`; module functions `parse_stream(text: str) -> tuple[dict | None, dict | None]` (init event, result event), `snapshot(repo: Path) -> str`, `main(argv: list[str] | None = None) -> int`.

Layout of a results directory: `<out>/<UTC timestamp>/` with `work/<case>-<run>/` (scratch ideas repo and repos folder), `logs/<case>-<run>.jsonl` (the stream), `grades.jsonl`, `summary.json`, `summary.md`.

- [ ] **Step 1: Write the fake `claude`** `tests/fixtures/heuresis/fake_claude.py`

```python
#!/usr/bin/env python3
"""Stand-in for `claude -p` in runner tests. Behaviour comes from FAKE_CLAUDE_MODE."""

import json
import os
import re
import sys
import time
from pathlib import Path

mode = os.environ.get("FAKE_CLAUDE_MODE", "trash")
prompt = sys.argv[sys.argv.index("-p") + 1]
ideas = Path(re.search(r"--ideas (\S+)", prompt).group(1))
idea_id = re.search(r"--triage (\S+)", prompt).group(1)
plugins = [{"name": "heuresis", "path": "/plugins/heuresis"}]
if mode == "no-plugin":
    plugins = []
print(json.dumps({"type": "system", "subtype": "init", "plugins": plugins}), flush=True)
if mode == "sleep":
    time.sleep(30)
if mode == "guard":
    guard = Path(os.environ["FAKE_CLAUDE_GUARD"])
    (guard / "ideas" / "stray.md").write_text("written by mistake")
if mode in ("trash", "guard"):
    sys.path.insert(0, os.environ["HEURESIS_SRC"])
    from heuresis import store

    path = store.idea_path(ideas, idea_id)
    idea = store.load(path)
    idea.state = "trash"
    idea.sections["Closest work"] = "**Closest:** [dokimasia](https://x) (github)"
    store.save(ideas, idea)
    run = ideas / "runs" / idea_id
    run.mkdir(parents=True, exist_ok=True)
    for name, data in {
        "restate": {"restated": "x"}, "pool": {"records": []},
        "judge": {"closest": {"ref": "r1"}}, "verify": {"r1": {"ok": True}},
    }.items():
        (run / f"{name}.json").write_text(json.dumps(data))
if mode == "crash":
    sys.exit(3)
print(json.dumps({"type": "result", "subtype": "success", "is_error": False,
                  "total_cost_usd": 0.25, "duration_ms": 1000, "num_turns": 4}), flush=True)
```

- [ ] **Step 2: Write the failing tests** `tests/test_heuresis_gold_runner.py`

```python
"""The gold runner, driven with a fake claude on PATH."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from conftest import GOLD_RUNNER, ROOT, _load

FAKE = ROOT / "tests" / "fixtures" / "heuresis" / "fake_claude.py"
CASES = ROOT / "tests" / "fixtures" / "heuresis" / "gold_cases.yaml"
r = _load("heuresis_gold", GOLD_RUNNER)


@pytest.fixture
def fake(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    shim = bindir / "claude"
    shim.write_text(f"#!/bin/sh\nexec python3 {FAKE} \"$@\"\n")
    shim.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("HEURESIS_SRC", str(ROOT / "plugins" / "heuresis"))
    return tmp_path


def guard_repo(tmp: Path) -> Path:
    repo = tmp / "real-ideas"
    (repo / "ideas").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    return repo


def results(out: Path) -> Path:
    (only,) = [p for p in out.iterdir() if p.is_dir()]
    return only


def test_parse_stream_finds_init_and_result():
    text = '{"type":"system","subtype":"init","plugins":[]}\nnot json\n{"type":"result","num_turns":2}\n'
    init, result = r.parse_stream(text)
    assert init["subtype"] == "init" and result["num_turns"] == 2
    assert r.parse_stream("") == (None, None)


def test_run_grades_each_case_and_writes_the_report(fake, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "trash")
    out = fake / "out"
    rc = r.main(["run", "--cases", str(CASES), "--case", "bib-checker", "--runs", "2",
                 "--out", str(out), "--guard-repo", str(guard_repo(fake))])
    assert rc == 0
    res = results(out)
    grades = [json.loads(line) for line in (res / "grades.jsonl").read_text().splitlines()]
    assert [(g["case"], g["run"], g["state"], g["accepted"], g["prior_art_hit"]) for g in grades] == [
        ("bib-checker", 1, "trash", True, True), ("bib-checker", 2, "trash", True, True)]
    assert grades[0]["cost_usd"] == 0.25
    assert "| bib-checker |" in (res / "summary.md").read_text()
    assert json.loads((res / "summary.json").read_text())["runs"] == 2


@pytest.mark.parametrize(("mode", "error"), [
    ("crash", "claude exited 3"), ("no-plugin", "heuresis plugin did not load"),
])
def test_failed_runs_are_recorded_and_the_next_case_still_runs(fake, monkeypatch, mode, error):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", mode)
    out = fake / "out"
    assert r.main(["run", "--cases", str(CASES), "--case", "bib-checker", "--case", "teleport",
                   "--runs", "1", "--out", str(out)]) == 0
    grades = [json.loads(x) for x in (results(out) / "grades.jsonl").read_text().splitlines()]
    assert [g["case"] for g in grades] == ["bib-checker", "teleport"]
    assert all(error in g["error"] and not g["accepted"] for g in grades)


def test_timeout_is_an_error(fake, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "sleep")
    out = fake / "out"
    assert r.main(["run", "--cases", str(CASES), "--case", "bib-checker", "--runs", "1",
                   "--timeout", "2", "--out", str(out)]) == 0
    (g,) = [json.loads(x) for x in (results(out) / "grades.jsonl").read_text().splitlines()]
    assert g["error"] == "timed out after 2s"


def test_a_write_to_the_guard_repo_stops_everything(fake, monkeypatch, capsys):
    guard = guard_repo(fake)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "guard")
    monkeypatch.setenv("FAKE_CLAUDE_GUARD", str(guard))
    out = fake / "out"
    rc = r.main(["run", "--cases", str(CASES), "--case", "bib-checker", "--case", "teleport",
                 "--runs", "1", "--out", str(out), "--guard-repo", str(guard)])
    assert rc == 1
    assert "guard repository" in capsys.readouterr().err
    lines = (results(out) / "grades.jsonl").read_text().splitlines()
    assert len(lines) == 0


def test_report_regenerates_the_summary(fake, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "trash")
    out = fake / "out"
    r.main(["run", "--cases", str(CASES), "--case", "bib-checker", "--runs", "1", "--out", str(out)])
    res = results(out)
    (res / "summary.md").unlink()
    assert r.main(["report", str(res)]) == 0
    assert (res / "summary.md").is_file()


def test_missing_claude_is_a_clear_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PATH", str(tmp_path))
    assert r.main(["run", "--cases", str(CASES), "--out", str(tmp_path / "o")]) == 2
    assert "claude is not on PATH" in capsys.readouterr().err
```

Add to `tests/conftest.py` after `SCHOLARLY_SCRIPT`: `GOLD_RUNNER = ROOT / "scripts" / "heuresis_gold.py"`.

- [ ] **Step 3: Run them to verify they fail**

Run: `uv run pytest tests/test_heuresis_gold_runner.py -v`
Expected: FAIL (runner file missing).

- [ ] **Step 4: Implement `scripts/heuresis_gold.py`**

```python
#!/usr/bin/env python3
"""Run the heuresis gold set: one headless Claude Code triage per case and run, graded from the
files it writes. Uses your Claude plan; never touches your real ideas repository.

Usage:
  heuresis_gold.py run [--cases FILE]... [--runs N] [--case GLOB]... [--out DIR]
                       [--plugin-dir DIR] [--guard-repo DIR] [--timeout SECONDS] [--model NAME]
  heuresis_gold.py report RESULTS_DIR
"""

from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "heuresis"
sys.path.insert(0, str(PLUGIN))
from heuresis import gold  # noqa: E402  # ty: ignore[unresolved-import]

DEFAULT_CASES = PLUGIN / "gold" / "cases.yaml"
# A full triage took about two minutes in the phase 1 live run; twenty minutes leaves room for
# slow sources and retries without letting a stuck session hold the whole set.
DEFAULT_TIMEOUT = 1200


class GuardTripped(Exception):
    """A run changed the guard repository."""


def heuresis(*args: str, stdin: str | None = None) -> str:
    done = subprocess.run(
        ["uv", "run", "--quiet", "--directory", str(PLUGIN), "python", "-m", "heuresis", *args],
        input=stdin, capture_output=True, text=True, check=False,
    )
    if done.returncode:
        raise RuntimeError(f"heuresis {args[0]} failed: {done.stderr.strip()}")
    return done.stdout.strip()


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          check=True).stdout


def snapshot(repo: Path) -> str:
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True,
                          text=True, check=False).stdout.strip()
    return head + "\n" + git(repo, "status", "--porcelain", "--untracked-files=all")


def parse_stream(text: str) -> tuple[dict | None, dict | None]:
    init = result = None
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") == "system" and event.get("subtype") == "init":
            init = event
        elif event.get("type") == "result":
            result = event
    return init, result


def prepare(work: Path, case: gold.Case) -> tuple[Path, Path, str]:
    repos, ideas = work / "repos", work / "ideas"
    repos.mkdir(parents=True)
    heuresis("init", str(ideas), "--repos-root", str(repos), "--techne-toml", str(work / "none.toml"))
    for key, value in (("user.email", "gold@example.com"), ("user.name", "gold"),
                       ("commit.gpgsign", "false")):
        git(ideas, "config", key, value)
    git(ideas, "add", "-A")
    git(ideas, "commit", "-qm", "init")
    idea_id = heuresis("capture", "--ideas", str(ideas), "--text", "-", stdin=case.idea)
    return ideas, repos, idea_id.splitlines()[-1]


def triage(ideas: Path, repos: Path, idea_id: str, log: Path, args) -> tuple[str, dict | None]:
    prompt = f"/heuresis:idea --ideas {ideas} --repos {repos} --triage {idea_id}"
    cmd = ["claude", "-p", prompt, "--output-format", "stream-json", "--verbose",
           "--permission-mode", "bypassPermissions"]
    if args.plugin_dir:
        cmd += ["--plugin-dir", str(args.plugin_dir)]
    if args.model:
        cmd += ["--model", args.model]
    try:
        done = subprocess.run(cmd, cwd=ideas.parent, capture_output=True, text=True,
                              timeout=args.timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        log.write_text(exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or ""))
        return f"timed out after {args.timeout}s", None
    log.write_text(done.stdout)
    init, result = parse_stream(done.stdout)
    names = [(p.get("name"), p.get("path")) for p in (init or {}).get("plugins", [])]
    wanted = [n for n in names if n[0] == "heuresis"]
    if not wanted or (args.plugin_dir and str(Path(args.plugin_dir).resolve()) not in
                      {str(Path(p).resolve()) for _, p in wanted if p}):
        return "heuresis plugin did not load", result
    if done.returncode:
        return f"claude exited {done.returncode}", result
    if result is None:
        return "no result in the stream", None
    if result.get("is_error"):
        return f"claude reported an error: {str(result.get('result', ''))[:200]}", result
    return "", result


def selected(cases: list[gold.Case], globs: list[str]) -> list[gold.Case]:
    return [c for c in cases if not globs or any(fnmatch.fnmatch(c.id, g) for g in globs)]


def write_report(res: Path, cases: list[gold.Case]) -> None:
    grades = [gold.RunGrade.from_dict(json.loads(line))
              for line in (res / "grades.jsonl").read_text().splitlines() if line.strip()]
    summary = gold.summarize(grades, [c for c in cases if any(g.case == c.id for g in grades)])
    (res / "summary.json").write_text(json.dumps(summary, indent=2))
    (res / "summary.md").write_text(gold.render_markdown(summary))


def run(args) -> int:
    if shutil.which("claude") is None:
        print("heuresis_gold: claude is not on PATH", file=sys.stderr)
        return 2
    cases = selected([c for f in args.cases for c in gold.load_cases(f)], args.case)
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    res = args.out / stamp
    (res / "logs").mkdir(parents=True)
    (res / "grades.jsonl").write_text("")
    files = [str(Path(f).resolve()) for f in args.cases]
    (res / "cases.json").write_text(json.dumps({"ids": [c.id for c in cases], "files": files}))
    guard = args.guard_repo
    before = snapshot(guard) if guard else ""
    try:
        for case in cases:
            for n in range(1, args.runs + 1):
                work = res / "work" / f"{case.id}-{n}"
                ideas, repos, idea_id = prepare(work, case)
                error, result = triage(ideas, repos, idea_id, res / "logs" / f"{case.id}-{n}.jsonl", args)
                if guard and snapshot(guard) != before:
                    raise GuardTripped(f"run {case.id}-{n} changed the guard repository {guard}; "
                                       "stopping. Inspect it with git status before anything else.")
                grade = gold.grade_run(case, n, ideas, idea_id, error=error, meta=result)
                with (res / "grades.jsonl").open("a") as fh:
                    fh.write(json.dumps(grade.to_dict()) + "\n")
                print(f"{case.id} run {n}: {grade.state or 'error'}"
                      f"{' (' + grade.error + ')' if grade.error else ''}", flush=True)
    except GuardTripped as exc:
        print(f"heuresis_gold: {exc}", file=sys.stderr)
        return 1
    write_report(res, cases)
    print(res / "summary.md")
    return 0


def report(args) -> int:
    meta = json.loads((args.results / "cases.json").read_text())
    files = [Path(f) for f in meta["files"]] + list(args.cases)
    pool = {c.id: c for f in files if f.is_file() for c in gold.load_cases(f)}
    write_report(args.results, [pool[i] for i in meta["ids"] if i in pool])
    print(args.results / "summary.md")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="heuresis_gold.py")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("run")
    p.add_argument("--cases", type=Path, action="append")
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--case", action="append", default=[])
    p.add_argument("--out", type=Path, default=ROOT / ".heuresis-gold")
    p.add_argument("--plugin-dir", type=Path)
    p.add_argument("--guard-repo", type=Path)
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    p.add_argument("--model")
    p = sub.add_parser("report")
    p.add_argument("results", type=Path)
    p.add_argument("--cases", type=Path, action="append", default=[])
    args = parser.parse_args(argv)
    if args.command == "run":
        args.cases = args.cases or [DEFAULT_CASES]
        return run(args)
    return report(args)


if __name__ == "__main__":
    sys.exit(main())
```

Notes for the implementer:
- `report` reloads the cases from the files recorded in `cases.json` by the run, plus any extra `--cases`.
- A row in the cases file that is not a mapping must raise `GoldError` too (Task 2's loader): check `isinstance(row, dict)` first.
- The guard test expects zero grade lines: the snapshot check runs before the grade is written. Keep that order.
- `datetime.UTC` needs Python 3.11+ (fine at 3.12).

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_heuresis_gold_runner.py tests/test_heuresis_gold.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/heuresis_gold.py tests/test_heuresis_gold_runner.py tests/fixtures/heuresis/fake_claude.py tests/conftest.py
git commit -m "feat(heuresis): add the gold-set runner"
```

---

### Task 4: Make target, ignore rule and docs

**Files:**
- Modify: `Makefile` (`.PHONY` and a `heuresis-gold` target), `.gitignore` (`.heuresis-gold/`), `docs/skills/idea.md` (an "Evaluating heuresis" section), `plugins/heuresis/AGENTS.md` (one line pointing at the section)
- Test: `tests/test_heuresis_gold_runner.py` (add one test)

- [ ] **Step 1: Write the failing test** (append)

```python
def test_make_target_and_ignore_rule_exist():
    makefile = (ROOT / "Makefile").read_text()
    assert "heuresis-gold:" in makefile and "scripts/heuresis_gold.py run" in makefile
    assert ".heuresis-gold/" in (ROOT / ".gitignore").read_text()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_heuresis_gold_runner.py::test_make_target_and_ignore_rule_exist -v`
Expected: FAIL.

- [ ] **Step 3: Add the target, the ignore rule and the docs**

Makefile, after `evals-bash` (add `heuresis-gold` to `.PHONY`):

```make
# The heuresis gold set runs real triages on your own login, so it draws on your plan's usage and
# stays out of validate. GOLD_ARGS passes runner flags, e.g. GOLD_ARGS="--runs 1 --case bib-*".
# GUARD names your real ideas repository; the runner stops if any run changes it.
GUARD ?=
heuresis-gold:          ## Run the heuresis gold set (real triages; uses your plan)
	@uv run python scripts/heuresis_gold.py run $(if $(GUARD),--guard-repo $(GUARD)) $(GOLD_ARGS)
```

`.gitignore`: add under the evals block:

```
# heuresis gold-set runs (scratch repos, logs, grades)
.heuresis-gold/
```

`docs/skills/idea.md`, new section "Evaluating heuresis":

```markdown
## Evaluating heuresis

`make heuresis-gold GUARD=<your ideas repository>` triages every case in `plugins/heuresis/gold/cases.yaml` three times in headless Claude Code sessions, each in its own scratch ideas repository, and writes `grades.jsonl`, `summary.json` and `summary.md` under `.heuresis-gold/<time>/`. It uses your Claude plan. The runner stops if any run changes the repository named by `GUARD`.

Each case gives an idea, the state it should get, and terms that name its known prior art. A run agrees when its state is one the case accepts; it finds the prior art when a term appears in Closest work. The summary also counts existing things filed as `do`, the failure the set is built to catch.

To add your own labelled ideas, keep a second cases file in your ideas repository and pass it with `GOLD_ARGS="--cases <file>"`.
```

`plugins/heuresis/AGENTS.md`: add one line at the end: "To measure triage quality, see "Evaluating heuresis" on the idea skill's docs page."

- [ ] **Step 4: Run the tests and the docs build**

Run: `uv run pytest tests/test_heuresis_gold_runner.py -v && make build`
Expected: PASS; docs build clean.

- [ ] **Step 5: Commit**

```bash
git add Makefile .gitignore docs/skills/idea.md plugins/heuresis/AGENTS.md tests/test_heuresis_gold_runner.py
git commit -m "feat(heuresis): make heuresis-gold and how to read its results"
```

---

### Task 5: The seed gold set

**Files:**
- Create: `plugins/heuresis/gold/cases.yaml`
- Test: `tests/test_heuresis_gold.py` (add one test)

The controller supplies a researched draft (20 cases: 16 that already exist, 2 "do" candidates, 2 infeasible) with prior-art URLs. Every prior-art URL must be re-opened and confirmed to describe what the case claims before it is committed; drop or replace any that fail.

- [ ] **Step 1: Write the failing test** (append to `tests/test_heuresis_gold.py`)

```python
def test_seed_set_is_valid_and_mostly_existing_things():
    cases = gold.load_cases(ROOT / "plugins" / "heuresis" / "gold" / "cases.yaml")
    assert len(cases) >= 20
    assert sum(c.expected_state in gold.EXISTING for c in cases) >= 16
    assert all(p.url.startswith("https://") for c in cases for p in c.prior_art)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_heuresis_gold.py::test_seed_set_is_valid_and_mostly_existing_things -v`
Expected: FAIL (file missing).

- [ ] **Step 3: Verify and write the cases**

For each case in the draft: WebFetch every prior-art URL and confirm it describes the claimed product or paper; check the idea text does not name the prior art; check every `match_terms` entry is lowercase and would appear in a triage that names that prior art (a product name, repo slug, distinctive title word, or domain). Write the verified cases to `plugins/heuresis/gold/cases.yaml` with `kind` set to `exists`, `candidate` or `infeasible`. Record in the task report which URLs were dropped and why.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_heuresis_gold.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/heuresis/gold/cases.yaml tests/test_heuresis_gold.py
git commit -m "feat(heuresis): add the seed gold set"
```

---

### Task 6: First baseline run and the committed report

Controller-run (uses AJ's plan; not a subagent task).

- [ ] **Step 1: Smoke one case once**

Run: `make heuresis-gold GUARD=$HOME/ajsoftworks/ideas GOLD_ARGS="--runs 1 --case <one exists case>"`
Expected: one grade line, the idea filed, no guard trip. If the plugin did not load or the run errors, fix before the full set.

- [ ] **Step 2: Run the full set**

Run: `make heuresis-gold GUARD=$HOME/ajsoftworks/ideas` (20 cases x 3 runs). Run it within a usage window; if a limit interrupts it, rerun the remaining cases with `--case` and combine the `grades.jsonl` files into one results directory, then `report`.

- [ ] **Step 3: Commit the generated report**

Copy the run's `summary.md` to `plugins/heuresis/gold/RESULTS.md` unchanged (it carries its own "generated" line), and add a dated Completed line to `ROADMAP.md` that states phase 2's status and points at `RESULTS.md` without restating any figure. Update `IMPL.md`.

```bash
git add plugins/heuresis/gold/RESULTS.md ROADMAP.md IMPL.md
git commit -m "docs(heuresis): first gold-set baseline"
```
