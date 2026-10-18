#!/usr/bin/env python3
"""Run the heuresis gold set: one headless Claude Code triage per case and run, graded from the
files it writes. Uses your Claude plan; never touches your real ideas repository, which
--guard-repo watches: after each run the guard is compared with its snapshot from before, and
the set stops if its refs, any file's content, its local git config, hooks or info changed. The
guard detects a change after the fact; it does not prevent one.
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
import hashlib
import json
import os
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import IO, NamedTuple, TextIO

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
# Seconds the stream must stay silent after a `result` event, with the verdict applied, before the
# still-running session is ended; a session that used background subagents may never exit itself:
# https://github.com/anthropics/claude-code/issues/30008 and
# https://github.com/anthropics/claude-code/issues/35262
SETTLE_SECONDS = 60
# How often run_session looks at the clock, the stream and the process.
POLL_SECONDS = 0.2
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


def git_dir_digest(common: Path) -> str:
    """Path, mode and content hash of everything under .git/hooks and .git/info."""
    lines = []
    for sub in ("hooks", "info"):
        base = common / sub
        for path in sorted(base.rglob("*")) if base.is_dir() else []:
            mode = path.lstat().st_mode & 0o7777
            if path.is_symlink():
                body = f"link {os.readlink(path)}"
            elif path.is_file():
                body = hashlib.sha256(path.read_bytes()).hexdigest()
            else:
                body = "dir"
            lines.append(f"{path.relative_to(common)} {mode:o} {body}")
    return "\n".join(lines)


def work_tree_of(path: Path) -> Path | None:
    """The top of the git work tree that holds path (which need not exist yet), or None."""
    near = path
    while not near.exists():
        near = near.parent
    done = subprocess.run(
        ["git", "-C", str(near), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    return Path(done.stdout.strip()) if done.returncode == 0 and done.stdout.strip() else None


def results_stamp() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")


def new_results_dir(out: Path) -> Path:
    """A fresh <out>/<UTC time>-<random> folder with logs/ in it; two runs never share one."""
    while True:
        res = out / f"{results_stamp()}-{secrets.token_hex(3)}"
        try:
            res.mkdir(parents=True)
        except FileExistsError:
            continue
        (res / "logs").mkdir()
        return res


def snapshot(repo: Path) -> str:
    """Everything a run could change in repo: refs, the staged index, every file's content, the
    repository's local config, and its hooks and info folders.

    The content tree comes from a throwaway index (`add -A -f` then `write-tree`), so edits to
    files that were already modified, untracked or ignored still change it. The tree's objects go
    to a temporary object directory with the real one as an alternate, so taking a snapshot
    writes nothing into the guarded repository, its index included.
    """
    common = (repo / git(repo, "rev-parse", "--git-common-dir").strip()).resolve()
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "objects").mkdir()
        env = {
            **os.environ,
            "GIT_INDEX_FILE": str(Path(tmp) / "index"),
            "GIT_OBJECT_DIRECTORY": str(Path(tmp) / "objects"),
            "GIT_ALTERNATE_OBJECT_DIRECTORIES": str(common / "objects"),
        }
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
    return "\n".join(
        [
            head,
            tree,
            git(repo, "for-each-ref"),
            git(repo, "ls-files", "-s"),
            git(repo, "config", "--local", "--list"),
            git_dir_digest(common),
        ]
    )


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
    except (RuntimeError, OSError) as exc:
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


class Session(NamedTuple):
    stdout: str
    stderr: str
    # The exit code; None for a session stopped at the timeout.
    code: int | None
    # True when the session was ended because it settled (see SETTLE_SECONDS); code is then the
    # signal that ended it.
    settled: bool = False
    # Why the log copy of stdout could not be written, or "".
    log_error: str = ""


class Pump(threading.Thread):
    """Reads one pipe line by line, keeping the lines, when the last arrived, whether the newest
    stream event is a `result`, and optionally a copy in a file that grows as the lines arrive.

    A copy that cannot be opened or written is dropped, the pipe is still drained, and the
    failure is kept in log_error.
    """

    def __init__(self, pipe: IO[str], copy: Path | None = None) -> None:
        super().__init__(daemon=True)
        self.pipe = pipe
        self.copy = copy
        self.lines: list[str] = []
        self.last_line = time.monotonic()
        self.ended_on_result = False
        self.log_error = ""

    def run(self) -> None:
        sink: TextIO | None = None
        try:
            try:
                sink = self.copy.open("w") if self.copy else None
            except OSError as exc:
                self.log_error = str(exc)
            for line in iter(self.pipe.readline, ""):
                self.lines.append(line)
                self.last_line = time.monotonic()
                self.ended_on_result = is_result(line)
                if sink:
                    try:
                        sink.write(line)
                        sink.flush()
                    except OSError as exc:
                        self.log_error = str(exc)
                        self.drop(sink)
                        sink = None
        except (OSError, ValueError):
            pass  # the pipe was closed under the reader
        finally:
            if sink:
                self.drop(sink)

    @staticmethod
    def drop(sink: TextIO) -> None:
        try:
            sink.close()
        except OSError:
            pass  # the failure that made us drop it is already recorded


def is_result(line: str) -> bool:
    try:
        event = json.loads(line)
    except ValueError:
        return False
    return isinstance(event, dict) and event.get("type") == "result"


def close_ended(pumps: tuple[Pump, ...]) -> None:
    """Close the pipe of each pump that has finished. A pipe whose reader is still blocked on it
    is left open: closing it would wait on the reader, which waits on a descendant holding it."""
    for pump in pumps:
        if not pump.is_alive():
            pump.pipe.close()


def end_group(proc: subprocess.Popen, pumps: tuple[Pump, ...]) -> None:
    """SIGTERM the session's process group, SIGKILL it after TERM_GRACE, and let the pumps drain."""
    kill_group(proc.pid, signal.SIGTERM)
    try:
        proc.wait(timeout=TERM_GRACE)
    except subprocess.TimeoutExpired:
        kill_group(proc.pid, signal.SIGKILL)
        proc.wait()
    for pump in pumps:
        pump.join(TERM_GRACE)
    if any(p.is_alive() for p in pumps):
        # A child that ignored SIGTERM still holds a pipe open.
        kill_group(proc.pid, signal.SIGKILL)
        for pump in pumps:
            pump.join(TERM_GRACE)


