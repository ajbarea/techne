"""quality/analyze.py computes the pre-registered statistics correctly."""

from __future__ import annotations

import json
import math
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "quality"))
import analyze as a  # ty: ignore[unresolved-import]


@pytest.mark.parametrize(
    ("p", "df", "want"),
    # Reference values from standard t tables.
    [(0.95, 9, 1.833), (0.95, 11, 1.796), (0.975, 4, 2.776), (0.95, 1, 6.314), (0.5, 7, 0.0)],
)
def test_t_quantile(p, df, want):
    assert a.t_quantile(p, df) == pytest.approx(want, abs=2e-3)


def test_t_lower_matches_the_formula():
    d = [0.0, -1 / 3, 0.0, 1 / 3, 0.0, 0.0, -1 / 3, 0.0, 0.0, 0.0]
    sd = (sum((x - sum(d) / 10) ** 2 for x in d) / 9) ** 0.5
    assert a.t_lower(d) == pytest.approx(sum(d) / 10 - 1.833 * sd / math.sqrt(10), abs=1e-3)


def test_bootstrap_lower_is_deterministic_and_below_the_mean():
    d = [0.0, -1 / 3, 0.0, 1 / 3, 0.0, 0.0, -1 / 3, 0.0, 0.0, 0.0]
    assert a.bootstrap_lower(d) == a.bootstrap_lower(d)
    assert a.bootstrap_lower(d) < a.mean(d)
    assert a.bootstrap_lower([0.0] * 10) == 0.0


@pytest.mark.parametrize(("sd", "want"), [(0.079, 16), (0.0786, 16), (0.07, 13), (0.2, 99)])
def test_tasks_needed(sd, want):
    # (1.645 + 0.842)^2 * sd^2 / 0.05^2, rounded up.
    assert a.tasks_needed(sd) == want


def run(task, mode, rep, resolved, risk="ordinary", cost=1.0, tests=True, blocking=False):
    return {
        "task": task,
        "mode": mode,
        "repeat": rep,
        "risk": risk,
        "resolved": resolved,
        "tests": {"passed": tests},
        "judge_verdict": {"ok": True, "blocking_defect": blocking, "blocking_reason": "r"},
        "flags": [],
        "reviews": [{}],
        "usage": {"cost_usd": cost, "input": 1, "output": 2, "cache_read": 3, "cache_write": 4},
    }


def trial(budget_resolved, risk="ordinary", n=10):
    runs = []
    for t in range(n):
        for rep in (1, 2, 3):
            runs.append(run(f"t{t}", "normal", rep, True, risk, cost=2.0))
            runs.append(run(f"t{t}", "budget", rep, budget_resolved(t, rep), risk, cost=1.0))
    return runs


def test_identical_modes_are_non_inferior_and_cheaper():
    out = a.decide(trial(lambda t, r: True))
    assert out["h1"]["non_inferior"] and out["h2"]["cheaper"]
    assert out["h2"]["median_cost_ratio"] == 0.5


def test_one_lost_task_fails_h1():
    # Budget loses every repeat of one task in ten: mean -0.1, beyond the margin.
    out = a.decide(trial(lambda t, r: t != 0))
    assert out["mean_difference"] == pytest.approx(-0.1)
    assert not out["h1"]["non_inferior"]


def test_one_lost_repeat_in_a_risk_class_fails_that_class():
    out = a.decide(trial(lambda t, r: not (t == 3 and r == 1), risk="security"))
    assert out["h3"]["security"]["regressions"] == ["t3"]


def test_pilot_sizing_says_inconclusive_when_too_many_tasks_are_needed():
    out = a.decide(trial(lambda t, r: not (t % 2 and r == 1)), pilot=True)
    assert out["pilot"]["tasks_needed"] > a.MAX_TASKS
    assert out["pilot"]["verdict"].startswith("inconclusive")


def test_disagreements_are_listed_both_ways():
    runs = [
        run("x", "normal", 1, False, tests=True, blocking=True),
        run("x", "normal", 2, False, tests=False, blocking=False),
        run("x", "normal", 3, True, tests=True, blocking=False),
    ]
    (row,) = a.task_rows(runs)
    assert [(d["tests"], d["judge_blocking"]) for d in row["disagreements"]] == [
        (True, True),
        (False, False),
    ]


def test_h2_leaves_out_unknown_and_zero_costs():
    runs = trial(lambda t, r: True)
    for x in runs:
        if x["task"] == "t0":
            x["usage"]["cost_known"] = 0
        if x["task"] == "t1" and x["mode"] == "normal":
            x["usage"]["cost_usd"] = 0.0
    out = a.decide(runs)
    assert out["h2"]["median_cost_ratio"] == 0.5


def test_h2_counts_a_task_with_an_unknown_cost_as_dearer_in_budget_mode():
    runs = trial(lambda t, r: True)
    for x in runs:
        x["usage"]["cost_known"] = 0
    out = a.decide(runs)
    assert out["h2"]["median_cost_ratio"] == math.inf and not out["h2"]["cheaper"]
    assert len(out["h2_imputed"]) == len(out["differences"])


def test_load_refuses_a_run_twice(tmp_path):
    for folder in ("a", "b"):
        path = tmp_path / folder / "t0" / "normal" / "r1" / "run.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(run("t0", "normal", 1, True)))
    with pytest.raises(SystemExit, match="repeats"):
        a.load(tmp_path / "a", tmp_path / "b")
    assert len(a.load(tmp_path / "a")) == 1


def registered(runs):
    for r in runs:
        r.update(implementer=a.IMPLEMENTER[r["mode"]], reviewer=a.REVIEWER, judge=a.JUDGE)
        r["judge_verdict"].update(model=a.JUDGE, **{"pass": "p1"})
    return runs


def test_check_set_accepts_one_complete_trial():
    runs = registered(trial(lambda t, r: True))
    assert a.check_set(runs, [f"t{t}" for t in range(10)], a.REPEATS) == []


def test_check_set_refuses_a_missing_mode_or_repeat():
    runs = registered(trial(lambda t, r: True))
    runs = [r for r in runs if not (r["task"] == "t3" and r["mode"] == "budget")]
    runs = [r for r in runs if not (r["task"] == "t4" and r["repeat"] == 3)]
    problems = a.check_set(runs, [f"t{t}" for t in range(10)], a.REPEATS)
    assert any("t3/r1" in p for p in problems) and any("t4/r3" in p for p in problems)


def test_check_set_refuses_a_smoke_model_and_a_second_judge_pass():
    runs = registered(trial(lambda t, r: True))
    runs[0]["implementer"] = "claude-haiku-5-5"
    runs[1]["judge_verdict"]["pass"] = "p2"
    problems = a.check_set(runs, [f"t{t}" for t in range(10)], a.REPEATS)
    assert any("models" in p for p in problems) and any("judge passes" in p for p in problems)


def test_check_set_refuses_two_claude_code_versions():
    runs = registered(trial(lambda t, r: True))
    for r in runs:
        r["claude_code"] = "2.1.302"
    runs[5]["claude_code"] = "2.1.303"
    problems = a.check_set(runs, [f"t{t}" for t in range(10)], a.REPEATS)
    assert any("versions" in p for p in problems)


def test_the_report_lists_retries_and_harness_failures_per_mode():
    runs = trial(lambda t, r: True)
    runs[0].update(retries=2, harness_failed=True)
    md = a.report(a.decide(runs), "t")
    assert "- normal: 2 retries; runs that failed 3 times: t0" in md
    assert "- budget: 0 retries; runs that failed 3 times: none" in md
