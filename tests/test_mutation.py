"""Tests for scripts/mutation.py, the mutation runner for hooks that tests run as subprocesses."""

from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import textwrap
import time

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("techne_mutation", ROOT / "scripts" / "mutation.py")
assert spec and spec.loader
mutation = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mutation  # dataclasses look their module up while it loads
spec.loader.exec_module(mutation)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("plugins.phylax.hooks.git_checks.x_parse_git__mutmut_3", "parse_git"),
        ("plugins.phylax.hooks.git_checks.xǁGuardsǁcheck_commit__mutmut_12", "Guards.check_commit"),
        ("hooks.guard.x_main__mutmut_1", "main"),
        ("hooks.guard.x__private__mutmut_2", "_private"),
    ],
)
def test_qualname_reads_mutmut_names(name, expected):
    assert mutation.qualname(name) == expected


def test_function_spans_cover_functions_methods_and_decorators():
    source = textwrap.dedent(
        """\
        import functools

        @functools.cache
        def a():
            return 1

        class C:
            def m(self):
                def inner():
                    return 2
                return inner()

        def b():
            pass
        """
    )
    assert mutation.function_spans(source) == {"a": (3, 5), "C.m": (8, 11), "b": (13, 14)}


def _git(repo: pathlib.Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        check=True,
        capture_output=True,
        env={**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"},
    )


def test_changed_functions_are_the_ones_whose_lines_changed(tmp_path):
    (tmp_path / "m.py").write_text("def a():\n    return 1\n\n\ndef b():\n    return 2\n")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "init")
    assert mutation.changed_functions("HEAD", "m.py", tmp_path) == set()
    (tmp_path / "m.py").write_text("def a():\n    return 1\n\n\ndef b():\n    return 3\n")
    assert mutation.changed_functions("HEAD", "m.py", tmp_path) == {"b"}
    (tmp_path / "new.py").write_text("def c():\n    pass\n")
    assert mutation.changed_functions("HEAD", "new.py", tmp_path) is None


def test_the_score_counts_timeouts_as_detected_and_equivalents_out():
    def r(status):
        return mutation.Result("m.x_f__mutmut_1", "m.py", "f", status, "k" * 64, 1.0, 1)

    table = mutation.score_table(
        [r("killed"), r("killed"), r("survived"), r("timeout"), r("equivalent")]
    )
    assert "| `m.py` | 5 | 2 | 1 | 1 | 1 | 75.0% |" in table
    assert "Survivors" in table and "m.x_f__mutmut_1" in table


def test_the_configured_modules_and_their_tests_exist():
    config = mutation.load_config()
    assert config
    for module, tests in config.items():
        assert (ROOT / module).is_file(), module
        assert tests and all((ROOT / t).is_file() for t in tests), module


def test_mutmut_is_the_version_generate_was_written_for():
    import mutmut

    assert mutmut.__version__ == mutation.MUTMUT_VERSION


TOY_HOOK = """\
import sys


def refuses(command):
    return "rm -rf /" in command


def unreached(x):
    return x + 1


def main():
    return 2 if refuses(sys.stdin.read()) else 0


if __name__ == "__main__":
    sys.exit(main())
"""

TOY_TEST = """\
import os
import pathlib
import subprocess
import sys

HOOK = pathlib.Path(__file__).resolve().parent.parent / "hooks" / "guard.py"


def run(text):
    return subprocess.run([sys.executable, str(HOOK)], input=text, text=True, env=dict(os.environ))


def test_refuses_only_the_wipe():
    assert run("rm -rf /").returncode == 2
    assert run("ls").returncode == 0
"""


@pytest.fixture
def toy(tmp_path):
    """A repo whose one hook is tested only through a subprocess, as techne's are."""
    repo = tmp_path / "toy"
    (repo / "hooks").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "hooks" / "guard.py").write_text(TOY_HOOK)
    (repo / "tests" / "test_guard.py").write_text(TOY_TEST)
    (repo / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n\n'
        '[tool.techne.mutation]\n"hooks/guard.py" = ["tests/test_guard.py"]\n'
    )
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    return repo


