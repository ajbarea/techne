"""Compare a bench/run.py summary with a baseline and fail when a hook got slower.

Usage: uv run python bench/compare.py BASELINE NEW [--threshold X] [--wall-threshold X]

Each case is judged by its ratio to the python3 floor, so a slower or faster machine moves both
sides alike. When both summaries carry retired-instruction counts, the instruction ratio decides
(THRESHOLD): it hardly moves from run to run, where wall time moves with whatever else the
machine runs. Otherwise the wall-clock ratio decides, against the looser WALL_THRESHOLD. Both
summaries must come from the same python3 minor version: a faster-starting python3 has a lower
floor, so its ratios run higher. Exit 0 when no case regressed, 1 when one did or the new
summary lacks a baseline case, 2 when the two cannot be compared.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

# Measured spreads behind both thresholds are in bench/README.md.
THRESHOLD = 1.05
WALL_THRESHOLD = 1.25


def minor(version: str) -> str:
    return ".".join(version.split(".")[:2])


def judge(
    base: dict, row: dict, threshold: float, wall_threshold: float
) -> tuple[str, float, bool]:
    """The metric that decides, the growth of its ratio, and whether that is past its limit."""
    if "instructions_ratio" in base and "instructions_ratio" in row:
        growth = row["instructions_ratio"] / base["instructions_ratio"]
        return "instructions", growth, growth > threshold
    growth = row["ratio"] / base["ratio"]
    return "wall", growth, growth > wall_threshold


def compare(
    baseline: dict, new: dict, threshold: float = THRESHOLD, wall_threshold: float = WALL_THRESHOLD
) -> tuple[int, list[str]]:
    """The exit code and the report lines for NEW against BASELINE."""
    if minor(baseline["python"]) != minor(new["python"]):
        return 2, [
            f"cannot compare: the baseline ran on python3 {baseline['python']} and this run on "
            f"{new['python']}; record a baseline on {minor(new['python'])}"
        ]
    lines = []
    if baseline.get("label") != new.get("label"):
        lines.append(
            f"note: baseline from {baseline.get('label')}, this run from {new.get('label')}"
        )
    lines.append(f"{'case':30} {'baseline':>9} {'now':>7} {'change':>8}  decided by")
    code = 0
    for case_id, base in baseline["cases"].items():
        row = new["cases"].get(case_id)
        if row is None:
            lines.append(f"{case_id:30} {base['ratio']:8.2f}x {'-':>7} not measured")
            code = 1
            continue
        metric, growth, slower = judge(base, row, threshold, wall_threshold)
        lines.append(
            f"{case_id:30} {base['ratio']:8.2f}x {row['ratio']:6.2f}x {growth - 1:+8.1%}  "
            f"{metric}{'  SLOWER' if slower else ''}"
        )
        code = code or int(slower)
    for case_id in sorted(new["cases"].keys() - baseline["cases"].keys()):
        lines.append(f"{case_id:30} {'-':>9} {new['cases'][case_id]['ratio']:6.2f}x no baseline")
    if code:
        lines.append(
            f"FAIL: a case grew past {threshold:g}x its baseline instruction ratio "
            f"(or {wall_threshold:g}x its wall-clock ratio), or was not measured"
        )
    return code, lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("baseline", type=pathlib.Path)
    ap.add_argument("new", type=pathlib.Path)
    ap.add_argument("--threshold", type=float, default=THRESHOLD)
    ap.add_argument("--wall-threshold", type=float, default=WALL_THRESHOLD)
    args = ap.parse_args(argv)
    if min(args.threshold, args.wall_threshold) < 1:
        ap.error("a threshold is a growth factor, 1 or more")
    code, lines = compare(
        json.loads(args.baseline.read_text()),
        json.loads(args.new.read_text()),
        args.threshold,
        args.wall_threshold,
    )
    print("\n".join(lines), file=sys.stderr if code == 2 else sys.stdout)
    return code


if __name__ == "__main__":
    sys.exit(main())
