"""Mutation testing of the plugin hooks: mutmut writes the mutants, and this runs the tests.

Usage: uv run python scripts/mutation.py [--changed-since REF] [--module PATH ...]
           [--shard I/N] [--workers N] [--no-confirm] [--out FILE] [--summary FILE]
           [--report-only]
       uv run python scripts/mutation.py --merge FILE... [--summary FILE] [--report-only]

mutmut 3 picks the tests for a mutant from calls it sees in the pytest process, and it activates a
mutant by the module name it was imported under. techne's hooks run as scripts in a subprocess
(`python3 hooks/git_guards.py`), under names mutmut never sees, so mutmut alone reports every
mutant as covered by no test. Here mutmut only generates the mutants and writes each one into the
source (`mutmut apply`), and the tests run against the real files:

1. Copy the working tree to a scratch folder and run the modules' tests there once, unmutated,
   tracing which test reaches which function in every Python process (mutation_trace/); stop
   unless they pass.
2. Generate the mutants with mutmut, for every function, or with --changed-since only for the
   functions whose lines changed since REF; of those, a mutant that changes none of the changed
   lines is not run (cargo-mutants' --in-diff).
3. For each mutant: write it into the scratch copy, run the tests that reached its function
   (all of the module's tests when none did), restore the file. A mutant that survives the
   subset is run once more against all of the module's tests before it counts as survived,
   unless --no-confirm (the weekly full run, where this re-run of every survivor cost 70% of
   the time and turned 3 of about 790 survivors into kills). Each run gets its own bytecode
   cache, so a stale .pyc cannot stand in for the mutant, and every process it starts is held to
   MEMORY_LIMIT_KB of data, so a mutant that allocates without end fails its test instead of
   taking the machine down. A kill counts only when the tests that decided it, the subset or
   the confirming rerun, pass on the unmutated copy (checked once per test list); otherwise the
   mutant is judged by its module's tests, and a run whose module tests fail unmutated stops.
   SIGINT, SIGTERM or SIGHUP (a cancelled job, `timeout`) kills every test process at once and
   removes the scratch copy.

[tool.techne.mutation] in pyproject.toml maps each module to the test files that exercise it.
A survivor whose mutated function is listed in mutation/equivalent.toml (by the hash of the
mutated function's source, with the reason) counts as equivalent, not survived. A timeout counts
as detected, as Stryker counts it: the tests did not pass. Exit 0 when no mutant survived, 1 when
one did (0 with --report-only), and 1 whenever a mutant could not be applied or run. --merge
reads the --out files of several shards and prints their combined table.
"""

# research(2026-11): mutmut 3 runs mutants from a trampolined copy and selects tests by in-process
# call stats (https://github.com/boxed/mutmut); diff-scoped runs per PR plus a scheduled full run
# (https://mutants.rs/in-diff.html, https://stryker-mutator.io/blog/announcing-incremental-mode/);
# score = (killed + timeout) / (killed + timeout + survived)
# (https://stryker-mutator.io/docs/mutation-testing-elements/mutant-states-and-metrics/).

from __future__ import annotations

import argparse
import ast
import collections
import concurrent.futures
import difflib
import hashlib
import json
import os
import pathlib
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
from dataclasses import asdict, dataclass
from typing import NamedTuple

ROOT = pathlib.Path(__file__).resolve().parent.parent
TRACE = pathlib.Path(__file__).resolve().parent / "mutation_trace"
EQUIVALENT = pathlib.Path("mutation") / "equivalent.toml"  # under the repo root
MUTMUT_VERSION = "3.8.1"  # generate() uses mutmut internals that this version has
MIN_TIMEOUT = 30.0
# RLIMIT_DATA, not RLIMIT_AS: gitleaks (the secret guard tests' scanner) reserves 4 GiB of
# address space at start and refuses to run under an address-space cap.
MEMORY_LIMIT_KB = 2 * 1024 * 1024
TAIL_LINES = 30  # of a failed step's output, in the message that reports it