def test_a_subprocess_test_kills_the_mutants_it_reaches(toy, tmp_path):
    out = tmp_path / "results.json"
    code = mutation.main(["--root", str(toy), "--workers", "2", "--out", str(out)])
    results = json.loads(out.read_text())
    by_function: dict[str, set[str]] = {}
    for r in results:
        by_function.setdefault(r["function"], set()).add(r["status"])
    assert by_function["refuses"] == {"killed"}
    assert by_function["main"] == {"killed"}
    # Nothing calls unreached(): its mutants run against all of the module's tests and survive.
    assert by_function["unreached"] == {"survived"}
    assert code == 1


def test_an_equivalent_survivor_is_listed_and_does_not_fail(toy, tmp_path):
    out = tmp_path / "results.json"
    mutation.main(["--root", str(toy), "--workers", "1", "--out", str(out)])
    survivors = [r for r in json.loads(out.read_text()) if r["status"] == "survived"]
    (toy / "mutation").mkdir()
    (toy / "mutation" / "equivalent.toml").write_text(
        "".join(f'[[mutant]]\nkey = "{r["key"]}"\nwhy = "nothing calls it"\n\n' for r in survivors)
    )
    assert mutation.main(["--root", str(toy), "--workers", "1", "--out", str(out)]) == 0
    assert {r["status"] for r in json.loads(out.read_text()) if r["function"] == "unreached"} == {
        "equivalent"
    }


def test_changed_since_runs_only_the_changed_functions(toy, tmp_path):
    hook = toy / "hooks" / "guard.py"
    hook.write_text(
        hook.read_text().replace('"rm -rf /" in command', '"rm -rf /" in command.strip()')
    )
    out = tmp_path / "results.json"
    mutation.main(["--root", str(toy), "--changed-since", "HEAD", "--out", str(out)])
    assert {r["function"] for r in json.loads(out.read_text())} == {"refuses"}


def test_red_unmutated_tests_stop_the_run(toy):
    (toy / "tests" / "test_guard.py").write_text(TOY_TEST.replace("== 2", "== 9"))
    with pytest.raises(SystemExit, match="did not pass") as stopped:
        mutation.main(["--root", str(toy), "--workers", "1"])
    assert "test_refuses_only_the_wipe" in str(stopped.value)  # the log names what failed


def test_the_scratch_copy_leaves_the_repo_untouched(toy):
    before = {p: p.read_bytes() for p in toy.rglob("*") if p.is_file() and ".git" not in p.parts}
    mutation.main(["--root", str(toy), "--workers", "2"])
    after = {p: p.read_bytes() for p in toy.rglob("*") if p.is_file() and ".git" not in p.parts}
    assert after == before
    assert not (toy / "mutants").exists()


def test_the_tracer_records_a_subprocess_under_the_running_test(tmp_path):
    hook = tmp_path / "h.py"
    hook.write_text("def f():\n    return 1\n\nf()\n")
    out = tmp_path / "trace"
    out.mkdir()
    env = {
        **os.environ,
        "PYTHONPATH": str(mutation.TRACE),
        "MUTATION_TRACE_DIR": str(out),
        "MUTATION_TRACE_FILES": str(hook.resolve()),
        "MUTATION_TEST_ID": "tests/t.py::test_x",
    }
    subprocess.run([sys.executable, str(hook)], env=env, check=True)
    (line,) = "".join(p.read_text() for p in out.glob("*.jsonl")).splitlines()
    row = json.loads(line)
    assert row["test"] == "tests/t.py::test_x"
    assert [str(hook.resolve()), "f"] in row["hits"]