def run_session(
    cmd: list[str],
    cwd: Path,
    timeout: int,
    log: Path | None = None,
    verdict_applied: Callable[[], bool] | None = None,
) -> Session:
    """Run cmd in its own process group; stop the whole group at the timeout, or earlier once the
    session has settled.

    Stdout is read as it arrives and copied to log. A session has settled when it is still
    running, its newest stream event is a `result`, nothing has arrived for SETTLE_SECONDS and
    verdict_applied() is true; it is then stopped like a timeout and the run counts as finished.
    A session that exited keeps its exit code, even if a child of it kept a pipe open and the
    group had to be stopped to release it. Children the session started die with it, so none
    keeps writing into the work folder or holds a pipe open.
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
    assert proc.stdout is not None and proc.stderr is not None
    out, err = Pump(proc.stdout, log), Pump(proc.stderr)
    pumps = (out, err)
    out.start()
    err.start()
    deadline = time.monotonic() + timeout
    try:
        stopped = None
        # Ends when the session exits, however its pipes stand: one that closed both and runs on
        # is still waited for, up to the deadline.
        while True:
            try:
                proc.wait(timeout=POLL_SECONDS)
            except subprocess.TimeoutExpired:
                pass
            if proc.returncode is not None:
                break
            if time.monotonic() >= deadline:
                stopped = "timeout"
                break
            if (
                verdict_applied
                and out.ended_on_result
                and time.monotonic() - out.last_line >= SETTLE_SECONDS
                and proc.poll() is None
                and verdict_applied()
            ):
                stopped = "settled"
                break
        if stopped:
            end_group(proc, pumps)
        else:
            for pump in pumps:
                pump.join(TERM_GRACE)  # an exited session's pipes drain
            if any(p.is_alive() for p in pumps):
                end_group(proc, pumps)  # a child of the session holds a pipe open
        close_ended(pumps)
        code = None if stopped == "timeout" else proc.returncode
        return Session(
            "".join(out.lines), "".join(err.lines), code, stopped == "settled", out.log_error
        )
    except BaseException:
        # An interrupt or any other failure must not leave the session writing in the background.
        kill_group(proc.pid, signal.SIGKILL)
        proc.wait()
        for pump in pumps:
            pump.join(TERM_GRACE)
        close_ended(pumps)
        raise


def kill_group(pid: int, sig: int) -> None:
    """Signal the session's process group; one that has already gone is not an error."""
    try:
        os.killpg(pid, sig)
    except ProcessLookupError:
        pass


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
) -> tuple[str, dict | None, str | None, bool]:
    """Run one triage; returns the error ("" if none), the result event, the plugin path and
    whether the runner ended the session after its verdict was applied."""
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
    session = run_session(
        cmd, ideas.parent, args.timeout, log, lambda: gold.verdict_applied(ideas, idea_id)
    )
    log.with_suffix(".stderr").write_text(session.stderr)
    error, result, plugin_path = session_outcome(session, args)
    if session.log_error:
        error = "; ".join(filter(None, [error, f"log not written: {session.log_error}"]))
    return error, result, plugin_path, session.settled


