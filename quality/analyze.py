"""Analyze trial results exactly as PREREGISTRATION.md fixes the analysis.

    uv run python quality/analyze.py quality/results/<name> [--pilot] [--out report.md]

With only normal-mode runs it reports the baseline: each task's resolved share, median and
range over repeats, cost and tokens, flags, and judge-test disagreements. With both modes it
adds the H1, H2 and H3 decisions; with --pilot, the standard deviation of the per-task
differences and the task count needed for 80% power. Pure standard library.
"""

from __future__ import annotations

import argparse
import functools
import json
import math
import pathlib
import random
import statistics
import sys
import tomllib
from collections import defaultdict
from collections.abc import Sequence

MARGIN = -0.05
ALPHA = 0.05
POWER = 0.80
RESAMPLES = 10_000
SEED = 20261029
MAX_TASKS = 12
RISK_CLASSES = ("security", "destructive-operation", "governance")
CRITERIA = ("root_cause", "inputs_covered", "no_regression", "regression_test", "scope")
Z = statistics.NormalDist()
REPEATS, PILOT_REPEATS = 3, 1
# The registered models; a run on any other (a smoke run on Haiku) is never analysed.
IMPLEMENTER = {"normal": "claude-opus-5-5", "budget": "claude-sonnet-5-5"}
REVIEWER = JUDGE = "claude-opus-5-5"
TASKS = pathlib.Path(__file__).resolve().parent / "tasks" / "tasks.toml"


def check_set(runs: list[dict], task_ids: list[str], repeats: int) -> list[str]:
    """Why RUNS are not one complete trial, or nothing: every task in every mode present
    with repeats 1..REPEATS, the registered models, and every verdict from one judge pass."""
    problems = []
    for mode in sorted({r["mode"] for r in runs}):
        have = {(r["task"], r["repeat"]) for r in runs if r["mode"] == mode}
        missing = [
            f"{t}/r{n}" for t in task_ids for n in range(1, repeats + 1) if (t, n) not in have
        ]
        extra = sorted(f"{t}/r{n}" for t, n in have if t not in task_ids or not 1 <= n <= repeats)
        if missing:
            problems.append(f"{mode}: missing {', '.join(missing)}")
        if extra:
            problems.append(f"{mode}: not in the registered set {', '.join(extra)}")
    for r in runs:
        tag = f"{r['task']}/{r['mode']}/r{r['repeat']}"
        want = (IMPLEMENTER.get(r["mode"]), REVIEWER, JUDGE)
        got = (r.get("implementer"), r.get("reviewer"), r.get("judge"))
        verdict_model = (r.get("judge_verdict") or {}).get("model", JUDGE)
        if got != want or verdict_model != JUDGE:
            problems.append(f"{tag}: models {got}, judged by {verdict_model}; registered {want}")
    passes = {(r.get("judge_verdict") or {}).get("pass") for r in runs}
    if len(passes) > 1:
        problems.append(f"verdicts from {len(passes)} judge passes: judge all folders together")
    versions = {r.get("claude_code") for r in runs}
    if len(versions) > 1:
        problems.append(f"Claude Code versions {sorted(map(str, versions))}: rerun on one version")
    return problems


def load(*folders: pathlib.Path) -> list[dict]:
    """Every run under FOLDERS; one (task, mode, repeat) twice is an error, so a pilot or an
    old baseline is never pooled into the analysis by accident."""
    runs, seen = [], {}
    for folder in folders:
        for p in sorted(folder.rglob("run.json")):
            run = json.loads(p.read_text(encoding="utf-8"))
            key = (run["task"], run["mode"], run["repeat"])
            if key in seen:
                raise SystemExit(f"{p} repeats {seen[key]}: analyze one trial's folders only")
            seen[key] = p
            errors = p.parent / "errors.json"
            run["retries"] = len(json.loads(errors.read_text())) if errors.exists() else 0
            runs.append(run)
    return runs


def scores(runs: list[dict]) -> dict[str, dict[str, list[int]]]:
    """task -> mode -> resolved (0/1) per repeat, in repeat order."""
    out: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for r in sorted(runs, key=lambda r: (r["task"], r["mode"], r["repeat"])):
        out[r["task"]][r["mode"]].append(int(r["resolved"]))
    return out


def mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs)