def test_the_tracer_does_nothing_unless_asked(tmp_path):
    proc = subprocess.run(
        [sys.executable, "-c", "import sitecustomize; print(sitecustomize._tool)"],
        env={**os.environ, "PYTHONPATH": str(mutation.TRACE)},
        capture_output=True,
        text=True,
        check=True,
    )
    assert proc.stdout.strip() == "None"
    assert shutil.which("git")


def test_merge_combines_shards_and_report_only_exits_zero(tmp_path, capsys):
    def r(name, status):
        return {
            "name": name,
            "module": "m.py",
            "function": "f",
            "status": status,
            "key": "k" * 64,
            "seconds": 1.0,
            "tests": 1,
        }

    one, two = tmp_path / "1.json", tmp_path / "2.json"
    one.write_text(json.dumps([r("m.x_f__mutmut_1", "killed")]))
    two.write_text(json.dumps([r("m.x_f__mutmut_2", "survived")]))
    summary = tmp_path / "summary.md"
    assert mutation.main(["--merge", str(one), str(two), "--summary", str(summary)]) == 1
    assert "| `m.py` | 2 | 1 | 1 | 0 | 0 | 50.0% |" in summary.read_text()
    assert mutation.main(["--merge", str(one), str(two), "--report-only"]) == 0
    capsys.readouterr()


@pytest.mark.parametrize("ends", ["passes", "times out"])
def test_a_run_leaves_no_process_behind(tmp_path, ends):
    # A mutant that loops does so in a hook process the test started; when the run ends, by
    # its own exit or by the timeout, every process it started is gone.
    pidfile = tmp_path / "child.pid"
    (tmp_path / "test_spawn.py").write_text(
        textwrap.dedent(
            f"""
            import pathlib, subprocess, sys, time

            def test_spawn():
                child = subprocess.Popen([sys.executable, "-c", "while True: pass"])
                pathlib.Path({str(pidfile)!r}).write_text(str(child.pid))
                if {ends == "times out"!r}:
                    time.sleep(60)
            """
        )
    )
    status, _, _ = mutation.run_tests(tmp_path, ["test_spawn.py"], 5)
    assert status == ("passed" if ends == "passes" else "timeout")
    pid = int(pidfile.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_every_process_a_run_starts_is_held_to_the_memory_limit(tmp_path):
    # A mutant that allocates without end runs in a hook process the test started; the data
    # limit must reach it there, not only pytest. Read back, never exercised: a mutant here
    # would allocate for real.
    seen = tmp_path / "limit"
    (tmp_path / "test_child.py").write_text(
        textwrap.dedent(
            f"""
            import subprocess, sys

            def test_child():
                code = "import resource; print(resource.getrlimit(resource.RLIMIT_DATA)[0])"
                out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
                open({str(seen)!r}, "w").write(out.stdout)
            """
        )
    )
    status, _, _ = mutation.run_tests(tmp_path, ["test_child.py"], 30)
    assert status == "passed"
    assert int(seen.read_text()) == mutation.MEMORY_LIMIT_KB * 1024


@pytest.mark.parametrize(("confirm", "runs"), [(True, 2), (False, 1)])
def test_no_confirm_skips_the_rerun_of_a_survivor(toy, monkeypatch, confirm, runs):
    calls = []

    def fake_run_tests(worker, tests, budget, extra=None):
        calls.append(tests)
        return "passed", 0.1, ""

    monkeypatch.setattr(mutation, "run_tests", fake_run_tests)
    names = mutation.generate(toy, ["hooks/guard.py"])
    name = next(n for n in names if "x_refuses" in n)
    everything = ["tests/test_guard.py"]
    out = mutation.run_mutant(
        toy,
        name,
        "hooks/guard.py",
        "refuses",
        ["tests/test_guard.py::test_x"],
        everything,
        5,
        confirm,
    )
    assert out.status == "survived" and len(calls) == runs
    assert out.tests == (1 if not confirm else len(everything))
    assert out.limit == (5 * 3 if confirm else 5)  # the limit of the run that decided
    assert (toy / "hooks" / "guard.py").read_text() == TOY_HOOK


def test_the_weekly_full_run_does_not_confirm_and_the_pull_request_run_does():
    workflow = (ROOT / ".github" / "workflows" / "mutation.yml").read_text()
    changed, full = workflow.split("\n  changed:", 1)[1].split("\n  full:", 1)
    assert "--no-confirm" not in changed and "--no-confirm" in full


def _toy_repo(tmp_path: pathlib.Path, hook: str, test: str) -> pathlib.Path:
    repo = tmp_path / "toy"
    (repo / "hooks").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "hooks" / "guard.py").write_text(hook)
    (repo / "tests" / "test_guard.py").write_text(test)
    (repo / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n\n'
        '[tool.techne.mutation]\n"hooks/guard.py" = ["tests/test_guard.py"]\n'
    )
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    return repo