# The process groups of the test runs in flight, and whether a signal is stopping the run: a
# test run starts in its own session, out of reach of a signal sent to this process's group.
_live: set[int] = set()
_stopping = threading.Event()
# GitHub cancels a job with SIGINT, then SIGTERM; `timeout` sends SIGTERM.
STOP_SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)


@dataclass
class Result:
    name: str  # mutmut's mutant name, such as plugins.phylax.hooks.git_checks.x_parse_git__mutmut_3
    module: str  # the source path, such as plugins/phylax/hooks/git_checks.py
    function: str  # the qualified name, such as Guards.check_commit
    status: str  # killed, survived, timeout, equivalent or error
    key: str  # sha256 of the mutated function's source
    seconds: float
    tests: int
    diff: str = ""  # the lines the mutant changed, "-" before and "+" after
    reason: str = ""  # an error's cause: what mutmut or pytest said, or why the run cannot judge


class Outcome(NamedTuple):
    """One mutant's run: STATUS, SECONDS, TESTS run, KEY, DIFF, the tests whose run DECIDED the
    status, the LIMIT in seconds that run had, and the REASON for an error or a failed run."""

    status: str
    seconds: float
    tests: int
    key: str
    diff: str
    decided: list[str]
    limit: float = 0.0
    reason: str = ""


def load_config(root: pathlib.Path = ROOT) -> dict[str, list[str]]:
    data = tomllib.loads((root / "pyproject.toml").read_text())
    mapping = data.get("tool", {}).get("techne", {}).get("mutation", {})
    if not mapping:
        raise SystemExit("no [tool.techne.mutation] table in pyproject.toml")
    config = {module: list(tests) for module, tests in mapping.items()}
    # mutmut writes the mutants of each module to mutants/<module> and a run writes each mutant
    # into <scratch>/<module>: a path that leaves the tree would have them overwrite a real file.
    for path in [*config, *(t.split("::")[0] for tests in config.values() for t in tests)]:
        if not inside(root, path):
            raise SystemExit(f"[tool.techne.mutation] names {path!r}, which is not inside {root}")
    return config


def inside(root: pathlib.Path, path: str) -> bool:
    """Whether PATH names a file under ROOT once resolved (symlinks and `..` followed; an
    absolute PATH replaces ROOT, so it resolves outside)."""
    resolved, top = (root / path).resolve(), root.resolve()
    return resolved != top and resolved.is_relative_to(top)


def tail(text: str, lines: int = TAIL_LINES) -> str:
    return "\n".join(text.rstrip().splitlines()[-lines:])


class StepFailed(SystemExit):
    """A command the run depends on failed; its message names the command and its output."""


def run_checked(command: list[str], cwd: pathlib.Path) -> str:
    """Run COMMAND in CWD and return its stdout; on a non-zero exit raise StepFailed naming the
    command, its exit code and the end of what it printed."""
    proc = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        said = tail(proc.stderr + proc.stdout) or "(nothing printed)"
        raise StepFailed(f"{shlex.join(command)} exited {proc.returncode}:\n{said}")
    return proc.stdout


def load_equivalent(root: pathlib.Path = ROOT) -> dict[str, str]:
    """{hash of a mutated function's source: why that mutant is equivalent}."""
    path = root / EQUIVALENT
    if not path.is_file():
        return {}
    return {e["key"]: e["why"] for e in tomllib.loads(path.read_text()).get("mutant", [])}


