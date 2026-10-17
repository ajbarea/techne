#!/usr/bin/env python3
"""Run the heuresis gold set: one headless Claude Code triage per case and run, graded from the
files it writes. Uses your Claude plan; never touches your real ideas repository, which
--guard-repo watches (the run stops if its refs or any file content change).
Results default to $XDG_STATE_HOME/heuresis-gold (~/.local/state/heuresis-gold).

Usage:
  heuresis_gold.py run (--guard-repo DIR | --no-guard) [--cases FILE]... [--runs N]
                       [--case GLOB]... [--out DIR] [--plugin-dir DIR] [--timeout SECONDS]
                       [--model NAME]
  heuresis_gold.py report RESULTS_DIR
"""

from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "heuresis"
sys.path.insert(0, str(PLUGIN))
from heuresis import gold  # noqa: E402

DEFAULT_CASES = PLUGIN / "gold" / "cases.yaml"
# A full triage took about two minutes in the phase 1 live run; twenty minutes leaves room for
# slow sources and retries without letting a stuck session hold the whole set.
DEFAULT_TIMEOUT = 1200
# Seconds a timed-out session gets to exit on SIGTERM before its process group is killed.
TERM_GRACE = 5


def default_out() -> Path:
    """Outside any repository, so the headless session's cwd loads no repo CLAUDE.md or settings."""
    state = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(state) / "heuresis-gold"


class GuardTripped(Exception):
    """A run changed the guard repository."""


def heuresis(*args: str, stdin: str | None = None) -> str:
    """Run the plugin CLI on this interpreter; inherited UV_* or VIRTUAL_ENV cannot redirect it."""
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(filter(None, [str(PLUGIN), os.environ.get("PYTHONPATH")])),
    }
    done = subprocess.run(
        [sys.executable, "-m", "heuresis", *args],
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    if done.returncode:
        raise RuntimeError(f"heuresis {args[0]} failed: {done.stderr.strip()}")
    return done.stdout.strip()


def git(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
    done = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=False, env=env
    )
    if done.returncode:
        raise RuntimeError(f"git {args[0]} failed in {repo}: {done.stderr.strip()}")
    return done.stdout


def check_guard(path: Path) -> Path:
    """The guard repository's resolved top level; raises ValueError unless path is exactly that."""
    resolved = path.resolve()
    done = subprocess.run(
        ["git", "-C", str(resolved), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode or Path(done.stdout.strip()).resolve() != resolved:
        raise ValueError(f"--guard-repo {path} is not the top level of a git repository")
    return resolved


def snapshot(repo: Path) -> str:
    """Everything a run could change in repo: refs, the staged index, and every file's content.

    The content tree comes from a throwaway index (`add -A -f` then `write-tree`), so edits to
    files that were already modified, untracked or ignored still change it, and the repository's
    own index is never touched.
    """
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(tmp) / "index")}
        has_head = (
            subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "--verify", "-q", "HEAD"],
                capture_output=True,
                check=False,
            ).returncode
            == 0
        )
        if has_head:
            git(repo, "read-tree", "HEAD", env=env)
        git(repo, "add", "-A", "-f", ".", env=env)
        tree = git(repo, "write-tree", env=env).strip()
    head = git(repo, "rev-parse", "HEAD").strip() if has_head else ""
    return "\n".join([head, tree, git(repo, "for-each-ref"), git(repo, "ls-files", "-s")])


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


def watch(guard: Path) -> str:
    try:
        return snapshot(guard)
    except RuntimeError as exc:
        raise GuardTripped(f"cannot snapshot the guard repository {guard}: {exc}") from exc


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
    printed = heuresis("capture", "--ideas", str(ideas), "--text", "-", stdin=case.idea)
    if not printed.strip():
        raise RuntimeError("capture printed no id")
    return ideas, repos, printed.splitlines()[-1]


def run_session(cmd: list[str], cwd: Path, timeout: int) -> tuple[str, str, int | None]:
    """Run cmd in its own process group; on timeout stop the whole group.

    Returns stdout, stderr and the exit code, or None for a timeout. Children the session started
    die with it, so none keeps writing into the work folder or holds the output pipe open.
    """
    # research(2026-10): code.claude.com/docs/en/env-vars, CLAUDE_CODE_DISABLE_AUTO_MEMORY=1
    # stops the session creating or loading auto-memory files, so no memory leaks between runs.
    env = {**os.environ, "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"}
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        start_new_session=True,
    )
    try:
        out, err = proc.communicate(timeout=timeout)
        return out, err, proc.returncode
    except subprocess.TimeoutExpired:
        pass
    os.killpg(proc.pid, signal.SIGTERM)
    try:
        out, err = proc.communicate(timeout=TERM_GRACE)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        out, err = proc.communicate()
    return out or "", err or "", None