TIGHT_HOOK = """\
import sys


class G:
    def check(self, command: str, limit: int = 3) -> bool:
        return len(command) > limit and "rm" in command


# research(2026-11): a comment directly above a wrapped signature
def resolve(
    command: str,
    extra: str = "",
) -> bool:
    return G().check(command + extra, 2)


def main():
    return 2 if resolve(sys.stdin.read()) else 0


if __name__ == "__main__":
    sys.exit(main())
"""


def test_every_mutant_of_a_function_gets_its_own_key(tmp_path):
    # A comment directly above a wrapped def, or a method right after its class line, once
    # made every mutant of that function hash to the signature alone, so one equivalent.toml
    # entry would have hidden them all.
    repo = _toy_repo(tmp_path, TIGHT_HOOK, TOY_TEST.replace("rm -rf /", "rm -rf /x"))
    out = tmp_path / "results.json"
    mutation.main(["--root", str(repo), "--workers", "1", "--out", str(out), "--report-only"])
    results = json.loads(out.read_text())
    for function in ("resolve", "G.check"):
        mine = [r for r in results if r["function"] == function]
        assert len(mine) > 1 and len({r["key"] for r in mine}) == len(mine), function
        assert all(r["diff"].startswith("-") and "\n+" in r["diff"] for r in mine)


@pytest.mark.parametrize(
    "path", ["/etc/hostname", "../outside.py", "hooks/../../x.py", "link/v.py", "", "."]
)
def test_a_configured_path_outside_the_tree_is_refused(tmp_path, path):
    # mutmut writes mutants/<module> and a run writes each mutant into <scratch>/<module>; a
    # path that leaves the tree would have them overwrite a real file.
    repo = tmp_path / "repo"
    repo.mkdir()
    (tmp_path / "elsewhere").mkdir()
    (repo / "link").symlink_to(tmp_path / "elsewhere")
    for table in (f'"{path}" = ["tests/t.py"]', f'"hooks/g.py" = ["{path}"]'):
        (repo / "pyproject.toml").write_text(f"[tool.techne.mutation]\n{table}\n")
        with pytest.raises(SystemExit, match="not inside"):
            mutation.load_config(repo)


ORDER_TEST = """\
import os
import pathlib
import subprocess
import sys

HOOK = pathlib.Path(__file__).resolve().parent.parent / "hooks" / "guard.py"
STATE = {}


def test_a_setup():
    STATE["ready"] = True


def test_b_needs_a():
    assert STATE.get("ready")
    subprocess.run([sys.executable, str(HOOK)], input="ls", text=True, env=dict(os.environ))
"""


def test_a_subset_that_fails_on_its_own_does_not_kill(tmp_path):
    # test_b reaches the hook but asserts nothing about it, and passes only after test_a: run
    # alone, as the traced subset, it fails whatever the mutant, so its failure kills nothing.
    repo = _toy_repo(tmp_path, TOY_HOOK, ORDER_TEST)
    out = tmp_path / "results.json"
    mutation.main(["--root", str(repo), "--workers", "1", "--out", str(out), "--report-only"])
    results = json.loads(out.read_text())
    assert results and {r["status"] for r in results} == {"survived"}