def bootstrap_lower(d: list[float], alpha: float = ALPHA, seed: int = SEED) -> float:
    """One-sided lower bound of the mean of D: the alpha quantile of task-level resamples."""
    rng = random.Random(seed)
    n = len(d)
    means = sorted(mean([d[rng.randrange(n)] for _ in range(n)]) for _ in range(RESAMPLES))
    return means[max(0, math.floor(alpha * RESAMPLES) - 1)]


@functools.lru_cache(maxsize=256)
def t_quantile(p: float, df: int) -> float:
    """Student t quantile by bisection on the regularized incomplete beta (no SciPy)."""

    def cdf(t: float) -> float:
        x = df / (df + t * t)
        tail = 0.5 * betainc(df / 2, 0.5, x)
        return 1 - tail if t > 0 else tail

    lo, hi = -50.0, 50.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if cdf(mid) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def betainc(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta I_x(a, b) by continued fraction (Numerical Recipes 6.4)."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    ln = (
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x)
    )
    if x > (a + 1) / (a + b + 2):
        return 1 - betainc(b, a, 1 - x)
    c, dd = 1.0, 1 - (a + b) * x / (a + 1)
    dd = 1 / (dd if abs(dd) > 1e-300 else 1e-300)
    h = dd
    for m in range(1, 300):
        for num in (
            m * (b - m) * x / ((a + 2 * m - 1) * (a + 2 * m)),
            -(a + m) * (a + b + m) * x / ((a + 2 * m) * (a + 2 * m + 1)),
        ):
            dd = 1 + num * dd
            dd = 1 / (dd if abs(dd) > 1e-300 else 1e-300)
            c = 1 + num / c
            c = c if abs(c) > 1e-300 else 1e-300
            h *= dd * c
    return math.exp(ln) * h / a


def t_lower(d: list[float], alpha: float = ALPHA) -> float:
    n = len(d)
    if n < 2:
        return -math.inf
    sd = statistics.stdev(d)
    return mean(d) - t_quantile(1 - alpha, n - 1) * sd / math.sqrt(n)


def tasks_needed(sd: float, margin: float = -MARGIN) -> int:
    """Tasks for POWER at a true difference of 0, one-sided ALPHA (normal approximation)."""
    z = Z.inv_cdf(1 - ALPHA) + Z.inv_cdf(POWER)
    return math.ceil((z * sd / margin) ** 2) if sd > 0 else 2


def simulated_power(d: list[float], n: int, trials: int = 10_000, seed: int = SEED) -> float:
    """Share of simulated trials of N tasks, resampling D centred at 0, whose t lower bound
    clears the margin (the bootstrap bound is the costlier twin, so the t bound sizes it)."""
    rng = random.Random(seed)
    centred = [x - mean(d) for x in d]
    hits = 0
    for _ in range(trials):
        sample = [centred[rng.randrange(len(centred))] for _ in range(n)]
        hits += t_lower(sample) > MARGIN
    return hits / trials


def task_rows(runs: list[dict]) -> list[dict]:
    by: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in runs:
        by[(r["task"], r["mode"])].append(r)
    rows = []
    for (task, mode), rs in sorted(by.items()):
        res = [int(r["resolved"]) for r in rs]
        cost = [r["usage"].get("cost_usd", 0.0) for r in rs]
        rows.append(
            {
                "task": task,
                "mode": mode,
                "risk": rs[0]["risk"],
                "repeats": len(rs),
                "resolved": mean(res),
                "tests_passed": mean([int(r["tests"]["passed"]) for r in rs]),
                "median_cost_usd": statistics.median(cost),
                "cost_range": [min(cost), max(cost)],
                "median_tokens": {
                    k: statistics.median(r["usage"].get(k, 0) for r in rs)
                    for k in ("input", "output", "cache_read", "cache_write")
                },
                "median_reviews": statistics.median(len(r["reviews"]) for r in rs),
                "retries": sum(r.get("retries", 0) for r in rs),
                "harness_failed": sum(bool(r.get("harness_failed")) for r in rs),
                "judge_scores": {
                    c: statistics.median((r["judge_verdict"] or {}).get(c, 0) for r in rs)
                    for c in CRITERIA
                },
                "flags": sorted({f for r in rs for f in r["flags"]}),
                "disagreements": [
                    {
                        "repeat": r["repeat"],
                        "tests": r["tests"]["passed"],
                        "judge_blocking": r["judge_verdict"].get("blocking_defect"),
                        "reason": r["judge_verdict"].get("blocking_reason", "")[:300],
                    }
                    for r in rs
                    if r["judge_verdict"].get("ok")
                    and r["tests"]["passed"] == bool(r["judge_verdict"].get("blocking_defect"))
                ],
            }
        )
    return rows


