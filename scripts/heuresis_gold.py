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
from heuresis import gold  # noqa: E402

DEFAULT_CASES = PLUGIN / "gold" / "cases.yaml"
# A full triage took about two minutes in the phase 1 live run; twenty minutes leaves room for
# slow sources and retries without letting a stuck session hold the whole set.
DEFAULT_TIMEOUT = 1200


class GuardTripped(Exception):
    """A run changed the guard repository."""


def heuresis(*args: str, stdin: str | None = None) -> str:
    done = subprocess.run(
        ["uv", "run", "--quiet", "--directory", str(PLUGIN), "python", "-m", "heuresis", *args],
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode:
        raise RuntimeError(f"heuresis {args[0]} failed: {done.stderr.strip()}")
    return done.stdout.strip()


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout


def snapshot(repo: Path) -> str:
    head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    ).stdout.strip()
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
    heuresis(
        "init", str(ideas), "--repos-root", str(repos), "--techne-toml", str(work / "none.toml")
    )
    for key, value in (
        ("user.email", "gold@example.com"),
        ("user.name", "gold"),
        ("commit.gpgsign", "false"),
    ):
        git(ideas, "config", key, value)
    git(ideas, "add", "-A")
    git(ideas, "commit", "-qm", "init")
    idea_id = heuresis("capture", "--ideas", str(ideas), "--text", "-", stdin=case.idea)
    return ideas, repos, idea_id.splitlines()[-1]


def triage(ideas: Path, repos: Path, idea_id: str, log: Path, args) -> tuple[str, dict | None]:
    prompt = f"/heuresis:idea --ideas {ideas} --repos {repos} --triage {idea_id}"
    cmd = [
        "claude",
        "-p",
        prompt,
        "--output-format",
        "stream-json",
        "--verbose",
        "--permission-mode",
        "bypassPermissions",
    ]
    if args.plugin_dir:
        cmd += ["--plugin-dir", str(args.plugin_dir)]
    if args.model:
        cmd += ["--model", args.model]
    try:
        done = subprocess.run(
            cmd, cwd=ideas.parent, capture_output=True, text=True, timeout=args.timeout, check=False
        )
    except subprocess.TimeoutExpired as exc:
        log.write_text(exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or ""))
        return f"timed out after {args.timeout}s", None
    log.write_text(done.stdout)
    init, result = parse_stream(done.stdout)
    names = [(p.get("name"), p.get("path")) for p in (init or {}).get("plugins", [])]
    wanted = [n for n in names if n[0] == "heuresis"]
    if not wanted or (
        args.plugin_dir
        and str(Path(args.plugin_dir).resolve())
        not in {str(Path(p).resolve()) for _, p in wanted if p}
    ):
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
    grades = [
        gold.RunGrade.from_dict(json.loads(line))
        for line in (res / "grades.jsonl").read_text().splitlines()
        if line.strip()
    ]
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
                error, result = triage(
                    ideas, repos, idea_id, res / "logs" / f"{case.id}-{n}.jsonl", args
                )
                if guard and snapshot(guard) != before:
                    raise GuardTripped(
                        f"run {case.id}-{n} changed the guard repository {guard}; "
                        "stopping. Inspect it with git status before anything else."
                    )
                grade = gold.grade_run(case, n, ideas, idea_id, error=error, meta=result)
                with (res / "grades.jsonl").open("a") as fh:
                    fh.write(json.dumps(grade.to_dict()) + "\n")
                print(
                    f"{case.id} run {n}: {grade.state or 'error'}"
                    f"{' (' + grade.error + ')' if grade.error else ''}",
                    flush=True,
                )
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