@pytest.mark.parametrize(
    ("body", "status"),
    [("def test_x():\n    pass\n", "passed"), ("def test_x():\n    assert 0\n", "failed"),
     ("import nonexistent_module_x\n", "failed"), ("x = 1\n", "error")],
)  # fmt: skip
def test_only_a_test_failure_or_a_broken_import_counts_as_failed(tmp_path, body, status):
    (tmp_path / "test_one.py").write_text(body)
    assert mutation.run_tests(tmp_path, ["test_one.py"], 30)[0] == status


def test_changed_since_counts_only_mutants_on_changed_lines(toy, tmp_path):
    # As cargo-mutants' --in-diff: a survivor on an untouched line of a changed function stays
    # the weekly run's, so a pull request answers only for the lines it wrote.
    hook = toy / "hooks" / "guard.py"
    hook.write_text(
        hook.read_text().replace(
            "def unreached(x):\n    return x + 1",
            "def unreached(x):\n    y = x * 2\n    return x + 1",
        )
    )
    out = tmp_path / "results.json"
    mutation.main(["--root", str(toy), "--changed-since", "HEAD", "--out", str(out)])
    results = json.loads(out.read_text())
    assert results and {r["function"] for r in results} == {"unreached"}
    assert all("y = x" in r["diff"] for r in results), [r["diff"] for r in results]


def _two_file_repo(tmp_path: pathlib.Path, files: dict[str, str], order: list[str]) -> pathlib.Path:
    repo = tmp_path / "toy"
    (repo / "hooks").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "hooks" / "guard.py").write_text(TOY_HOOK)
    for name, body in files.items():
        (repo / "tests" / name).write_text(body)
    (repo / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n\n'
        f'[tool.techne.mutation]\n"hooks/guard.py" = {json.dumps(order)}\n'
    )
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    return repo


REACH_ONLY = """\
import os
import pathlib
import subprocess
import sys

HOOK = pathlib.Path(__file__).resolve().parent.parent / "hooks" / "guard.py"


def test_reach():
    subprocess.run([sys.executable, str(HOOK)], input="ls", text=True, env=dict(os.environ))


def test_needs_a():
    assert os.environ.get("TOY_READY")
"""


def test_a_kill_by_the_confirming_rerun_must_pass_unmutated(tmp_path):
    # The trace runs the test files sorted (a, then b); the confirming rerun runs them in their
    # configured order (b, then a), where test_needs_a fails whatever the mutant. Nothing
    # asserts on the hook, so a kill here would be false: the run stops and says why.
    repo = _two_file_repo(
        tmp_path,
        {
            "test_b.py": REACH_ONLY,
            "test_a.py": "import os\n\n\ndef test_set():\n    os.environ['TOY_READY'] = '1'\n",
        },
        ["tests/test_b.py", "tests/test_a.py"],
    )
    with pytest.raises(SystemExit, match="do not pass unmutated") as stopped:
        mutation.main(["--root", str(repo), "--workers", "1", "--report-only"])
    assert "test_needs_a" in str(stopped.value)


def test_a_mutmut_failure_says_what_mutmut_said(toy, monkeypatch):
    monkeypatch.setattr(mutation, "MUTMUT_VERSION", "0.0.0")
    with pytest.raises(mutation.StepFailed, match="AssertionError"):
        mutation.generate(toy, ["hooks/guard.py"])


def test_a_mutant_that_cannot_be_applied_is_an_error_with_its_reason(toy):
    names = mutation.generate(toy, ["hooks/guard.py"])
    assert names
    status, _, ran, _, diff, decided, _, why = mutation.run_mutant(
        toy,
        "hooks.guard.x_refuses__mutmut_99999",
        "hooks/guard.py",
        "refuses",
        [],
        ["tests/test_guard.py"],
        5,
    )
    assert status == "error" and "mutmut" in why and ran == 0 and decided == [] and diff == ""
    assert (toy / "hooks" / "guard.py").read_text() == TOY_HOOK
    error = mutation.Result("m", "hooks/guard.py", "refuses", status, "", 0.0, 0, reason=why)
    table = mutation.score_table([error])
    assert "Errors" in table and why.splitlines()[0] in table
    assert mutation.report([error], None, True) == 1