def function_spans(source: str) -> dict[str, tuple[int, int]]:
    """{qualified name: (first line, last line)} of each top-level function and each method of a
    top-level class, the units mutmut mutates; a function's decorators count as its lines."""

    def span(node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[int, int]:
        first = min([node.lineno, *(d.lineno for d in node.decorator_list)])
        return first, node.end_lineno or node.lineno

    spans = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            spans[node.name] = span(node)
        elif isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                    spans[f"{node.name}.{item.name}"] = span(item)
    return spans


def changed_lines(ref: str, module: str, root: pathlib.Path = ROOT) -> set[int]:
    """The line numbers of MODULE, as it is now, that differ from REF."""
    out = subprocess.run(
        ["git", "-C", str(root), "diff", "--unified=0", ref, "--", module],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    lines: set[int] = set()
    for m in re.finditer(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", out, re.M):
        start, count = int(m.group(1)), int(m.group(2) or "1")
        lines.update(range(start, start + max(count, 1)))
    return lines


def changed_functions(ref: str, module: str, root: pathlib.Path = ROOT) -> set[str] | None:
    """The functions of MODULE whose lines changed since REF; None when the whole file is new."""
    known = subprocess.run(
        ["git", "-C", str(root), "cat-file", "-e", f"{ref}:{module}"], capture_output=True
    )
    if known.returncode != 0:
        return None
    lines = changed_lines(ref, module, root)
    spans = function_spans((root / module).read_text())
    return {name for name, (a, b) in spans.items() if any(a <= n <= b for n in lines)}


def verify_ref(ref: str, root: pathlib.Path = ROOT) -> None:
    """Stop unless REF names a commit: changed_functions reads a module REF lacks as new, so a
    mistyped or unfetched REF would otherwise mutate every module."""
    run_checked(
        ["git", "-C", str(root), "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], root
    )


def qualname(mutant: str) -> str:
    """The qualified function name in a mutmut mutant name: x_f__mutmut_3 is f, and
    xǁGuardsǁcheck__mutmut_2 is Guards.check."""
    leaf = mutant.rsplit(".", 1)[-1]
    body = leaf.split("__mutmut_")[0]
    if body.startswith("xǁ"):
        return ".".join(part for part in body[2:].split("ǁ") if part)
    return body[2:] if body.startswith("x_") else body


def scratch_copy(dest: pathlib.Path, root: pathlib.Path = ROOT) -> None:
    """Copy the working tree's tracked and untracked, not ignored, files into DEST."""
    files = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        capture_output=True,
        check=True,
    ).stdout.split(b"\0")
    for raw in files:
        if not raw:
            continue
        rel = raw.decode()
        src = root / rel
        if src.is_file():
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)


def generate(scratch: pathlib.Path, modules: list[str]) -> list[str]:
    """Generate the mutants of MODULES under SCRATCH/mutants and return their names."""
    with (scratch / "pyproject.toml").open("a") as out:
        out.write(f"\n[tool.mutmut]\nsource_paths = {json.dumps(modules)}\n")
    code = (
        "import mutmut\n"
        f"assert mutmut.__version__ == {MUTMUT_VERSION!r}, mutmut.__version__\n"
        "from mutmut.__main__ import create_mutants\n"
        "from mutmut.utils.file_utils import copy_src_dir, setup_source_paths\n"
        "copy_src_dir(); setup_source_paths(); create_mutants(os.cpu_count() or 2)\n"
    )
    run_checked([sys.executable, "-c", "import os\n" + code], scratch)
    names = []
    for module in modules:
        meta = json.loads((scratch / "mutants" / f"{module}.meta").read_text())
        names.extend(sorted(meta["exit_code_by_key"]))
    return names


def function_key(source: str, module: str, function: str) -> str:
    """A hash of FUNCTION's source as it stands in SOURCE (a module with a mutant written in): the
    same mutation of the same function keeps its key when mutants are added elsewhere, and loses
    it when the function changes."""
    tree = ast.parse(source)
    *owner, name = function.split(".")
    body = tree.body
    for cls in owner:
        body = next(n.body for n in body if isinstance(n, ast.ClassDef) and n.name == cls)
    node = next(
        n for n in body if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef) and n.name == name
    )
    segment = ast.get_source_segment(source, node) or ""
    return hashlib.sha256(f"{module}\n{function}\n{segment}".encode()).hexdigest()


def mutated_lines(pristine: str, mutated: str) -> tuple[set[int], str]:
    """The line numbers of PRISTINE that MUTATED changes, and those lines as a short diff."""
    a, b = pristine.splitlines(), mutated.splitlines()
    lines: set[int] = set()
    diff: list[str] = []
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        lines.update(range(i1 + 1, i2 + 1) if i2 > i1 else {max(i1, 1)})
        diff += [f"-{line.strip()}" for line in a[i1:i2]] + [
            f"+{line.strip()}" for line in b[j1:j2]
        ]
    return lines, "\n".join(diff[:8])


def pytest_env(root: pathlib.Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("MUTANT_", "MUTATION_"))}
    env["PYTHONPYCACHEPREFIX"] = tempfile.mkdtemp(prefix="mutation-pyc-")
    return {**env, **(extra or {})}


