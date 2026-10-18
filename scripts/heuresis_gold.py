#!/usr/bin/env python3
"""Run the heuresis gold set: one headless Claude Code triage per case and run, graded from the
files it writes. Uses your Claude plan; never touches your real ideas repository, which
--guard-repo watches (the run stops if its refs or any file content change).
With --plugin-dir, the installed heuresis plugins are switched off for the sessions (--settings)
and a run whose session did not load heuresis from that folder is an error.
Results default to $XDG_STATE_HOME/heuresis-gold (~/.local/state/heuresis-gold).

Usage:
  heuresis_gold.py run (--guard-repo DIR | --no-guard) [--cases FILE]... [--runs N]
                       [--case GLOB]... [--out DIR] [--plugin-dir DIR] [--timeout SECONDS]
                       [--model NAME]
  heuresis_gold.py report RESULTS_DIR [--cases FILE]...
  heuresis_gold.py regrade RESULTS_DIR... --into OUT_DIR [--cases FILE]...
"""

from __future__ import annotations

import argparse
import dataclasses
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
# `claude plugin list` starts no session; a minute is far past a healthy listing.
PLUGIN_LIST_TIMEOUT = 60


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


def code_identity(folder: Path | None) -> dict:
    """The commit of the repository holding the plugin folder, whether anything under the folder
    is uncommitted (git status --porcelain), and the version its manifest declares.

    Each is None when it cannot be read: no folder, no repository, no version in plugin.json.
    """
    state: dict = {"commit": None, "dirty": None, "plugin_version": None}
    if folder is None or not folder.is_dir():
        return state
    try:
        version = json.loads((folder / ".claude-plugin" / "plugin.json").read_text())["version"]
        state["plugin_version"] = version if isinstance(version, str) else None
    except (OSError, ValueError, KeyError, TypeError):
        pass
    try:
        state["commit"] = git(folder, "rev-parse", "HEAD").strip()
        state["dirty"] = bool(git(folder, "status", "--porcelain", "--", ".").strip())
    except RuntimeError:
        state["commit"] = state["dirty"] = None
    return state


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


def installed_heuresis() -> list[str] | None:
    """Ids like heuresis@techne of the installed heuresis plugins, or None when the list fails.

    `claude plugin list --json` reads the installed set and starts no session. It runs from a
    scratch folder, the same place the sessions run, so only user-scope plugins show.
    """
    try:
        with tempfile.TemporaryDirectory() as tmp:
            done = subprocess.run(
                ["claude", "plugin", "list", "--json"],
                cwd=tmp,
                capture_output=True,
                text=True,
                check=False,
                timeout=PLUGIN_LIST_TIMEOUT,
            )
        if done.returncode:
            return None
        entries = json.loads(done.stdout)
        return [
            e["id"]
            for e in entries
            if isinstance(e, dict)
            and isinstance(e.get("id"), str)
            and e["id"].split("@")[0] == "heuresis"
        ]
    except (OSError, subprocess.TimeoutExpired, ValueError, TypeError):
        return None


def disable_settings(ids: list[str]) -> str | None:
    """The --settings JSON that turns the installed heuresis copies off, or None when none are."""
    return json.dumps({"enabledPlugins": dict.fromkeys(ids, False)}) if ids else None