def test_a_changed_since_ref_that_names_no_commit_stops_the_run(toy):
    with pytest.raises(mutation.StepFailed, match="rev-parse"):
        mutation.main(["--root", str(toy), "--changed-since", "no-such-ref"])


def test_the_tracer_counts_what_a_fixture_reaches_in_its_teardown(tmp_path):
    hook = tmp_path / "h.py"
    hook.write_text("def f():\n    return 1\n\nf()\n")
    (tmp_path / "test_fx.py").write_text(
        textwrap.dedent(
            f"""
            import os, subprocess, sys
            import pytest

            @pytest.fixture
            def cleanup():
                yield
                subprocess.run([sys.executable, {str(hook)!r}], check=True, env=dict(os.environ))

            def test_x(cleanup):
                pass
            """
        )
    )
    out = tmp_path / "trace"
    out.mkdir()
    extra = {
        "PYTHONPATH": str(mutation.TRACE),
        "MUTATION_TRACE_DIR": str(out),
        "MUTATION_TRACE_FILES": str(hook.resolve()),
    }
    status, _, said = mutation.run_tests(
        tmp_path, ["-p", "mutation_trace_plugin", "test_fx.py"], 60, extra
    )
    assert status == "passed", said
    rows = [json.loads(line) for p in out.glob("*.jsonl") for line in p.read_text().splitlines()]
    assert any(
        r["test"] == "test_fx.py::test_x" and [str(hook.resolve()), "f"] in r["hits"] for r in rows
    ), rows


SLEEPER_TEST = """\
import os
import pathlib
import subprocess
import sys
import time

HOOK = pathlib.Path(__file__).resolve().parent.parent / "hooks" / "guard.py"


def test_refuses_only_the_wipe():
    if bool(os.environ.get("MUTATION_TRACE_DIR")) == {in_trace}:
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
        pathlib.Path({pidfile!r}).write_text(str(child.pid))
        time.sleep(600)
    run = lambda text: subprocess.run([sys.executable, str(HOOK)], input=text, text=True)
    assert run("rm -rf /").returncode == 2
    assert run("ls").returncode == 0
"""