def decide(runs: list[dict], pilot: bool = False) -> dict:
    s = scores(runs)
    out: dict = {"tasks": task_rows(runs)}
    paired = [t for t in s if s[t].get("normal") and s[t].get("budget")]
    if not paired:
        return out
    d = [mean(s[t]["budget"]) - mean(s[t]["normal"]) for t in paired]
    sd = statistics.stdev(d) if len(d) > 1 else 0.0
    out["paired_tasks"] = len(d)
    out["differences"] = dict(zip(paired, d, strict=True))
    out["mean_difference"] = mean(d)
    out["sd_difference"] = sd
    if pilot:
        need = tasks_needed(sd)
        power = simulated_power(d, max(need, 2)) if len(d) > 1 else None
        out["pilot"] = {
            "discordant_tasks": sum(x != 0 for x in d),
            "tasks_needed": need,
            "simulated_power_at_needed": power,
            "simulated_power_at_max": simulated_power(d, MAX_TASKS) if len(d) > 1 else None,
            "verdict": "proceed"
            if need <= MAX_TASKS and power is not None and power >= POWER
            else "inconclusive: normal mode stays",
        }
        return out
    boot, tl = bootstrap_lower(d), t_lower(d)
    cost: dict[str, dict[str, list[float]]] = {r["task"]: {} for r in runs}
    unknown = {r["task"] for r in runs if not r["usage"].get("cost_known", 1)}
    for r in runs:
        cost[r["task"]].setdefault(r["mode"], []).append(r["usage"].get("cost_usd", 0.0))
    # Per task, the median budget cost over the median normal cost. A task with a run whose
    # cost is unknown (a timed-out session reports none) or a zero normal cost counts as
    # infinitely dearer in budget mode: dropping it would favour the mode that times out.
    ratios = [
        math.inf
        if t in unknown or statistics.median(cost[t]["normal"]) <= 0
        else statistics.median(cost[t]["budget"]) / statistics.median(cost[t]["normal"])
        for t in paired
    ]
    out["h2_imputed"] = sorted(
        t for t in paired if t in unknown or statistics.median(cost[t]["normal"]) <= 0
    )
    rng = random.Random(SEED)
    boot_medians = sorted(
        statistics.median(ratios[rng.randrange(len(ratios))] for _ in ratios)
        for _ in range(RESAMPLES)
    )
    upper = boot_medians[min(RESAMPLES - 1, math.ceil((1 - ALPHA) * RESAMPLES) - 1)]
    risk = {t: next(r["risk"] for r in runs if r["task"] == t) for t in paired}
    out["h1"] = {
        "bootstrap_lower": boot,
        "t_lower": tl,
        "non_inferior": boot > MARGIN and tl > MARGIN,
    }
    out.setdefault(
        "h2",
        {"median_cost_ratio": statistics.median(ratios), "upper": upper, "cheaper": upper < 1},
    )
    out["h3"] = {
        c: {
            "tasks": [t for t in paired if risk[t] == c],
            "regressions": [t for t, x in zip(paired, d, strict=True) if risk[t] == c and x < 0],
        }
        for c in RISK_CLASSES
    }
    return out