def triage(
    ideas: Path, repos: Path, idea_id: str, log: Path, args, settings: str | None = None
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
    if settings:
        cmd += ["--settings", settings]
    if args.model:
        cmd += ["--model", args.model]
    out, err, code = run_session(cmd, ideas.parent, args.timeout)
    log.write_text(out)
    log.with_suffix(".stderr").write_text(err)
    if code is None:
        return f"timed out after {args.timeout}s", None, None
    init, result = parse_stream(out)
    paths = [
        str(p["path"])
        for p in (init or {}).get("plugins", [])
        if p.get("name") == "heuresis" and p.get("path")
    ]
    if args.plugin_dir:
        mine = str(Path(args.plugin_dir).resolve())
        plugin_path = next((p for p in paths if str(Path(p).resolve()) == mine), None)
        if plugin_path is None:
            return "heuresis plugin from --plugin-dir did not load", result, None
    else:
        plugin_path = paths[0] if paths else None
        if plugin_path is None:
            return "heuresis plugin did not load", result, None
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


def read_grades(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def write_report(res: Path, cases: list[gold.Case]) -> None:
    grades = [gold.RunGrade.from_dict(d) for d in read_grades(res / "grades.jsonl")]
    summary = gold.summarize(grades, [c for c in cases if any(g.case == c.id for g in grades)])
    (res / "summary.json").write_text(json.dumps(summary, indent=2))
    (res / "summary.md").write_text(gold.render_markdown(summary))


def read_meta(res: Path) -> tuple[list[str], list[str]]:
    """The case ids and case files a results folder recorded."""
    meta = json.loads((res / "cases.json").read_text())
    return list(meta["ids"]), list(meta["files"])


def case_pool(files: list[Path]) -> dict[str, gold.Case]:
    return {c.id: c for f in files if f.is_file() for c in gold.load_cases(f)}


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
    settings = None
    if args.plugin_dir:
        # The installed copy may predate the branch's flags; with both loaded the session would
        # see two heuresis plugins, so the installed ones are switched off for these sessions.
        ids = installed_heuresis()
        if ids is None:
            print(
                "heuresis_gold: warning: could not list installed plugins; running without "
                "--settings, so an installed heuresis may load beside --plugin-dir",
                file=sys.stderr,
            )
        else:
            settings = disable_settings(ids)
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    res = args.out / stamp
    (res / "logs").mkdir(parents=True)
    (res / "grades.jsonl").write_text("")
    files = [str(Path(f).resolve()) for f in args.cases]
    (res / "cases.json").write_text(json.dumps({"ids": [c.id for c in cases], "files": files}))

    def record(grade: gold.RunGrade, plugin_path: str | None = None) -> None:
        # The folder the session loaded is the code under test; --plugin-dir was checked to be it.
        loaded = args.plugin_dir or (Path(plugin_path) if plugin_path else None)
        grade = dataclasses.replace(grade, **code_identity(loaded))
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
                    ideas, repos, idea_id, res / "logs" / f"{case.id}-{n}.jsonl", args, settings
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
    ids, recorded = read_meta(args.results)
    pool = case_pool([Path(f) for f in recorded] + list(args.cases))
    write_report(args.results, [pool[i] for i in ids if i in pool])
    print(args.results / "summary.md")
    return 0


def regrade_folder(
    res: Path, name: str, case: gold.Case, n: int, original: dict | None
) -> tuple[gold.RunGrade, str | None]:
    """Grade one work folder again from the files in it; returns the grade and its plugin path.

    A run that never triaged keeps the error the original run recorded, which names the cause.
    """
    work = res / "work" / name
    ideas = work / "ideas"
    log = res / "logs" / f"{name}.jsonl"
    meta = parse_stream(log.read_text(errors="replace"))[1] if log.is_file() else None
    kept = (original or {}).get("error") or ""
    found = sorted((ideas / "ideas").glob("*.md")) if (ideas / "ideas").is_dir() else []
    plugin_path = (original or {}).get("plugin_path")
    problem = f"expected one idea file, found {len(found)}"
    if len(found) == 1:
        grade = gold.grade_run(case, n, ideas, found[0].stem, meta=meta)
        if not grade.error:
            return grade, plugin_path
        problem = grade.error
    return gold.grade_run(case, n, ideas, "", error=kept or problem, meta=meta), plugin_path


def regrade(args) -> int:
    missing = [d for d in args.results if not d.is_dir()]
    if missing:
        print(f"heuresis_gold: results folder not found: {missing[0]}", file=sys.stderr)
        return 2
    out = args.into.resolve()
    if any(d.resolve() == out for d in args.results):
        print(f"heuresis_gold: --into {args.into} is one of the results folders", file=sys.stderr)
        return 2
    order: list[str] = []
    files: list[str] = []
    for res in args.results:
        try:
            ids, recorded = read_meta(res)
        except (OSError, ValueError, KeyError):
            continue
        order += [i for i in ids if i not in order]
        files += [f for f in recorded if f not in files]
    pool = case_pool([Path(f) for f in files] + list(args.cases))
    merged: dict[tuple[str, int], dict] = {}
    for res in args.results:
        try:
            originals = {(d["case"], d["run"]): d for d in read_grades(res / "grades.jsonl")}
        except (OSError, ValueError, KeyError):
            originals = {}
        for work in sorted(p for p in (res / "work").glob("*") if p.is_dir()):
            case_id, _, run_no = work.name.rpartition("-")
            if case_id not in pool or not run_no.isdigit():
                print(f"heuresis_gold: skipping {work}: not a run of a known case", file=sys.stderr)
                continue
            n = int(run_no)
            grade, plugin_path = regrade_folder(
                res, work.name, pool[case_id], n, originals.get((case_id, n))
            )
            key = (case_id, n)
            # A later folder replaces an earlier grade only with a run that did not fail.
            if key not in merged or not grade.error:
                merged[key] = {**grade.to_dict(), "plugin_path": plugin_path}
    if not merged:
        print("heuresis_gold: no run folders to grade", file=sys.stderr)
        return 2
    order += [c for c in dict.fromkeys(c for c, _ in merged) if c not in order]
    rows = sorted(merged.values(), key=lambda d: (order.index(d["case"]), d["run"]))
    out.mkdir(parents=True, exist_ok=True)
    (out / "grades.jsonl").write_text("".join(json.dumps(d) + "\n" for d in rows))
    ids = [i for i in order if i in pool]
    case_files = dict.fromkeys(str(Path(f).resolve()) for f in [*files, *args.cases])
    (out / "cases.json").write_text(json.dumps({"ids": ids, "files": list(case_files)}))
    write_report(out, [pool[i] for i in ids])
    print(out / "summary.md")
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
    p = sub.add_parser("regrade")
    p.add_argument("results", type=Path, nargs="+")
    p.add_argument("--into", type=Path, required=True)
    p.add_argument("--cases", type=Path, action="append", default=[])
    args = parser.parse_args(argv)
    if args.command == "regrade":
        return regrade(args)
    if args.command == "run":
        args.cases = args.cases or [DEFAULT_CASES]
        return run(args)
    return report(args)


if __name__ == "__main__":
    sys.exit(main())
