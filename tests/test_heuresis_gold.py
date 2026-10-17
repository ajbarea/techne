"""Gold cases: loading, grading one run, the summary."""

from __future__ import annotations

import json
from collections.abc import Mapping
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
        (
            "cases:\n  - {id: a, idea: x, expected_state: trash, match_terms: [t]}\n"
            "  - {id: a, idea: y, expected_state: trash, match_terms: [t]}\n",
            "duplicate",
        ),
        (
            "cases:\n  - {id: a, idea: x, expected_state: maybe, match_terms: [t]}\n",
            "expected_state",
        ),
        (
            "cases:\n  - {id: a, kind: exists, idea: x, expected_state: trash, match_terms: []}\n",
            "match_terms",
        ),
        ("cases:\n  - {id: a, idea: '  ', expected_state: trash, match_terms: [t]}\n", "idea"),
        (
            "cases:\n  - {id: 'Bad Id', idea: x, expected_state: trash, match_terms: [t]}\n",
            "id",
        ),
        ("nothing: here\n", "cases"),
        ("cases:\n  - just a string\n", "not a mapping"),
    ],
)
def test_load_cases_rejects_malformed_files(tmp_path, body, problem):
    with pytest.raises(gold.GoldError, match=problem):
        gold.load_cases(write(tmp_path, body))


def idea_repo(
    tmp: Path, state: str, closest: str, runs: Mapping[str, object] | None
) -> tuple[Path, str]:
    root = tmp / "ideas"
    i = Idea(
        id="2026-10-17-x",
        title="x",
        captured="2026-10-17T00:00:00",
        captured_via="terminal",
        state=state,
        sections={"Idea": "x", "Closest work": closest},
    )
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
    root, idea_id = idea_repo(
        tmp_path,
        "trash",
        "**Closest:** [dokimasia](https://x) (github)\n\n**Also:**\n\n- [bib-verify](u)",
        FULL_RUNS,
    )
    g = gold.grade_run(
        case, 1, root, idea_id, meta={"total_cost_usd": 0.5, "duration_ms": 61000, "num_turns": 9}
    )
    assert (g.state, g.accepted, g.prior_art_hit, g.closest_hit, g.files_ok, g.verified_ok) == (
        "trash",
        True,
        True,
        True,
        True,
        True,
    )
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
        gold.RunGrade(
            "bib-checker", 1, "trash", True, True, True, True, True, cost_usd=0.4, duration_s=60
        ),
        gold.RunGrade(
            "bib-checker", 2, "do", False, False, False, True, True, cost_usd=0.6, duration_s=80
        ),
        gold.RunGrade("teleport", 1, "trash", True, None, None, True, True),
        gold.RunGrade(
            "new-thing", 1, None, False, None, None, False, False, error="timed out after 5s"
        ),
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