def session_outcome(session: Session, args) -> tuple[str, dict | None, str | None]:
    """What a finished session amounts to: the error ("" if none), the result event and the path
    of the heuresis plugin it loaded."""
    if session.code is None:
        return f"timed out after {args.timeout}s", None, None
    init, result = parse_stream(session.stdout)
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
    # A settled session was ended by the runner, so its exit code says nothing.
    if session.code and not session.settled:
        return f"claude exited {session.code}", result, plugin_path
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
    grades = []
    for number, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            grades.append(json.loads(line))
        except ValueError as exc:
            raise gold.GoldError(f"{path}:{number} is not a grade line: {exc}") from exc
    return grades


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
    """The cases of every file that exists; a missing file warns, a repeated id is an error."""
    present: list[Path] = []
    for f in dict.fromkeys(Path(f).resolve() for f in files):
        if f.is_file():
            present.append(f)
        else:
            print(f"heuresis_gold: warning: cases file {f} not found; skipped", file=sys.stderr)
    return {c.id: c for c in load_all(present)}


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
    if guard and (args.out == guard or guard in args.out.parents):
        print(f"heuresis_gold: --out {args.out} is inside the guard repository", file=sys.stderr)
        return 2
    top = work_tree_of(args.out)
    if top:
        print(
            f"heuresis_gold: --out {args.out} is inside the git work tree {top}; a session started "
            "there would load its CLAUDE.md and settings. Use a folder outside any repository.",
            file=sys.stderr,
        )
        return 2
    try:
        cases = selected(load_all(args.cases), args.case)
    except (gold.GoldError, OSError) as exc:
        print(f"heuresis_gold: {exc}", file=sys.stderr)
        return 2
    if not cases:
        what = f"matches --case {' '.join(args.case)}" if args.case else "is in the cases files"
        print(f"heuresis_gold: no case {what}", file=sys.stderr)
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
    res = new_results_dir(args.out)
    (res / "grades.jsonl").write_text("")
    files = [str(f) for f in args.cases]
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

    before = None
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
                error, result, plugin_path, stopped = triage(
                    ideas, repos, idea_id, res / "logs" / f"{case.id}-{n}.jsonl", args, settings
                )
                if guard and watch(guard) != before:
                    raise GuardTripped(
                        f"run {case.id}-{n} changed the guard repository {guard}; "
                        "stopping. Inspect it with git status before anything else."
                    )
                grade = gold.grade_run(case, n, ideas, idea_id, error=error, meta=result)
                record(dataclasses.replace(grade, stopped_after_result=stopped), plugin_path)
    except GuardTripped as exc:
        print(f"heuresis_gold: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        if guard and before is not None and watch(guard) != before:
            print(f"heuresis_gold: interrupted, and {guard} changed; inspect it", file=sys.stderr)
            return 1
        print("heuresis_gold: interrupted; the guard repository is unchanged", file=sys.stderr)
        return 130
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

    Files never revive a run: an error the original run recorded stays, and a folder with no
    grade line (the run was stopped or crashed before it was recorded) is an error. The plugin
    path and the code identity are facts about the original session, so they carry over.
    """
    work = res / "work" / name
    ideas = work / "ideas"
    log = res / "logs" / f"{name}.jsonl"
    meta = parse_stream(log.read_text(errors="replace"))[1] if log.is_file() else None
    kept = "no grade recorded" if original is None else original.get("error") or ""
    found = sorted((ideas / "ideas").glob("*.md")) if (ideas / "ideas").is_dir() else []
    if kept:
        grade = gold.grade_run(case, n, ideas, "", error=kept, meta=meta)
    elif len(found) == 1:
        grade = gold.grade_run(case, n, ideas, found[0].stem, meta=meta)
    else:
        error = f"expected one idea file, found {len(found)}"
        grade = gold.grade_run(case, n, ideas, "", error=error, meta=meta)
    carried = {k: (original or {}).get(k) for k in ("commit", "dirty", "plugin_version")}
    carried["stopped_after_result"] = bool((original or {}).get("stopped_after_result"))
    return dataclasses.replace(grade, **carried), (original or {}).get("plugin_path")


def regrade(args) -> int:
    missing = [d for d in args.results if not d.is_dir()]
    if missing:
        print(f"heuresis_gold: results folder not found: {missing[0]}", file=sys.stderr)
        return 2
    out = args.into
    if any(d == out for d in args.results):
        print(f"heuresis_gold: --into {args.into} is one of the results folders", file=sys.stderr)
        return 2
    if (out / "grades.jsonl").exists() or (out / "work").exists():
        print(
            f"heuresis_gold: --into {args.into} already holds grades or runs; name a new folder",
            file=sys.stderr,
        )
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
    merged: dict[tuple[str, int], tuple[dict, Path]] = {}
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
            if key in merged and grade.error:
                continue
            if key in merged and not merged[key][0]["error"]:
                print(
                    f"heuresis_gold: warning: {case_id} run {n} in {res} replaces the grade from "
                    f"{merged[key][1]}; regrade replaces a repeat, it does not pool it",
                    file=sys.stderr,
                )
            merged[key] = ({**grade.to_dict(), "plugin_path": plugin_path}, res)
    if not merged:
        print("heuresis_gold: no run folders to grade", file=sys.stderr)
        return 2
    order += [c for c in dict.fromkeys(c for c, _ in merged) if c not in order]
    rows = sorted((m[0] for m in merged.values()), key=lambda d: (order.index(d["case"]), d["run"]))
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
    p = sub.add_parser(
        "regrade",
        help="grade finished runs again from their files",
        description="Grade the runs in RESULTS again from the files in their work folders. "
        "Where one case and run is in several folders, a later folder replaces an earlier "
        "one only if its run did not fail (with a warning); repeats are replaced, never pooled.",
    )
    p.add_argument("results", type=Path, nargs="+")
    p.add_argument("--into", type=Path, required=True, help="a new folder for the combined grades")
    p.add_argument("--cases", type=Path, action="append", default=[])
    args = parser.parse_args(argv)
    if args.command == "run":
        args.cases = args.cases or [DEFAULT_CASES]
    # Resolved once here, so no later step depends on the working directory.
    for name in ("out", "plugin_dir", "guard_repo", "into", "results", "cases"):
        value = getattr(args, name, None)
        if isinstance(value, list):
            setattr(args, name, [v.resolve() for v in value])
        elif value is not None:
            setattr(args, name, value.resolve())
    try:
        if args.command == "regrade":
            return regrade(args)
        if args.command == "run":
            return run(args)
        return report(args)
    except gold.GoldError as exc:
        print(f"heuresis_gold: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
