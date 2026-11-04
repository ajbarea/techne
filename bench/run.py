"""Time each hook's whole command with hyperfine, beside the python3 floor, and write a summary.

Usage: uv run python bench/run.py --out FILE [--label NAME] [--runs N] [--warmup N] [--only ID]

The cases, their inputs and the sandbox they run in are tests/test_hook_latency.py's, so this and
the latency budgets time the same commands. For each case one hyperfine call times the floor
(`python3 -c pass`) and the hook's hooks.json command, both through `sh -c` with the case's
input on stdin; hyperfine fails the run when a command exits non-zero. The summary holds, per
case, both medians, their ratio, the spread and (where the machine exposes them) the medians of
retired instructions, plus where and how it was measured. bench/compare.py reads two summaries.

HYPERFINE names the binary; `make bench` sets it from scripts/install_hyperfine.sh.
TECHNE_GUARD_PYTHON picks the python3 the hooks run on, as in the tests.
"""

# research(2026-11): hyperfine 2.0 exports schema 2, a `summary` per metric with its median
# (https://github.com/sharkdp/hyperfine/releases/tag/v2.0.0); warm-up runs and many runs per
# command, compared through the median (https://github.com/sharkdp/hyperfine#usage).

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import platform
import shlex
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

import test_hook_latency as cases  # noqa: E402
from conftest import HOOK_PYTHON  # noqa: E402


def hyperfine_version(binary: str) -> str:
    out = subprocess.run([binary, "--version"], capture_output=True, text=True, check=True)
    return out.stdout.split()[-1]


def python_version() -> str:
    out = subprocess.run(
        [HOOK_PYTHON, "-c", "import sys; print('%d.%d.%d' % sys.version_info[:3])"],
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


def cpu_model() -> str:
    try:
        for line in pathlib.Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or platform.machine()


def median_of(result: dict, metric: str) -> float | None:
    stats = result["summary"].get(metric)
    return None if stats is None else stats["median"]


def time_case(
    binary: str, case: cases.Case, home: pathlib.Path, repo: pathlib.Path, runs: int, warmup: int
) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        stdin = pathlib.Path(tmp) / "stdin.json"
        stdin.write_text(cases.case_stdin(case, repo))
        out = pathlib.Path(tmp) / "hyperfine.json"
        shells = [cases.floor_command(), cases.command(case)]
        subprocess.run(
            [
                binary,
                "--shell=none",
                "--style=none",
                f"--runs={runs}",
                f"--warmup={warmup}",
                f"--input={stdin}",
                f"--export-json={out}",
                *(f"sh -c {shlex.quote(shell)}" for shell in shells),
            ],
            env=cases.case_env(case, home),
            cwd=repo,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        floor, hook = json.loads(out.read_text())["results"]
    floor_s, hook_s = median_of(floor, "time_wall_clock"), median_of(hook, "time_wall_clock")
    assert floor_s and hook_s, f"{case.id}: hyperfine reported no wall-clock median"
    row = {
        "floor_ms": round(floor_s * 1000, 2),
        "hook_ms": round(hook_s * 1000, 2),
        "ratio": round(hook_s / floor_s, 3),
        "hook_stddev_ms": round(hook["summary"]["time_wall_clock"]["stddev"] * 1000, 2),
    }
    floor_i, hook_i = median_of(floor, "instructions"), median_of(hook, "instructions")
    if floor_i and hook_i:
        row["instructions_ratio"] = round(hook_i / floor_i, 3)
    return row


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=pathlib.Path, required=True)
    ap.add_argument("--label", default="local", help="where this ran, such as ci or local")
    ap.add_argument("--runs", type=int, default=30)
    ap.add_argument("--warmup", type=int, default=3)
    ap.add_argument("--only", action="append", default=[], help="a case id (repeatable)")
    args = ap.parse_args(argv)
    binary = os.environ.get("HYPERFINE") or "hyperfine"
    known = {c.id: c for c in cases.CASES}
    unknown = [i for i in args.only if i not in known]
    if unknown:
        ap.error(f"no case named {', '.join(unknown)}; the cases are {', '.join(known)}")
    chosen = [known[i] for i in args.only] or cases.CASES
    results = {}
    with tempfile.TemporaryDirectory() as tmp:
        home, repo = pathlib.Path(tmp) / "home", pathlib.Path(tmp) / "repo"
        home.mkdir()
        repo.mkdir()
        cases.make_sandbox(home, repo)
        if any(c.id == "git_guards-no-git" for c in chosen) and not cases.no_git_input_can_skip(
            repo
        ):
            print(
                f"bench: the temporary folder's path could name git ({repo}), so the no-git case "
                "would time the parsed path; set TMPDIR to a folder whose path does not.",
                file=sys.stderr,
            )
            return 1
        for case in chosen:
            results[case.id] = time_case(binary, case, home, repo, args.runs, args.warmup)
            row = results[case.id]
            print(
                f"{case.id:30} {row['hook_ms']:7.1f} ms  floor {row['floor_ms']:5.1f}  "
                f"{row['ratio']:.2f}x",
                flush=True,
            )
    commit = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    summary = {
        "label": args.label,
        "measured": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commit": commit,
        "python": python_version(),
        "hyperfine": hyperfine_version(binary),
        "cpu": cpu_model(),
        "cpus": os.cpu_count(),
        "runs": args.runs,
        "warmup": args.warmup,
        "cases": results,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
