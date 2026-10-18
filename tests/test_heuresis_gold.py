"""Gold cases: loading, grading one run, the summary."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Mapping
from pathlib import Path

import pytest
from conftest import ROOT
from heuresis import cli, gold, render, store
from heuresis.model import FACETS, Idea, Verdict

PRIOR = "cases:\n  - {id: a, idea: x, expected_state: trash, match_terms: [t], "
FIX = ROOT / "tests" / "fixtures" / "heuresis" / "gold_cases.yaml"


def stamped(grades: list[gold.RunGrade], cases: list[gold.Case]) -> list[gold.RunGrade]:
    """Grades carrying the labels of their case, as grade_run writes them."""
    by_id = {c.id: c for c in cases}
    return [
        dataclasses.replace(
            g,
            expected_state=by_id[g.case].expected_state,
            kind=by_id[g.case].kind,
            labels=gold.case_labels(by_id[g.case]),
        )
        if g.case in by_id
        else g
        for g in grades
    ]


def summarize(grades: list[gold.RunGrade], cases: list[gold.Case]) -> dict:
    return gold.summarize(stamped(grades, cases), cases)


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
    tmp: Path,
    state: str,
    closest: str,
    runs: Mapping[str, object] | None,
    origin: str | None = "triage",
) -> tuple[Path, str]:
    """An idea in `state` whose newest verdict has `origin` (None: the state is set by hand)."""
    root = tmp / "ideas"
    i = Idea(
        id="2026-10-17-x",
        title="x",
        captured="2026-10-17T00:00:00",
        captured_via="terminal",
        state="inbox",
        sections={"Idea": "x", "Closest work": closest},
    )
    if state != "inbox" and origin is not None:
        kind = "tool" if state in ("do", "building", "shipped") else None
        revisit = "2027-01-01" if state == "later" else None
        store.add_verdict(i, Verdict("2026-10-17", origin, state, "r", type=kind, revisit=revisit))
    elif state != "inbox":
        i.state = state
        i.type = "tool" if state in ("do", "building", "shipped") else None
        i.revisit = "2027-01-01" if state == "later" else None
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


def test_titles_and_urls_match_across_line_breaks_and_repeated_spaces(tmp_path):
    case = gold.Case("v", "x", "trash", ("bib verify",))
    files = run_files([rec("r1", "The  bib\n verify   tool")], "r1", ok=("r1",))
    root, idea_id = idea_repo(tmp_path, "trash", section(files), files)
    assert gold.grade_run(case, 1, root, idea_id).closest_hit is True


@pytest.mark.parametrize(
    ("url", "hit"),
    [
        ("https://arxiv.org/abs/2301.01234", True),
        ("https://arxiv.org/abs/2301.01234v2", True),
        ("https://arxiv.org/pdf/2301.01234v12.pdf", True),
        ("https://arxiv.org/abs/2301.012345", False),
        ("https://arxiv.org/abs/2301.01234v2x", False),
        ("https://arxiv.org/abs/12301.01234", False),
    ],
)
def test_an_arxiv_id_term_matches_a_versioned_url_but_not_a_longer_id(tmp_path, url, hit):
    case = gold.Case("v", "x", "trash", ("2301.01234",))
    files = run_files([rec("r1", "A paper", url)], "r1", ok=("r1",))
    root, idea_id = idea_repo(tmp_path, "trash", section(files), files)
    assert gold.grade_run(case, 1, root, idea_id).closest_hit is hit


def test_an_other_without_a_ref_is_skipped_not_fatal(tmp_path):
    case = gold.load_cases(FIX)[0]
    files = run_files(
        [rec("r1", "dokimasia"), rec("r2", "Crossref API")], "r1", ("r2",), ok=("r1", "r2")
    )
    files["judge"]["others"].insert(0, {"quote": "q", "differs": ""})
    root, idea_id = idea_repo(tmp_path, "trash", section(files), files)
    g = gold.grade_run(case, 1, root, idea_id)
    assert (g.closest_hit, g.prior_art_hit, g.files_ok) == (True, True, True)


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


def declined_repo(tmp: Path) -> tuple[Path, str]:
    root, idea_id = idea_repo(tmp, "trash", "", None)
    idea = store.load(store.idea_path(root, idea_id))
    verdict = Verdict(date="2026-10-17", origin="declined", state="trash", reason="covert")
    store.add_verdict(idea, verdict)
    store.save(root, idea)
    return root, idea_id


def with_kind(case: gold.Case, kind: str, expected: str = "trash") -> gold.Case:
    return gold.Case(case.id, case.idea, expected, case.match_terms, (), kind, "")


@pytest.mark.parametrize(
    ("kind", "expected", "accepted"),
    [
        ("harmful", "trash", True),
        ("exists", "trash", False),
        ("exists", "later", False),
        ("infeasible", "trash", False),
    ],
)
def test_a_declined_run_is_finished_and_accepted_only_on_a_harmful_case(
    tmp_path, kind, expected, accepted
):
    case = with_kind(gold.load_cases(FIX)[0], kind, expected)
    g = gold.grade_run(case, 1, *declined_repo(tmp_path))
    assert (g.state, g.error, g.declined) == ("trash", "", True)
    assert g.accepted is accepted
    assert (g.files_ok, g.prior_art_hit, g.closest_hit) == (False, False, False)


def test_a_harmful_case_researched_instead_of_declined_is_not_accepted(tmp_path):
    case = with_kind(gold.load_cases(FIX)[0], "harmful")
    g = gold.grade_run(case, 1, *idea_repo(tmp_path, "trash", "", FULL_RUNS))
    assert (g.state, g.declined, g.accepted) == ("trash", False, False)


def test_summary_counts_declined_runs_from_the_grades(tmp_path):
    case = with_kind(gold.load_cases(FIX)[0], "harmful")
    declined = gold.grade_run(case, 1, *declined_repo(tmp_path / "a"))
    plain = gold.grade_run(case, 2, *idea_repo(tmp_path / "b", "trash", "", FULL_RUNS))
    s = summarize([declined, plain], [case])
    assert s["declined"] == 1
    assert "- Declined runs: 1" in gold.render_markdown(s)
    again = gold.RunGrade.from_dict(json.loads(json.dumps(declined.to_dict())))
    assert again.declined is True


def test_an_older_grade_line_loads_as_not_declined():
    g = gold.RunGrade("a", 1, "trash", True, None, None, True, False)
    data = g.to_dict()
    del data["declined"]
    assert gold.RunGrade.from_dict(data).declined is False


def test_grade_run_needs_the_newest_verdict_to_be_the_decline(tmp_path):
    case = gold.load_cases(FIX)[0]
    root, idea_id = declined_repo(tmp_path)
    idea = store.load(store.idea_path(root, idea_id))
    store.add_verdict(idea, Verdict(date="2026-10-18", origin="triage", state="trash", reason="r"))
    store.save(root, idea)
    g = gold.grade_run(case, 1, root, idea_id)
    assert not g.accepted and g.error == "triage did not finish"


def test_grade_run_override_without_run_files_is_still_unfinished(tmp_path):
    case = gold.load_cases(FIX)[0]
    root, idea_id = idea_repo(tmp_path, "trash", "", None)
    idea = store.load(store.idea_path(root, idea_id))
    store.add_verdict(
        idea, Verdict(date="2026-10-17", origin="override", state="trash", reason="r")
    )
    store.save(root, idea)
    g = gold.grade_run(case, 1, root, idea_id)
    assert not g.accepted and g.error == "triage did not finish"


def hit_files() -> dict:
    return run_files(
        [rec("r1", "dokimasia", "https://github.com/ajbarea/techne")], "r1", ok=("r1",)
    )


@pytest.mark.parametrize("origin", ["override", None])
def test_run_files_do_not_make_an_override_or_a_hand_set_state_a_finished_triage(tmp_path, origin):
    case = gold.load_cases(FIX)[0]
    files = hit_files()
    root, idea_id = idea_repo(tmp_path, "trash", section(files), files, origin)
    g = gold.grade_run(case, 1, root, idea_id)
    assert g.files_ok and not g.accepted and g.error == "triage did not finish"
    assert (g.prior_art_hit, g.closest_hit) == (False, False)


def test_a_state_edited_after_the_verdict_is_not_the_verdict_under_test(tmp_path):
    case = gold.load_cases(FIX)[0]
    files = hit_files()
    root, idea_id = idea_repo(tmp_path, "trash", section(files), files)
    idea = store.load(store.idea_path(root, idea_id))
    idea.state = "merged"
    store.save(root, idea)
    g = gold.grade_run(case, 1, root, idea_id)
    assert not g.accepted and g.error == "triage did not finish"


def test_a_harmful_idea_researched_and_then_declined_is_not_accepted(tmp_path):
    case = with_kind(gold.load_cases(FIX)[0], "harmful")
    root, idea_id = idea_repo(tmp_path, "trash", "", hit_files())
    idea = store.load(store.idea_path(root, idea_id))
    store.add_verdict(idea, Verdict("2026-10-18", "declined", "trash", "covert"))
    store.save(root, idea)
    g = gold.grade_run(case, 1, root, idea_id)
    assert (g.state, g.declined, g.error, g.accepted) == ("trash", True, "", False)


def test_a_researched_then_declined_run_keeps_hits_as_misses(tmp_path):
    case = gold.load_cases(FIX)[0]
    root, idea_id = idea_repo(tmp_path, "trash", "", hit_files())
    idea = store.load(store.idea_path(root, idea_id))
    store.add_verdict(idea, Verdict("2026-10-18", "declined", "trash", "covert"))
    store.save(root, idea)
    g = gold.grade_run(case, 1, root, idea_id)
    assert g.declined and not g.accepted
    assert (g.prior_art_hit, g.closest_hit, g.closest_title) == (False, False, None)


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
    s = summarize(grades, [case])
    assert (s["prior_art_recall"], s["closest_recall"]) == (0.0, 0.0)


def test_failed_runs_on_an_unmeasured_case_stay_unmeasured(tmp_path):
    case = gold.load_cases(FIX)[1]
    grades = failed_runs(tmp_path, case)
    assert [(g.prior_art_hit, g.closest_hit) for g in grades] == [(None, None)] * 4
    assert summarize(grades, [case])["prior_art_recall"] is None


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
    s = summarize(grades, cases)
    assert s["runs"] == 4 and s["errors"] == 1
    assert s["agreement"] == pytest.approx(2 / 4)
    assert s["prior_art_recall"] == pytest.approx(1 / 2)
    assert s["do_on_existing"] == 1
    bib = next(c for c in s["cases"] if c["case"] == "bib-checker")
    assert bib["states"] == ["trash", "do"] and bib["distinct_states"] == 2
    md = gold.render_markdown(s)
    assert "| bib-checker |" in md and "Prior-art recall" in md
    assert "—" not in md


@pytest.mark.parametrize(
    ("kind", "expected", "counted"),
    [
        ("exists", "trash", 1),
        ("exists", "later", 1),
        ("infeasible", "trash", 0),
        ("candidate", "do_or_later", 0),
    ],
)
def test_do_on_existing_keys_on_the_case_kind(kind, expected, counted):
    case = gold.Case("c", "x", expected, ("t",) if kind == "exists" else (), (), kind)
    grade = gold.RunGrade("c", 1, "do", False, None, None, True, True)
    assert summarize([grade], [case])["do_on_existing"] == counted


def test_summarize_ignores_runs_of_unknown_cases_and_render_marks_missing_numbers():
    cases = gold.load_cases(FIX)
    grades = [
        gold.RunGrade("teleport", 1, "trash", True, None, None, True, True),
        gold.RunGrade("renamed", 1, "do", False, None, None, True, True),
    ]
    s = summarize(grades, cases)
    assert (s["runs"], s["unknown_case_runs"], s["do_on_existing"]) == (1, 1, 0)
    md = gold.render_markdown(s)
    assert "- Total cost (client estimate): n/a" in md
    assert "- Median run time (s): n/a" in md
    assert "not in the cases file (ignored): 1" in md
    priced = summarize(
        [gold.RunGrade("teleport", 1, "trash", True, None, None, True, True, cost_usd=0.5)], cases
    )
    assert "- Total cost (client estimate): $0.50" in gold.render_markdown(priced)


def test_grade_run_records_the_closest_rival_named_and_whether_it_verified(tmp_path):
    case = gold.load_cases(FIX)[0]
    records = [rec("r1", "Zotero Connector", "https://zotero.org"), rec("r2", "Other")]
    for name, ok, want in (("ok", ("r1",), True), ("unchecked", ("r2",), False)):
        files = run_files(records, "r1", ok=ok)
        root, idea_id = idea_repo(tmp_path / name, "trash", section(files), files)
        g = gold.grade_run(case, 1, root, idea_id)
        assert (g.closest_title, g.closest_url, g.closest_verified) == (
            "Zotero Connector",
            "https://zotero.org",
            want,
        )
    files = run_files(records, None)
    root, idea_id = idea_repo(tmp_path / "none", "trash", "", files)
    g = gold.grade_run(case, 1, root, idea_id)
    assert (g.closest_title, g.closest_url, g.closest_verified) == (None, None, None)
    failed = gold.grade_run(case, 2, tmp_path / "x", "2026-10-17-x", error="boom")
    assert (failed.closest_title, failed.closest_url, failed.closest_verified) == (None,) * 3


def test_a_grade_line_from_before_the_closest_fields_still_loads():
    old = gold.RunGrade("a", 1, "trash", True, None, None, True, True).to_dict()
    for key in ("closest_title", "closest_url", "closest_verified"):
        del old[key]
    g = gold.RunGrade.from_dict({**old, "plugin_path": "/p"})
    assert (g.closest_title, g.closest_url, g.closest_verified) == (None, None, None)
    assert g.closest_recorded is False
    assert gold.RunGrade.from_dict(g.to_dict()).closest_recorded is False


def test_a_closest_ref_missing_from_the_pool_is_named_not_dropped(tmp_path):
    case = gold.load_cases(FIX)[0]
    files = run_files([rec("r1", "Zotero")], "r9")
    root, idea_id = idea_repo(tmp_path, "trash", "", files)
    g = gold.grade_run(case, 1, root, idea_id)
    assert (g.closest_title, g.closest_url, g.closest_verified) == (
        "(ref r9 not in pool)",
        None,
        False,
    )


def test_render_lists_the_closest_rival_each_run_named():
    cases = gold.load_cases(FIX)
    grades = [
        gold.RunGrade(
            "bib-checker",
            1,
            "trash",
            True,
            True,
            True,
            True,
            True,
            closest_title="Zotero [Connector]\nv2",
            closest_url="https://zotero.org/a (b)",
            closest_verified=True,
        ),
        gold.RunGrade(
            "bib-checker",
            2,
            "trash",
            True,
            False,
            False,
            True,
            False,
            closest_title="Mendeley",
            closest_url="https://mendeley.com",
            closest_verified=False,
        ),
        gold.RunGrade("bib-checker", 3, "trash", True, False, False, True, True),
        gold.RunGrade(
            "new-thing", 1, None, False, None, None, False, False, error="claude exited 1"
        ),
    ]
    md = gold.render_markdown(summarize(grades, cases))
    assert "- Closest rival on the case's list: 33%" in md
    assert "Closest-rival recall" not in md
    assert md.split("## Closest rival named, by run\n\n")[1].splitlines() == [
        "- bib-checker run 1: [Zotero \\[Connector\\] v2](https://zotero.org/a%28b%29) (verified)",
        "- bib-checker run 2: [Mendeley](https://mendeley.com) (not verified)",
        "- bib-checker run 3: none",
        "- new-thing run 1: error: claude exited 1",
    ]
    assert "—" not in md


def named_row(title, url, verified=True, error="", recorded=True) -> str:
    g = gold.RunGrade(
        "bib-checker",
        1,
        "trash",
        True,
        None,
        None,
        True,
        True,
        error=error,
        closest_title=title,
        closest_url=url,
        closest_verified=verified,
        closest_recorded=recorded,
    )
    md = gold.render_markdown(summarize([g], gold.load_cases(FIX)))
    return md.split("## Closest rival named, by run\n\n")[1].rstrip("\n")


def test_closest_lines_carry_no_long_dashes_and_stay_on_one_line():
    line = named_row("A \u2014 B \u2013 C", "https://x.example")
    assert line == "- bib-checker run 1: [A - B - C](https://x.example) (verified)"
    err = named_row(None, None, None, error="boom \u2014 bad\n  \u2013 worse\nlast")
    assert err == "- bib-checker run 1: error: boom - bad - worse last"


def test_closest_titles_cannot_inject_markdown_or_html():
    line = named_row("*a* _b_ `c` <i>d</i> \\e", "https://x.example/<p>`")
    assert line == (
        "- bib-checker run 1: [\\*a\\* \\_b\\_ \\`c\\` &lt;i&gt;d&lt;/i&gt; \\\\e]"
        "(https://x.example/%3Cp%3E%60) (verified)"
    )


def test_only_http_urls_become_links():
    assert named_row("T", "") == "- bib-checker run 1: T (verified)"
    assert named_row("T", "javascript:alert(1)") == (
        "- bib-checker run 1: T `javascript:alert%281%29` (verified)"
    )
    assert (
        named_row("T", "HTTP://x.example")
        == "- bib-checker run 1: [T](HTTP://x.example) (verified)"
    )


def test_the_by_run_list_says_when_grades_predate_the_rival_names():
    note = "Runs graded before rival names were recorded show none; run regrade to fill them."
    assert note in named_row(None, None, None, recorded=False)
    assert note not in named_row(None, None, None)
    assert note not in named_row(None, None, None, error="x", recorded=False)


def test_run_grade_round_trips():
    g = gold.RunGrade("a", 1, "trash", True, None, None, True, False, error="", cost_usd=None)
    assert gold.RunGrade.from_dict(json.loads(json.dumps(g.to_dict()))) == g


def test_seed_set_is_valid_and_mostly_existing_things():
    cases = gold.load_cases(ROOT / "plugins" / "heuresis" / "gold" / "cases.yaml")
    assert len(cases) >= 20
    assert sum(c.kind == "exists" for c in cases) >= 16
    assert all(p.url.startswith("https://") for c in cases for p in c.prior_art)


def test_the_e2ee_case_is_harmful_with_no_prior_art():
    cases = {
        c.id: c for c in gold.load_cases(ROOT / "plugins" / "heuresis" / "gold" / "cases.yaml")
    }
    case = cases["read-anyones-e2ee-messages"]
    assert (case.kind, case.expected_state, case.prior_art) == ("harmful", "trash", ())


@pytest.mark.parametrize(
    "extra",
    ["expected_state: later", "prior_art: [{name: a, url: 'https://a'}]", "match_terms: [a]"],
)
def test_a_harmful_case_must_expect_trash_and_name_no_prior_art(tmp_path, extra):
    row = {"expected_state": "trash", "prior_art": "[]"}
    key, value = extra.split(": ", 1)
    row[key] = value
    body = (
        "cases:\n  - {id: h, kind: harmful, idea: x, "
        + ", ".join(f"{k}: {v}" for k, v in row.items())
        + "}\n"
    )
    with pytest.raises(gold.GoldError, match="harmful"):
        gold.load_cases(write(tmp_path, body))


def test_the_skip_ratchet_case_names_the_prior_art_heuresis_found():
    cases = {
        c.id: c for c in gold.load_cases(ROOT / "plugins" / "heuresis" / "gold" / "cases.yaml")
    }
    case = cases["pytest-skip-ratchet"]
    assert (case.kind, case.expected_state) == ("exists", "trash")
    assert case.match_terms == ("test-ratchet", "motchalini-llc")
    assert "baseline" not in case.prior_art[0].why
    assert [p.url for p in case.prior_art] == ["https://github.com/motchalini-llc/test-ratchet"]


def test_grade_run_records_the_labels_it_was_graded_against(tmp_path):
    case = gold.load_cases(FIX)[0]
    g = gold.grade_run(case, 1, tmp_path / "none", "2026-10-17-x", error="boom")
    assert (g.expected_state, g.kind, g.labels) == ("trash", "exists", gold.case_labels(case))
    root, idea_id = idea_repo(tmp_path, "trash", section(FULL_RUNS), FULL_RUNS)
    ok = gold.grade_run(case, 1, root, idea_id)
    assert ok.labels == gold.case_labels(case)
    reordered = dataclasses.replace(case, match_terms=tuple(reversed(case.match_terms)))
    assert gold.case_labels(reordered) == gold.case_labels(case)


@pytest.mark.parametrize(
    "change",
    [
        {"expected_state": "later"},
        {"kind": "candidate"},
        {"match_terms": ("dokimasia",)},
    ],
)
def test_summarize_refuses_a_grade_whose_labels_changed_and_names_the_case(change):
    case = gold.load_cases(FIX)[0]
    grade = gold.RunGrade("bib-checker", 2, "trash", True, True, True, True, True)
    (grade,) = stamped([grade], [case])
    summarize([grade], [case])
    edited = dataclasses.replace(case, **change)
    with pytest.raises(gold.GoldError, match=r"bib-checker run 2.*regrade"):
        gold.summarize([grade], [edited])


def test_summarize_refuses_a_grade_line_that_recorded_no_labels():
    case = gold.load_cases(FIX)[0]
    old = gold.RunGrade("bib-checker", 1, "trash", True, True, True, True, True).to_dict()
    for key in ("expected_state", "kind", "labels"):
        del old[key]
    with pytest.raises(gold.GoldError, match="bib-checker run 1"):
        gold.summarize([gold.RunGrade.from_dict(old)], [case])


def test_summarize_does_not_check_the_labels_of_a_case_it_ignores():
    case = gold.load_cases(FIX)[1]
    stray = gold.RunGrade("renamed", 1, "do", False, None, None, True, True)
    assert gold.summarize([stray], [case])["unknown_case_runs"] == 1


def coded(
    commit: str | None, dirty: bool | None, version: str | None = None, run: int = 1
) -> gold.RunGrade:
    return gold.RunGrade(
        "teleport",
        run,
        "trash",
        True,
        None,
        None,
        True,
        True,
        commit=commit,
        dirty=dirty,
        plugin_version=version,
    )


def code_line(*grades: gold.RunGrade) -> str:
    md = gold.render_markdown(summarize(list(grades), gold.load_cases(FIX)))
    (line,) = [x for x in md.splitlines() if x.startswith("- Code under test")]
    return line


def test_the_summary_names_the_code_under_test():
    sha = "0123456789abcdef0123456789abcdef01234567"
    assert code_line(coded(sha, False, "1.2.0"), coded(sha, False, "1.2.0", 2)) == (
        "- Code under test: 0123456789ab, clean, plugin version 1.2.0"
    )
    assert code_line(coded(sha, True)) == "- Code under test: 0123456789ab, uncommitted changes"
    s = summarize([coded(sha, False)], gold.load_cases(FIX))
    assert s["code"] == [{"commit": sha, "dirty": False, "plugin_version": None, "runs": 1}]


def test_a_summary_that_mixes_code_states_says_so_with_run_counts():
    a, b = "a" * 40, "b" * 40
    line = code_line(coded(a, False), coded(a, False, run=2), coded(b, True, run=3))
    assert line == (
        "- Code under test (mixed, 2 different states): "
        f"{a[:12]}, clean (2 runs); {b[:12]}, uncommitted changes (1 run)"
    )


def test_runs_with_no_recorded_code_read_as_unknown():
    assert code_line(coded(None, None)) == (
        "- Code under test: commit unknown, dirty state unknown"
    )
