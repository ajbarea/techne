"""Merge several bench/run.py summaries into one whose cases hold each figure's median.

Usage: uv run python bench/median.py --out FILE SUMMARY [SUMMARY ...]

A baseline taken from one run sits wherever that run fell in the runner's spread; if it was a
fast one, an ordinary later run reads as a slowdown. The median of several runs sits in the
middle. Every summary must come from the same python3 minor version and label and hold the
same cases. Each case's figures are the medians of that figure across the runs (the ratio's
median, not the ratio of the medians); instructions_ratio is kept only when every run has it.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import statistics
import sys

FIGURES = ("floor_ms", "hook_ms", "ratio", "hook_stddev_ms", "instructions_ratio")


def minor(version: str) -> str:
    return ".".join(version.split(".")[:2])


def median_summary(summaries: list[dict]) -> dict:
    """The merged summary; ValueError when the summaries cannot be merged."""
    if len(summaries) < 2:
        raise ValueError("a median needs two or more summaries")
    first = summaries[0]
    for s in summaries[1:]:
        for key, same in (("python", minor), ("label", str), ("hyperfine", str)):
            if same(s[key]) != same(first[key]):
                raise ValueError(f"{key} differs: {first[key]} and {s[key]}")
        if s["cases"].keys() != first["cases"].keys():
            raise ValueError("the summaries hold different cases")
    cases = {}
    for case_id in first["cases"]:
        rows = [s["cases"][case_id] for s in summaries]
        cases[case_id] = {
            fig: round(statistics.median(r[fig] for r in rows), 3)
            for fig in FIGURES
            if all(fig in r for r in rows)
        }
    return {
        "label": first["label"],
        "measured": max(s["measured"] for s in summaries),
        "commit": "; ".join(sorted({s["commit"] for s in summaries})),
        "python": first["python"],
        "hyperfine": first["hyperfine"],
        "cpu": "; ".join(sorted({s["cpu"] for s in summaries})),
        "cpus": first["cpus"],
        "runs": first["runs"],
        "warmup": first["warmup"],
        "median_of": [f"{s['measured']} on {s['cpu']}" for s in summaries],
        "cases": cases,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=pathlib.Path, required=True)
    ap.add_argument("summaries", nargs="+", type=pathlib.Path)
    args = ap.parse_args(argv)
    try:
        merged = median_summary([json.loads(p.read_text()) for p in args.summaries])
    except ValueError as e:
        print(f"median: {e}", file=sys.stderr)
        return 2
    args.out.write_text(json.dumps(merged, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