def triage(
    ideas: Path, repos: Path, idea_id: str, log: Path, args
) -> tuple[str, dict | None, str | None]:
    """Run one triage; returns the error ("" if none), the result event and the plugin path."""
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
        "--strict-mcp-config",
    ]
    if args.plugin_dir:
        cmd += ["--plugin-dir", str(args.plugin_dir)]
    if args.model:
        cmd += ["--model", args.model]
    out, err, code = run_session(cmd, ideas.parent, args.timeout)
    log.write_text(out)
    log.with_suffix(".stderr").write_text(err)
    if code is None:
        return f"timed out after {args.timeout}s", None, None
    init, result = parse_stream(out)
    names = [(p.get("name"), p.get("path")) for p in (init or {}).get("plugins", [])]
    wanted = [n for n in names if n[0] == "heuresis"]
    paths = [str(p) for _, p in wanted if p]
    plugin_path = next(
        (
            p
            for p in paths
            if args.plugin_dir and Path(p).resolve() == Path(args.plugin_dir).resolve()
        ),
        paths[0] if paths and not args.plugin_dir else None,
    )
    if not wanted or (
        args.plugin_dir
        and str(Path(args.plugin_dir).resolve())
        not in {str(Path(p).resolve()) for _, p in wanted if p}
    ):
        return "heuresis plugin did not load", result, plugin_path
    if code:
        return f"claude exited {code}", result, plugin_path
    if result is None:
        return "no result in the stream", None, plugin_path
    if result.get("is_error"):
        return (
            f"claude reported an error: {str(result.get('result', ''))[:200]}",
            result,
            plugin_path,
        )
    return "", result, plugin_path


def load_all(files: list[Path]) -> list[gold.Case]:
    """Every case from the files in order; one id in two files is an error naming both."""
    cases: list[gold.Case] = []
    origin: dict[str, Path] = {}
    for f in files:
        for c in gold.load_cases(f):
            if c.id in origin:
                raise gold.GoldError(f"case id {c.id} is in both {origin[c.id]} and {f}")
            origin[c.id] = f
            cases.append(c)
    return cases


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
    guard = None
    if args.guard_repo:
        try:
            guard = check_guard(args.guard_repo)
        except ValueError as exc:
            print(f"heuresis_gold: {exc}", file=sys.stderr)
            return 2
    try:
        cases = selected(load_all(args.cases), args.case)
    except (gold.GoldError, OSError) as exc:
        print(f"heuresis_gold: {exc}", file=sys.stderr)
        return 2
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    res = args.out / stamp
    (res / "logs").mkdir(parents=True)
    (res / "grades.jsonl").write_text("")
    files = [str(Path(f).resolve()) for f in args.cases]
    (res / "cases.json").write_text(json.dumps({"ids": [c.id for c in cases], "files": files}))

    def record(grade: gold.RunGrade, plugin_path: str | None = None) -> None:
        with (res / "grades.jsonl").open("a") as fh:
            fh.write(json.dumps({**grade.to_dict(), "plugin_path": plugin_path}) + "\n")
        print(
            f"{grade.case} run {grade.run}: {grade.state or 'error'}"
            f"{' (' + grade.error + ')' if grade.error else ''}",
            flush=True,
        )

    try:
        before = watch(guard) if guard else ""
        for case in cases:
            for n in range(1, args.runs + 1):
                work = res / "work" / f"{case.id}-{n}"
                try:
                    ideas, repos, idea_id = prepare(work, case)
                except (OSError, RuntimeError) as exc:
                    record(
                        gold.grade_run(case, n, work / "ideas", "", error=f"setup failed: {exc}")
                    )
                    continue
                error, result, plugin_path = triage(
                    ideas, repos, idea_id, res / "logs" / f"{case.id}-{n}.jsonl", args
                )
                if guard and watch(guard) != before:
                    raise GuardTripped(
                        f"run {case.id}-{n} changed the guard repository {guard}; "
                        "stopping. Inspect it with git status before anything else."
                    )
                record(
                    gold.grade_run(case, n, ideas, idea_id, error=error, meta=result), plugin_path
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
    p.add_argument("--out", type=Path, default=default_out())
    p.add_argument("--plugin-dir", type=Path)
    guard = p.add_mutually_exclusive_group(required=True)
    guard.add_argument(
        "--guard-repo", type=Path, help="your real ideas repository; must not change"
    )
    guard.add_argument("--no-guard", action="store_true", help="run without a guard repository")
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