@pytest.mark.parametrize("phase", ["trace", "mutants"])
def test_sigterm_kills_every_test_process_and_removes_the_scratch_copy(tmp_path, phase):
    # `timeout` stops a run with SIGTERM, which a test run's own session never receives: the
    # runner kills each test run's group itself and leaves by SystemExit, so cleanup runs.
    pidfile = tmp_path / "child.pid"
    test = SLEEPER_TEST.format(in_trace=phase == "trace", pidfile=str(pidfile))
    repo = _toy_repo(tmp_path, TOY_HOOK, test)
    scratch = tmp_path / "tmp"
    scratch.mkdir()
    script = str(ROOT / "scripts" / "mutation.py")
    driver = (
        "import importlib.util, sys\n"
        f"spec = importlib.util.spec_from_file_location('m', {script!r})\n"
        "m = importlib.util.module_from_spec(spec); sys.modules['m'] = m\n"
        "spec.loader.exec_module(m)\n"
        f"sys.exit(m.main(['--root', {str(repo)!r}, '--workers', '1']))\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", driver],
        env={**os.environ, "TMPDIR": str(scratch)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 120
        while not pidfile.exists() or not pidfile.read_text():
            assert proc.poll() is None and time.monotonic() < deadline
            time.sleep(0.1)
        child = int(pidfile.read_text())
        proc.send_signal(signal.SIGTERM)
        # Well inside the 30-second budget a test run would otherwise be left to use up.
        assert proc.wait(timeout=15) == 128 + signal.SIGTERM
    finally:
        proc.kill()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        os.kill(child, signal.SIGKILL)
        pytest.fail(f"test process {child} outlived the run")
    assert list(scratch.iterdir()) == []


def test_a_stopping_run_starts_no_test_run(tmp_path):
    (tmp_path / "test_one.py").write_text("def test_x():\n    pass\n")
    mutation._stopping.set()
    try:
        with pytest.raises(RuntimeError, match="stopping"):
            mutation.run_tests(tmp_path, ["test_one.py"], 30)
    finally:
        mutation._stopping.clear()


@pytest.mark.parametrize(
    ("tests", "timeout", "cause"),
    [(["test_one.py::test_gone"], 30, "pytest exited 4"),
     (["test_one.py::test_slow"], 2, "pytest still running after 2 s"),
     (["test_one.py::test_killed"], 30, "pytest killed by signal 9 (Killed)")],
)  # fmt: skip
def test_a_run_that_does_not_pass_names_its_cause(tmp_path, tests, timeout, cause):
    # A node id the trace recorded can vanish under a mutant (a parametrize value the mutated
    # function computes), and pytest then exits 4; the cause leads what the run reports.
    (tmp_path / "test_one.py").write_text(
        "import os\nimport time\n\n\ndef test_slow():\n    time.sleep(30)\n\n\n"
        "def test_killed():\n    os.kill(os.getpid(), 9)\n"
    )
    status, _, said = mutation.run_tests(tmp_path, tests, timeout)
    assert status in ("error", "timeout") and said.startswith(cause + ":"), said


def _fake_mutant_runs(monkeypatch, outcome, unmutated):
    """run_mutant returns OUTCOME for every mutant; an unmutated run of the tests (sound()'s)
    returns UNMUTATED; the trace runs for real."""
    real = mutation.run_tests
    unmutated_calls = []

    def run_tests(worker, tests, budget, extra=None):
        if extra:  # the trace
            return real(worker, tests, budget, extra)
        unmutated_calls.append((tests, budget))
        return unmutated

    monkeypatch.setattr(mutation, "run_tests", run_tests)
    monkeypatch.setattr(mutation, "run_mutant", lambda *a, **k: outcome)
    return unmutated_calls


def test_a_mutant_run_error_carries_pytests_cause_to_the_report(toy, tmp_path, monkeypatch):
    said = "pytest exited 4:\nERROR: not found: tests/test_guard.py::test_case[a]"
    outcome = mutation.Outcome("error", 1.0, 1, "k", "-a\n+b", ["t"], 30.0, said)
    _fake_mutant_runs(monkeypatch, outcome, ("passed", 0.1, ""))
    out, summary = tmp_path / "results.json", tmp_path / "summary.md"
    code = mutation.main(["--root", str(toy), "--out", str(out), "--summary", str(summary)])
    assert code == 1
    assert {r["reason"] for r in json.loads(out.read_text())} == {said}
    assert "> pytest exited 4:" in summary.read_text()
    assert "  `-a`" in summary.read_text()  # the mutant that erred
    assert "> ERROR: not found" in summary.read_text()


@pytest.mark.parametrize(
    ("unmutated", "status"),
    [(("passed", 0.1, ""), "timeout"),
     (("timeout", 40.0, "pytest still running after 40 s:\n"), "error")],
)  # fmt: skip
def test_a_timeout_counts_only_when_the_unmutated_tests_finish_in_time(
    toy, tmp_path, monkeypatch, unmutated, status
):
    everything = ["tests/test_guard.py"]
    outcome = mutation.Outcome("timeout", 40.0, 1, "k", "-a\n+b", everything, 40.0)
    calls = _fake_mutant_runs(monkeypatch, outcome, unmutated)
    out = tmp_path / "results.json"
    mutation.main(["--root", str(toy), "--workers", "1", "--out", str(out), "--report-only"])
    results = json.loads(out.read_text())
    assert results and {r["status"] for r in results} == {status}
    assert calls and {budget for _, budget in calls} == {40.0}  # the limit the mutant had
    if status == "error":
        assert all("also fail within 40 s" in r["reason"] for r in results)


@pytest.mark.parametrize(("status", "limit"), [("killed", 3000.0), ("timeout", 1000.0)])
def test_a_detected_mutant_is_rechecked_unmutated_and_keeps_no_output(
    toy, tmp_path, monkeypatch, status, limit
):
    # A kill is re-checked unmutated at three times the mutant's budget, a timeout at the limit
    # the mutant had; only an error keeps the test output.
    monkeypatch.setattr(mutation, "MIN_TIMEOUT", 1000.0)  # the budget, whatever the trace took
    everything = ["tests/test_guard.py"]
    said = "pytest exited 1:\nFAILED tests/test_guard.py::test_case"
    outcome = mutation.Outcome(status, 1.0, 1, "k", "-a\n+b", everything, 1000.0, said)
    calls = _fake_mutant_runs(monkeypatch, outcome, ("passed", 0.1, ""))
    out = tmp_path / "results.json"
    mutation.main(["--root", str(toy), "--workers", "1", "--out", str(out), "--report-only"])
    results = json.loads(out.read_text())
    assert results and {r["status"] for r in results} == {status}
    assert {r["reason"] for r in results} == {""}
    assert calls and {budget for _, budget in calls} == {limit}


def test_a_timeout_is_not_judged_by_an_unmutated_run_at_a_longer_limit(toy, tmp_path, monkeypatch):
    # A kill re-checks its tests unmutated at three times the budget; a later timeout on the same
    # tests asks whether they finish within its own, shorter limit, and must not reuse that pass.
    monkeypatch.setattr(mutation, "MIN_TIMEOUT", 1000.0)  # the budget, whatever the trace took
    everything = ["tests/test_guard.py"]
    outcomes = iter(
        [
            mutation.Outcome("killed", 1.0, 1, "a", "-a\n+b", everything, 1000.0, ""),
            mutation.Outcome("timeout", 1000.0, 1, "b", "-c\n+d", everything, 1000.0, ""),
        ]
    )
    real = mutation.run_tests

    def run_tests(worker, tests, budget, extra=None):
        if extra:  # the trace
            return real(worker, tests, budget, extra)
        if budget > 1500:
            return "passed", 1200.0, ""
        return "timeout", 1000.0, "pytest still running after 1000 s:\n"

    def run_mutant(*args, **kwargs):
        return next(outcomes, mutation.Outcome("survived", 1.0, 1, "z", "", everything, 1000.0))

    monkeypatch.setattr(mutation, "run_tests", run_tests)
    monkeypatch.setattr(mutation, "run_mutant", run_mutant)
    out = tmp_path / "results.json"
    mutation.main(["--root", str(toy), "--workers", "1", "--out", str(out), "--report-only"])
    statuses = {r["key"]: r["status"] for r in json.loads(out.read_text())}
    assert statuses["a"] == "killed" and statuses["b"] == "error"


def test_an_empty_pythonpath_adds_no_entry(tmp_path, monkeypatch):
    # An empty entry is the current directory, which would put the scratch root on sys.path.
    seen = {}

    def run_tests(worker, tests, budget, extra=None):
        seen.update(extra or {})
        return "passed", 0.1, ""

    monkeypatch.setattr(mutation, "run_tests", run_tests)
    monkeypatch.setenv("PYTHONPATH", "")
    (tmp_path / "w0").mkdir()
    mutation.trace(tmp_path / "w0", {"m.py": ["t.py"]}, ["m.py"])
    assert seen["PYTHONPATH"] == str(mutation.TRACE)


def test_merging_no_results_file_says_so(tmp_path):
    with pytest.raises(SystemExit, match=r"no results file at .*mutation-\*\.json"):
        mutation.main(["--merge", str(tmp_path / "mutation-*.json")])