def fmt_pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def report(result: dict, title: str) -> str:
    lines = [f"# {title}", "", "Generated by `quality/analyze.py`; do not edit by hand.", ""]
    lines += [
        "| Task | Risk | Mode | Resolved | Tests pass | Median reviews | Median cost | Cost range"
        " | Median output tokens | Flags | Judge-test disagreements |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in result["tasks"]:
        lo, hi = r["cost_range"]
        lines.append(
            f"| {r['task']} | {r['risk']} | {r['mode']} | {fmt_pct(r['resolved'])} of"
            f" {r['repeats']} | {fmt_pct(r['tests_passed'])} | {r['median_reviews']:g} |"
            f" ${r['median_cost_usd']:.2f} | ${lo:.2f} to ${hi:.2f} |"
            f" {r['median_tokens']['output']:g} | {len(r['flags'])} |"
            f" {len(r['disagreements'])} |"
        )
    flagged = [(r["task"], r["mode"], f) for r in result["tasks"] for f in r["flags"]]
    lines += ["", "## Cheat-audit flags", ""]
    lines += [f"- {t} ({m}): {f}" for t, m, f in flagged] or ["None."]
    lines += ["", "## Judge-test disagreements", ""]
    dis = [(r["task"], r["mode"], x) for r in result["tasks"] for x in r["disagreements"]]
    lines += [
        f"- {t} ({m}) r{x['repeat']}: tests {'pass' if x['tests'] else 'fail'}, judge"
        f" {'finds' if x['judge_blocking'] else 'finds no'} blocking defect. {x['reason']}"
        for t, m, x in dis
    ] or ["None."]
    lines += ["", "## Harness retries and failures", ""]
    for mode in sorted({r["mode"] for r in result["tasks"]}):
        rows = [r for r in result["tasks"] if r["mode"] == mode]
        failed = [r["task"] for r in rows if r["harness_failed"]]
        lines.append(
            f"- {mode}: {sum(r['retries'] for r in rows)} failed attempts;"
            f" runs that failed 3 times: {', '.join(failed) or 'none'}"
        )
    lines += ["", "## Judge criterion scores (median, 0 to 3)", ""]
    lines += [
        f"- {r['task']} ({r['mode']}): "
        + ", ".join(f"{c} {v:g}" for c, v in r["judge_scores"].items())
        for r in result["tasks"]
    ]
    if "differences" in result:
        lines += ["", "## Per-task differences (budget minus normal)", ""]
        lines += [f"- {t}: {x:+.3f}" for t, x in result["differences"].items()]
    if "h1" in result:
        h1, h2 = result["h1"], result["h2"]
        lines += [
            "",
            "## Decision",
            "",
            f"- Mean per-task difference (budget minus normal): {result['mean_difference']:+.3f}",
            f"- H1 lower bounds: bootstrap {h1['bootstrap_lower']:+.3f}, t {h1['t_lower']:+.3f};"
            f" margin {MARGIN:+.2f}: {'non-inferior' if h1['non_inferior'] else 'not shown'}",
            f"- H2: median cost ratio {h2['median_cost_ratio']:.2f}, one-sided 95% upper bound"
            f" {h2['upper']:.2f}: {'cheaper' if h2['cheaper'] else 'not shown'}",
            "- H2 tasks counted as dearer in budget mode (a cost unknown or zero): "
            + (", ".join(result["h2_imputed"]) or "none"),
        ]
        for c, v in result["h3"].items():
            lines.append(
                f"- H3 {c}: {len(v['tasks'])} tasks, regressions"
                f" {', '.join(v['regressions']) or 'none'}"
            )
    if "pilot" in result:
        p = result["pilot"]
        lines += [
            "",
            "## Pilot sizing",
            "",
            f"- SD of per-task differences: {result['sd_difference']:.3f}",
            f"- Discordant tasks: {p['discordant_tasks']} of {result['paired_tasks']}",
            f"- Tasks needed for 80% power: {p['tasks_needed']} (cap {MAX_TASKS})",
            f"- Verdict: {p['verdict']}",
        ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("results", type=pathlib.Path, nargs="+", help="one trial's result folders")
    ap.add_argument("--pilot", action="store_true")
    ap.add_argument("--out", type=pathlib.Path)
    ap.add_argument("--tasks", type=pathlib.Path, default=TASKS)
    args = ap.parse_args(argv)
    runs = load(*args.results)
    if not runs:
        print(f"no run.json under {args.results}", file=sys.stderr)
        return 1
    unjudged = [f"{r['task']}/{r['mode']}/r{r['repeat']}" for r in runs if r["resolved"] is None]
    if unjudged:
        print(
            f"not judged yet (run quality/run.py --judge): {', '.join(unjudged)}", file=sys.stderr
        )
        return 1
    task_ids = [t["id"] for t in tomllib.loads(args.tasks.read_text(encoding="utf-8"))["task"]]
    problems = check_set(runs, task_ids, PILOT_REPEATS if args.pilot else REPEATS)
    if problems:
        print("not one complete trial:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 1
    result = decide(runs, pilot=args.pilot)
    md = report(result, "Quality trial: " + ", ".join(r.name for r in args.results))
    (args.results[0] / "summary.json").write_text(json.dumps(result, indent=1) + "\n")
    if args.out:
        args.out.write_text(md, encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
