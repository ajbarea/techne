"""Compare a bench/run.py summary with a baseline and fail when a hook got slower.

Usage: uv run python bench/compare.py BASELINE NEW [--threshold X] [--wall-threshold X]

Each case is judged by its ratio to the python3 floor, so a slower or faster machine moves both
sides alike. A case fails when its wall-clock ratio grew past WALL_THRESHOLD, or, when both
summaries carry retired-instruction counts, when its instruction ratio grew past the tighter
THRESHOLD: instructions hardly move from run to run, but they do not count time spent waiting
(a sleep, a lock, a network call), so wall time is always checked too. Both summaries must come
from the same python3 minor version: a faster-starting python3 has a lower floor, so its ratios
run higher. Exit 0 when no case regressed, 1 when one did or the new
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
) -> list[tuple[str, float, bool]]:
    """Per metric checked: its name, the growth of its ratio, and whether that is past its limit.
    Wall time always; instructions too when both sides counted them."""
    growth = row["ratio"] / base["ratio"]
    checked = [("wall", growth, growth > wall_threshold)]
    if "instructions_ratio" in base and "instructions_ratio" in row:
        growth = row["instructions_ratio"] / base["instructions_ratio"]
        checked.append(("instructions", growth, growth > threshold))
    return checked


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
    if baseline.get("cpu") != new.get("cpu"):
        lines.append(
            f"note: baseline on {baseline.get('cpu')}, this run on {new.get('cpu')}; ratios to "
            "the floor move less than times, but not by nothing"
        )
    lines.append(f"{'case':30} {'baseline':>9} {'now':>7}  change")
    code = 0
    for case_id, base in baseline["cases"].items():
        row = new["cases"].get(case_id)
        if row is None:
            lines.append(f"{case_id:30} {base['ratio']:8.2f}x {'-':>7} not measured")
            code = 1
            continue
        checked = judge(base, row, threshold, wall_threshold)
        change = ", ".join(
            f"{growth - 1:+.1%} {metric}{' SLOWER' if past else ''}"
            for metric, growth, past in checked
        )
        lines.append(f"{case_id:30} {base['ratio']:8.2f}x {row['ratio']:6.2f}x  {change}")
        code = code or int(any(past for _, _, past in checked))
    for case_id in sorted(new["cases"].keys() - baseline["cases"].keys()):
        lines.append(f"{case_id:30} {'-':>9} {new['cases'][case_id]['ratio']:6.2f}x no baseline")
    if code:
        lines.append(
            f"FAIL: a case grew past {wall_threshold:g}x its baseline wall-clock ratio or "
            f"{threshold:g}x its instruction ratio, or was not measured"
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