def run_tests(
    scratch: pathlib.Path, tests: list[str], timeout: float, extra: dict[str, str] | None = None
) -> tuple[str, float, str]:
    """Run TESTS (pytest node ids or files) in SCRATCH; (status, seconds, what went wrong). The
    status is passed (pytest exit 0), failed (1: a test failed; 2: collection failed, as a
    mutant that breaks an import does), timeout (the wall budget, or a signal such as the CPU
    limit's), or error (any other exit: pytest's internal or usage errors, a node id that no
    longer exists, or no tests collected). Unless it passed, what went wrong is a line naming
    the cause (the exit code, the signal or the budget) and the end of pytest's output."""
    env = pytest_env(scratch, extra)
    log = pathlib.Path(env["PYTHONPYCACHEPREFIX"]) / "pytest.log"
    # A mutant that loops runs in the hook processes the tests start, which outlive a killed
    # pytest: each process gets the run's budget in CPU seconds (ulimit -t, inherited) and
    # MEMORY_LIMIT_KB of data (ulimit -d), and the run's whole process group is killed when it
    # ends, so nothing it started keeps a core or fills the memory.
    cpu = max(1, int(timeout))
    command = [sys.executable, "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider", *tests]
    start = time.monotonic()
    output = ""
    proc = None
    try:
        with log.open("wb") as sink:
            proc = subprocess.Popen(
                [
                    "sh",
                    "-c",
                    f'ulimit -t {cpu} && ulimit -d {MEMORY_LIMIT_KB} && exec "$@"',
                    "sh",
                    *command,
                ],
                cwd=scratch,
                env=env,
                stdout=sink,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        _live.add(proc.pid)
        if _stopping.is_set():  # stop() ran before this group was in _live
            raise RuntimeError("the run is stopping")
        try:
            code = proc.wait(timeout=timeout)
            status = {0: "passed", 1: "failed", 2: "failed"}.get(code)
            status = status or ("timeout" if code < 0 else "error")
            cause = f"pytest exited {code}"
            if code < 0:
                cause = f"pytest killed by signal {-code} ({signal.strsignal(-code)})"
        except subprocess.TimeoutExpired:
            status, cause = "timeout", f"pytest still running after {timeout:.0f} s"
        if status != "passed":
            output = f"{cause}:\n{tail(log.read_text(errors='replace'))}"
    finally:
        # Also reached by a stop signal that lands between Popen and _live.add.
        if proc is not None:
            kill_group(proc)
            _live.discard(proc.pid)
        shutil.rmtree(env["PYTHONPYCACHEPREFIX"], ignore_errors=True)
    return status, time.monotonic() - start, output


def stop(signum: int, frame: object) -> None:
    """A STOP_SIGNALS signal: kill every test run's process group, start no more, and leave by
    SystemExit so each finally restores its file and removes the scratch copy."""
    _stopping.set()
    for group in tuple(_live):
        try:
            os.killpg(group, signal.SIGKILL)
        except ProcessLookupError:
            pass
    raise SystemExit(128 + signum)


def kill_group(proc: subprocess.Popen, wait: float = 10.0) -> None:
    """SIGKILL PROC's process group and return once no process of it is left, or after WAIT
    seconds: the signal is delivered asynchronously, so a looping child can still be running
    for a moment after killpg returns."""
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    proc.wait()
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        try:
            os.killpg(proc.pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.02)


def trace(scratch: pathlib.Path, config: dict[str, list[str]], modules: list[str]):
    """Run each module's tests once, unmutated, with the tracer on. Returns ({(module, function):
    {test node ids}}, {module: seconds the module's tests took})."""
    out = scratch.parent / "trace"
    out.mkdir()
    files = os.pathsep.join(str((scratch / m).resolve()) for m in modules)
    reached: dict[tuple[str, str], set[str]] = {}
    seconds: dict[str, float] = {}
    tests = sorted({t for m in modules for t in config[m]})
    path = [str(TRACE), *(p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p)]
    extra = {
        "PYTHONPATH": os.pathsep.join(path),
        "MUTATION_TRACE_DIR": str(out),
        "MUTATION_TRACE_FILES": files,
    }
    status, took, said = run_tests(scratch, ["-p", "mutation_trace_plugin", *tests], 3600, extra)
    if status != "passed":
        raise SystemExit(f"the unmutated tests did not pass ({status}): {' '.join(tests)}\n{said}")
    for module in modules:
        seconds[module] = took * len(config[module]) / len(tests)
    by_path = {str((scratch / m).resolve()): m for m in modules}
    for log in out.glob("*.jsonl"):
        for line in log.read_text().splitlines():
            row = json.loads(line)
            for hit, name in row["hits"]:
                if hit in by_path:
                    reached.setdefault((by_path[hit], name), set()).add(row["test"])
    return reached, seconds


def run_mutant(
    worker: pathlib.Path,
    mutant: str,
    module: str,
    function: str,
    tests: list[str],
    everything: list[str],
    budget: float,
    confirm: bool = True,
    diff_lines: set[int] | None = None,
) -> Outcome:
    """Write MUTANT into WORKER's copy, run TESTS, then (with CONFIRM) EVERYTHING when it
    survives; restore. With DIFF_LINES, a mutant that changes none of those lines is not run:
    its status is outside. A mutant that cannot be applied is an error, with mutmut's reason."""
    target = worker / module
    pristine = target.read_bytes()
    try:
        try:
            run_checked([sys.executable, "-m", "mutmut", "apply", mutant], worker)
            mutated = target.read_bytes()
            if mutated == pristine:
                raise StepFailed(f"mutmut apply {mutant} left {module} unchanged")
            lines, diff = mutated_lines(pristine.decode(), mutated.decode())
            key = function_key(mutated.decode(), module, function)
        except (StepFailed, StopIteration, SyntaxError, UnicodeDecodeError) as e:
            why = str(e) or f"{function} not found in the mutated {module}"
            return Outcome("error", 0.0, 0, "", "", [], reason=why)
        if diff_lines is not None and not lines & diff_lines:
            return Outcome("outside", 0.0, 0, key, diff, [])
        decided, limit = tests or everything, budget
        status, took, said = run_tests(worker, decided, limit)
        if confirm and status == "passed" and tests and tests != everything:
            decided, limit = everything, budget * 3
            status, more, said = run_tests(worker, everything, limit)
            took += more
    finally:
        target.write_bytes(pristine)
    status = {"failed": "killed", "passed": "survived"}.get(status, status)
    return Outcome(status, took, len(decided), key, diff, decided, limit, said)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--changed-since", metavar="REF")
    ap.add_argument(
        "--module", action="append", default=[], help="a configured module (repeatable)"
    )
    ap.add_argument("--shard", default="1/1", help="I/N: run every Nth mutant from the Ith")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) // 2))
    ap.add_argument(
        "--no-confirm",
        action="store_true",
        help="count a mutant that survives the tests reaching it as survived, without rerunning "
        "it against all of its module's tests",
    )
    ap.add_argument("--out", type=pathlib.Path, help="write each mutant's result here (JSON)")
    ap.add_argument("--summary", type=pathlib.Path, help="append the score table here (markdown)")
    ap.add_argument("--report-only", action="store_true", help="exit 0 even when a mutant survived")
    ap.add_argument("--merge", nargs="+", type=pathlib.Path, help="--out files to combine")
    ap.add_argument("--root", type=pathlib.Path, default=ROOT, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    if args.merge:
        missing = [str(f) for f in args.merge if not f.is_file()]
        if missing:  # an unmatched shell glob arrives as its own text
            raise SystemExit(f"no results file at {', '.join(missing)}: no shard wrote one")
        merged = [Result(**r) for f in args.merge for r in json.loads(f.read_text())]
        return report(merged, args.summary, args.report_only)
    root = args.root.resolve()
    config = load_config(root)
    unknown = [m for m in args.module if m not in config]
    if unknown:
        ap.error(f"not in [tool.techne.mutation]: {', '.join(unknown)}")
    shard, of = (int(x) for x in args.shard.split("/"))
    if not 1 <= shard <= of:
        ap.error("--shard is I/N with 1 <= I <= N")
    modules = args.module or list(config)
    wanted: dict[str, set[str] | None] = dict.fromkeys(modules)
    diff_lines: dict[str, set[int] | None] = dict.fromkeys(modules)
    if args.changed_since:
        verify_ref(args.changed_since, root)
        wanted = {m: changed_functions(args.changed_since, m, root) for m in modules}
        wanted = {m: f for m, f in wanted.items() if f is None or f}
        modules = list(wanted)
        # As cargo-mutants' --in-diff: only a mutant that changes a changed line counts, so a
        # survivor on an untouched line of a changed function stays the weekly run's.
        diff_lines = {
            m: None if wanted[m] is None else changed_lines(args.changed_since, m, root)
            for m in modules
        }
    if not modules:
        print("no configured module changed")
        return 0
    equivalent = load_equivalent(root)
    _stopping.clear()
    handlers = {}
    if threading.current_thread() is threading.main_thread():
        handlers = {sig: signal.signal(sig, stop) for sig in STOP_SIGNALS}
    base = pathlib.Path(tempfile.mkdtemp(prefix="mutation-"))
    results: list[Result] = []
    try:
        scratch = base / "w0"
        scratch_copy(scratch, root)
        reached, seconds = trace(scratch, config, modules)
        names = generate(scratch, modules)
        jobs = []
        for name in names:
            module = next(m for m in modules if name.startswith(m[:-3].replace("/", ".") + "."))
            function = qualname(name)
            only = wanted[module]
            if only is not None and function not in only:
                continue
            jobs.append((name, module, function))
        jobs = jobs[shard - 1 :: of]
        workers = [scratch]
        for i in range(1, min(args.workers, len(jobs) or 1)):
            workers.append(base / f"w{i}")
            shutil.copytree(scratch, workers[-1], symlinks=True)
        passes_unmutated: dict[tuple[tuple[str, ...], float], tuple[bool, str]] = {}
        lock = threading.Lock()

        def sound(worker: pathlib.Path, tests: list[str], budget: float) -> tuple[bool, str]:
            """Whether TESTS pass on the unmutated copy, so that a failure under a mutant is the
            mutant's: a traced subset can hold a test that needs another to run first, and the
            module's tests run in their configured order can hold one that fails or flakes.
            Returns the verdict and, when they fail, the cause and the end of pytest's output."""
            with lock:
                known = passes_unmutated.get((tuple(tests), budget))
            if known is None:
                status, _, said = run_tests(worker, tests, budget)
                known = (status == "passed", said)
                with lock:
                    passes_unmutated[(tuple(tests), budget)] = known
            return known

        def one(job, worker):
            name, module, function = job
            everything = config[module]
            tests = sorted(reached.get((module, function), set()))
            budget = max(MIN_TIMEOUT, 3 * seconds[module])
            run = (worker, name, module, function)
            more = (budget, not args.no_confirm, diff_lines[module])
            while True:
                out = run_mutant(*run, tests, everything, *more)
                status, reason = out.status, out.reason if out.status == "error" else ""
                if status not in ("killed", "timeout"):
                    break
                # A timeout counts as detected only when the same tests finish unmutated within
                # the same limit; a kill only needs them to pass.
                limit = out.limit if status == "timeout" else budget * 3
                ok, said = sound(worker, out.decided, limit)
                if ok:
                    break
                if out.decided == everything:
                    if status == "timeout":
                        status = "error"
                        reason = f"the unmutated tests also fail within {limit:.0f} s: {said}"
                        break
                    raise SystemExit(
                        f"the tests of {module} do not pass unmutated on their own "
                        f"({' '.join(out.decided)}):\n{said}"
                    )
                tests = []  # the subset fails on its own: judge the mutant by the module's tests
            if status == "survived" and out.key in equivalent:
                status = "equivalent"
            took = round(out.seconds, 2)
            return Result(
                name, module, function, status, out.key, took, out.tests, out.diff, reason
            )

        free = list(workers)
        with concurrent.futures.ThreadPoolExecutor(len(workers)) as pool:
            pending = {}
            queue = collections.deque(jobs)
            while queue or pending:
                while queue and free:
                    worker = free.pop()
                    pending[pool.submit(one, queue.popleft(), worker)] = worker
                done, _ = concurrent.futures.wait(pending, return_when="FIRST_COMPLETED")
                for fut in done:
                    free.append(pending.pop(fut))
                    r = fut.result()
                    if r.status == "outside":
                        continue
                    results.append(r)
                    print(
                        f"{r.status:10} {r.module}::{r.function} {r.name.rsplit('__', 1)[-1]}",
                        flush=True,
                    )
                    # Rewritten after each mutant, so a shard whose runner is stopped keeps
                    # what it finished.
                    write_results(args.out, results)
    finally:
        for sig, previous in handlers.items():
            signal.signal(sig, previous)
        shutil.rmtree(base, ignore_errors=True)
    write_results(args.out, results)
    return report(results, args.summary, args.report_only)


def write_results(out: pathlib.Path | None, results: list[Result]) -> None:
    if out is None:
        return
    partial = out.with_name(out.name + ".partial")
    partial.write_text(json.dumps([asdict(r) for r in results], indent=1) + "\n")
    partial.replace(out)


def report(results: list[Result], summary: pathlib.Path | None, report_only: bool) -> int:
    table = score_table(results)
    print(table)
    if summary:
        with summary.open("a") as out:
            out.write(table + "\n")
    if any(r.status == "error" for r in results):
        return 1  # a broken run, not a score: fails even with --report-only
    return 0 if report_only else int(any(r.status == "survived" for r in results))


def score_table(results: list[Result]) -> str:
    """A markdown table of each module's counts and score, (killed + timeout) / (killed + timeout +
    survived), then each survivor."""
    rows = [
        "| Module | Mutants | Killed | Survived | Timeout | Equivalent | Score |",
        "|---|---|---|---|---|---|---|",
    ]
    for module in sorted({r.module for r in results}):
        mine = [r for r in results if r.module == module]
        count = {
            s: sum(r.status == s for r in mine)
            for s in ("killed", "survived", "timeout", "equivalent")
        }
        judged = count["killed"] + count["survived"] + count["timeout"]
        detected = count["killed"] + count["timeout"]
        score = f"{detected / judged:.1%}" if judged else "-"
        rows.append(
            f"| `{module}` | {len(mine)} | {count['killed']} | {count['survived']} | "
            f"{count['timeout']} | {count['equivalent']} | {score} |"
        )
    errors = [r for r in results if r.status == "error"]
    if errors:
        rows += ["", f"Errors (the run could not judge these mutants): {len(errors)}"]
        for r in errors:
            rows.append(f"- `{r.name}` ({r.function})")
            rows += [f"  `{line}`" for line in r.diff.splitlines()]
            rows += [f"  > {line}" for line in r.reason.splitlines()[: TAIL_LINES + 1]]
    survivors = [r for r in results if r.status == "survived"]
    if survivors:
        rows += ["", "Survivors (the change, and the key for mutation/equivalent.toml):"]
        for r in survivors:
            rows.append(f"- `{r.name}` ({r.function}) key `{r.key}`")
            rows += [f"  `{line}`" for line in r.diff.splitlines()]
    return "\n".join(rows)


if __name__ == "__main__":
    sys.exit(main())
