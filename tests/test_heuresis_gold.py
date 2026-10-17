"""Gold cases: loading, grading one run, the summary."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import pytest
from conftest import ROOT
from heuresis import cli, gold, render, store
from heuresis.model import FACETS, Idea

PRIOR = "cases:\n  - {id: a, idea: x, expected_state: trash, match_terms: [t], "
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
        (
            "cases:\n  - {id: a, idea: x, expected_state: trash, match_terms: crossref}\n",
            "match_terms",
        ),
        ("cases:\n  - {id: a, idea: x, expected_state: trash, match_terms: ''}\n", "match_terms"),
        ("cases:\n  - {id: a, idea: x, expected_state: trash, match_terms: ['']}\n", "match_terms"),
        (
            "cases:\n  - {id: a, idea: x, expected_state: trash, match_terms: [' t']}\n",
            "match_terms",
        ),
        ("cases:\n  - {id: a, idea: x, expected_state: trash, match_terms: [3]}\n", "match_terms"),
        (
            PRIOR + "prior_art: p}\n",
            "prior_art",
        ),
        (
            PRIOR + "prior_art: [p]}\n",
            "prior_art",
        ),
        (
            PRIOR + "prior_art: [{name: n}]}\n",
            "prior_art",
        ),
        (
            PRIOR + "prior_art: [{name: '', url: u}]}\n",
            "prior_art",
        ),
        (
            "cases:\n  - {id: a, kind: exist, idea: x, expected_state: trash, match_terms: [t]}\n",
            "kind",
        ),
        (
            "cases:\n  - {id: a, kind: '', idea: x, expected_state: trash, match_terms: [t]}\n",
            "kind",
        ),
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


def rec(ref: str, title: str, url: str = "https://u.example") -> dict:
    return {
        "ref": ref,
        "title": title,
        "url": url,
        "source": "github",
        "kind": "repo",
        "evidence_url": f"https://api.example/{ref}",
    }


def run_files(
    records: list[dict],
    closest: str | None,
    others: tuple[str, ...] = (),
    ok: tuple[str, ...] = (),
    differs: str = "",
) -> dict:
    """The four run files in the shapes the CLI writes; ok lists the refs that verified."""
    judge = {
        "closest": {"ref": closest, "quote": "q", "differs": dict.fromkeys(FACETS, differs)},
        "others": [{"ref": o, "quote": "q", "differs": differs} for o in others],
    }
    return {
        "restate": {"restated": "x", "queries": ["q"]},
        "pool": {"records": records, "coverage": [], "queries": {}},
        "judge": judge,
        "verify": {
            r["ref"]: {
                "ok": r["ref"] in ok,
                "reason": "",
                "quote": "q",
                **{k: r.get(k, "") for k in cli.BOUND},
            }
            for r in records
        },
    }


def section(files: dict, dropped: frozenset[str] = frozenset()) -> str:
    records = {r["ref"]: r for r in files["pool"]["records"]}
    return render.closest_section(files["judge"], records, set(dropped))


FULL_RUNS = run_files([rec("r1", "Zotero Connector", "https://zotero.org")], "r1", ok=("r1",))


def test_grade_run_accepts_trash_with_prior_art_in_closest(tmp_path):
    case = gold.load_cases(FIX)[0]
    files = run_files(
        [rec("r1", "dokimasia", "https://github.com/ajbarea/techne"), rec("r2", "bib-verify")],
        "r1",
        ("r2",),
        ok=("r1", "r2"),
    )
    root, idea_id = idea_repo(tmp_path, "trash", section(files), files)
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


def test_a_term_in_an_other_rival_is_a_prior_art_hit_but_not_a_closest_hit(tmp_path):
    case = gold.load_cases(FIX)[0]
    files = run_files(
        [rec("r1", "Zotero Connector"), rec("r2", "Crossref REST API")],
        "r1",
        ("r2",),
        ok=("r1", "r2"),
    )
    root, idea_id = idea_repo(tmp_path, "trash", section(files), files)
    g = gold.grade_run(case, 1, root, idea_id)
    assert (g.prior_art_hit, g.closest_hit) == (True, False)


def test_the_term_in_a_judges_prose_about_an_unrelated_rival_is_no_hit(tmp_path):
    case = gold.load_cases(FIX)[0]
    files = run_files(
        [rec("r1", "Zotero Connector"), rec("r2", "Unrelated Thing")],
        "r1",
        ("r2",),
        ok=("r1", "r2"),
        differs="it never checks entries against Crossref",
    )
    text = section(files)
    assert "Crossref" in text
    root, idea_id = idea_repo(tmp_path, "trash", text, files)
    g = gold.grade_run(case, 1, root, idea_id)
    assert (g.prior_art_hit, g.closest_hit) == (False, False)


def test_a_term_matches_whole_words_only(tmp_path):
    case = gold.Case("flowers", "x", "trash", ("flower",))
    files = run_files([rec("r1", "cauliflower recipes")], "r1", ok=("r1",))
    root, idea_id = idea_repo(tmp_path, "trash", section(files), files)
    assert gold.grade_run(case, 1, root, idea_id).closest_hit is False
    files = run_files([rec("r1", "Flower: a plant app")], "r1", ok=("r1",))
    root, idea_id = idea_repo(tmp_path / "b", "trash", section(files), files)
    assert gold.grade_run(case, 1, root, idea_id).closest_hit is True


def test_a_rival_that_did_not_verify_is_no_hit(tmp_path):
    case = gold.load_cases(FIX)[0]
    files = run_files(
        [rec("r1", "dokimasia"), rec("r2", "Crossref API")], "r1", ("r2",), ok=("r2",)
    )
    root, idea_id = idea_repo(tmp_path, "trash", section(files, frozenset({"r1"})), files)
    g = gold.grade_run(case, 1, root, idea_id)
    assert (g.closest_hit, g.prior_art_hit, g.verified_ok) == (False, True, False)
    files = run_files([rec("r1", "dokimasia"), rec("r2", "Crossref API")], "r1", ("r2",))
    root, idea_id = idea_repo(tmp_path / "b", "trash", "", files)
    g = gold.grade_run(case, 1, root, idea_id)
    assert (g.closest_hit, g.prior_art_hit) == (False, False)


def test_a_verify_file_made_for_an_older_quote_or_record_counts_for_nothing(tmp_path):
    case = gold.load_cases(FIX)[0]
    files = run_files(
        [rec("r1", "dokimasia"), rec("r2", "Crossref API")], "r1", ("r2",), ok=("r1", "r2")
    )
    files["judge"]["closest"]["quote"] = "a rewritten quote"
    root, idea_id = idea_repo(tmp_path / "quote", "trash", "", files)
    g = gold.grade_run(case, 1, root, idea_id)
    assert (g.closest_hit, g.prior_art_hit, g.verified_ok) == (False, True, False)
    files = run_files([rec("r1", "dokimasia")], "r1", ok=("r1",))
    files["pool"]["records"][0]["url"] = "https://moved.example"
    root, idea_id = idea_repo(tmp_path / "url", "trash", "", files)
    g = gold.grade_run(case, 1, root, idea_id)
    assert (g.closest_hit, g.prior_art_hit, g.verified_ok) == (False, False, False)


def test_grade_run_do_on_an_existing_thing_is_not_accepted(tmp_path):
    case = gold.load_cases(FIX)[0]
    root, idea_id = idea_repo(tmp_path, "do", section(FULL_RUNS), FULL_RUNS)
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


def failed_runs(tmp: Path, case: gold.Case) -> list[gold.RunGrade]:
    """One grade for each way a run can fail."""
    inbox, inbox_id = idea_repo(tmp / "inbox", "inbox", "", None)
    partial, partial_id = idea_repo(tmp / "partial", "trash", "", {"restate": {}})
    return [
        gold.grade_run(case, 1, tmp / "none", "2026-10-17-x", error="timed out after 5s"),
        gold.grade_run(case, 2, tmp / "none", "2026-10-17-x"),
        gold.grade_run(case, 3, inbox, inbox_id),
        gold.grade_run(case, 4, partial, partial_id),
    ]


def test_every_failed_run_on_a_measured_case_counts_as_a_recall_miss(tmp_path):
    case = gold.load_cases(FIX)[0]
    grades = failed_runs(tmp_path, case)
    assert [(g.prior_art_hit, g.closest_hit) for g in grades] == [(False, False)] * 4
    assert all(g.error and not g.accepted for g in grades)
    s = gold.summarize(grades, [case])
    assert (s["prior_art_recall"], s["closest_recall"]) == (0.0, 0.0)


def test_failed_runs_on_an_unmeasured_case_stay_unmeasured(tmp_path):
    case = gold.load_cases(FIX)[1]
    grades = failed_runs(tmp_path, case)
    assert [(g.prior_art_hit, g.closest_hit) for g in grades] == [(None, None)] * 4
    assert gold.summarize(grades, [case])["prior_art_recall"] is None


def test_cases_without_match_terms_have_no_prior_art_measure(tmp_path):
    case = gold.load_cases(FIX)[1]
    root, idea_id = idea_repo(tmp_path, "trash", section(FULL_RUNS), FULL_RUNS)
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


def test_summarize_ignores_runs_of_unknown_cases_and_render_marks_missing_numbers():
    cases = gold.load_cases(FIX)
    grades = [
        gold.RunGrade("teleport", 1, "trash", True, None, None, True, True),
        gold.RunGrade("renamed", 1, "do", False, None, None, True, True),
    ]
    s = gold.summarize(grades, cases)
    assert (s["runs"], s["unknown_case_runs"], s["do_on_existing"]) == (1, 1, 0)
    md = gold.render_markdown(s)
    assert "- Total cost (client estimate): n/a" in md
    assert "- Median run time (s): n/a" in md
    assert "not in the cases file (ignored): 1" in md
    priced = gold.summarize(
        [gold.RunGrade("teleport", 1, "trash", True, None, None, True, True, cost_usd=0.5)], cases
    )
    assert "- Total cost (client estimate): $0.50" in gold.render_markdown(priced)


def test_run_grade_round_trips():
    g = gold.RunGrade("a", 1, "trash", True, None, None, True, False, error="", cost_usd=None)
    assert gold.RunGrade.from_dict(json.loads(json.dumps(g.to_dict()))) == g


def test_seed_set_is_valid_and_mostly_existing_things():
    cases = gold.load_cases(ROOT / "plugins" / "heuresis" / "gold" / "cases.yaml")
    assert len(cases) >= 20
    assert sum(c.kind == "exists" for c in cases) >= 16
    assert all(p.url.startswith("https://") for c in cases for p in c.prior_art)
