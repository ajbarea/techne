"""Tests for command_shapes.py: the phylax guards on background loops with no bound and on
`pkill -f` / `pgrep -f`.

The differential tests run each case under real bash, with logging stand-ins for pkill, pgrep
and a loop probe first on PATH, and hold the guard's verdict equal to what bash did: whether
pkill or pgrep ran with `-f`, and whether a loop ran with no `timeout` among its ancestors.
Quoted text, heredoc bodies and comments must not trip a guard; code bash runs must.
"""

from __future__ import annotations

import json
import os
import pathlib
import random
import shlex
import shutil
import subprocess
import sys

import pytest
from conftest import HOOK_PYTHON, ROOT, hook_env, hook_handlers, load_phylax_hooks, run_hook_handler

PLUGIN = ROOT / "plugins" / "phylax"
GUARDS = PLUGIN / "hooks" / "git_guards.py"
LOOPS = "block_background_loops"
FULL = "block_pkill_full"
BOTH = {LOOPS, FULL}
BASH = shutil.which("bash")


@pytest.fixture
def cs(monkeypatch):
    (mod,) = load_phylax_hooks(monkeypatch, "command_shapes")
    return mod


# --- the differential test against bash -------------------------------------------------

# A stand-in for pkill and pgrep that logs its name and arguments, and a loop probe that logs
# whether a `timeout` process is among the ancestors of the shell running its loop (its nearest
# shell ancestor; a `timeout` on the probe itself bounds one test, not the loop) and then ends
# the loop (exit 1 ends a
# `while`, 0 an `until`; `while ! probe` and `until ! probe` are not used).
STUB = """#!{python}
import os, sys
name = os.path.basename(sys.argv[0])
log = os.environ["SHAPE_LOG"]
if name.startswith("probe"):
    pid, bounded, top = os.getppid(), False, int(os.environ["SHAPE_TOP"])
    in_shell = False
    while pid > 1 and pid != top:  # up to the test, not the runner's own timeout
        with open(f"/proc/{{pid}}/stat") as f:
            stat = f.read()
        comm = stat[stat.index("(") + 1 : stat.rindex(")")]
        in_shell = in_shell or comm in ("bash", "sh")
        bounded = bounded or (in_shell and comm == "timeout")
        pid = int(stat[stat.rindex(")") + 2 :].split()[1])
    with open(log, "a") as f:
        f.write(("bounded" if bounded else "unbounded") + "\\n")
    sys.exit(1 if name == "probe" else 0)
with open(log, "a") as f:
    f.write(name + " " + " ".join(sys.argv[1:]) + "\\n")
"""


def bash_ran(command: str, tmp_path: pathlib.Path) -> list[str]:
    """Run COMMAND under bash in a scratch folder; the stand-ins' log lines."""
    return bash_run(command, tmp_path)[0]


def bash_run(command: str, tmp_path: pathlib.Path) -> tuple[list[str], str]:
    """Run COMMAND under bash in a scratch folder; the stand-ins' log lines and bash's stderr."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name in ("pkill", "pgrep", "probe", "probe_ok"):
        stub = bin_dir / name
        stub.write_text(STUB.format(python=sys.executable))
        stub.chmod(0o755)
    log = tmp_path / "log"
    log.write_text("")
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "SHAPE_LOG": str(log),
        "SHAPE_TOP": str(os.getpid()),
    }
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    proc = subprocess.run(
        [str(BASH), "-c", command], cwd=work, env=env, capture_output=True, timeout=30, check=False
    )
    return log.read_text().splitlines(), proc.stderr.decode(errors="replace")


def bash_parses(command: str) -> bool:
    """Whether bash's own parser accepts COMMAND (`bash -n`: read, never run)."""
    proc = subprocess.run([str(BASH), "-n", "-c", command], capture_output=True, timeout=30)
    return proc.returncode == 0


# Each case names pkill/pgrep only with -f and loops only on a probe, so what bash ran decides
# the verdict: a pkill or pgrep line means `-f` ran, an `unbounded` line an unbounded loop.
DIFFERENTIAL = [
    # pkill / pgrep as code
    "pkill -f marker",
    "cd . && pkill -f marker",
    "true; pgrep -f marker",
    "sudo -n true 2>/dev/null; pkill -f marker 2>/dev/null",
    "kill $(pgrep -f marker) 2>/dev/null",
    'echo "$(pgrep -af marker)"',
    "echo `pgrep -f marker`",
    "bash -c 'pkill -f marker'",
    'sh -c "pgrep -f marker"',
    "bash -lc 'pkill -f marker'",
    "eval 'pkill -f marker'",
    "timeout 5 pkill -f marker",
    "/usr/bin/timeout 5 pkill -f marker",
    "timeout --kill-after 5 10 pkill -f marker",
    "timeout --signal KILL 10 pgrep -f marker",
    "env --unset X pkill -f marker",
    "setsid pkill -f marker",
    "stdbuf -o L pgrep -f marker",
    "env A=1 pkill -f marker",
    "/usr/bin/env A=1 pkill -f marker",
    "echo x | xargs pkill -f",
    "flock -o lock pkill -f marker",
    "flock -o lock -c 'pkill -f marker'",
    "flock -o lock --command 'pkill -f marker'",
    'echo "${x:-$(pkill -f marker)}"',
    "echo ${x:-`pkill -f marker`}",
    "kill ${PID:-$(pgrep -f marker)} 2>/dev/null",
    "cat <<EOF\n${x:-$(pgrep -f marker)}\nEOF",
    "echo '${x:-$(pkill -f marker)}'",
    # quotes inside ${...} hide braces
    "echo ${x:-'{'}; pkill -f marker",
    "echo ${x:-'}'}; pkill -f marker",
    'echo "${x:-"}"}"; pkill -f marker',
    'echo ${x:-"{"}; pgrep -f marker',
    "echo \"${x:-'{'}\"; pkill -f marker",
    "echo ${x:-'a'}${y:-\"{\"}; pkill -f marker",
    # shells reading their commands from stdin
    "bash -s -- arg <<'EOF'\npkill -f marker\nEOF",
    "bash - <<'EOF'\npkill -f marker\nEOF",
    "bash /dev/stdin <<'EOF'\npgrep -f marker\nEOF",
    "eval \"$(cat <<'EOF'\npkill -f marker\nEOF\n)\"",
    "coproc pgrep -f marker",
    "time -p pkill -f marker",
    "bash <<'EOF'\npkill -f marker\nEOF",
    "bash <<< 'pgrep -f marker'",
    "cat <(pgrep -f marker)",
    "{ pkill -f marker; }",
    "( pgrep -f marker )",
    "if true; then pkill -f marker; fi",
    # corners the generated cases found
    "cat <<EOF\necho $(pgrep -af marker)\nEOF",  # an unquoted heredoc runs its $(...)
    "eval 'cat <<E\npgrep -f marker\nE'",  # eval's string is code read afresh
    "eval 'true # $(pgrep -f marker)'",
    "echo $(( echo $(pkill -f marker)\n)\n)",  # `$((` not closed by `))` is a subshell
    "echo $(( 1 + 2 ))",
    # arithmetic shifts are no heredocs; parentheses inside $(...) keep their own `)`
    "echo $((1<<2))\npkill -f marker",
    "(( mask = 1 << 2 ))\npgrep -f marker",
    "x=$(( 1<<2 )) && pkill -f marker",
    'echo "$(\nn=$((1+1))  # count what is left\necho $n\n)"; pkill -f marker',
    'echo "$( (echo a) # it\'s\n)"; pkill -f marker',
    'f() { :; }; echo "$(f() { :; }; f)"; pgrep -f marker',
    "echo ${x:- #}; pkill -f marker",
    "bash -c \"$(cat<<'EOF'\npkill -f marker\nEOF\n)\"",
    "flock --wait 5 lk pkill -f marker",
    "flock --wai 5 lk pkill -f marker",
    "flock --timeout 5 lk pgrep -f marker",
    # pkill / pgrep as text
    "echo $((1<<2)) # pkill -f marker",
    "cat <<'EOF'\necho $(pgrep -af marker)\nEOF",
    "echo 'pkill -f marker'",
    'echo "pkill -f marker"',
    "echo pkill -f marker",
    "printf '%s\\n' \"$(echo 'pkill -f marker')\"",
    'echo "$(echo "a; pkill -f marker")"',
    "cat > notes.txt <<'EOF'\npkill -f marker\nEOF",
    "cat <<EOF\npgrep -f marker\nEOF",
    "true # pkill -f marker",
    "echo -m \"$(cat <<'EOF'\nfix: stop pkill -f marker\nEOF\n)\"",
    "grep -n 'pkill -f' notes.txt 2>/dev/null",
    "pkill -x marker",
    "pgrep -x marker",
    "pkill -- -f",
    # loops as code
    "while probe; do :; done",
    "until probe_ok; do sleep 0; done",
    "x=1; while probe; do :; done",
    "for i in 1; do while probe; do :; done; done",
    "( while probe; do :; done )",
    "echo $(while probe; do :; done)",
    "bash -c 'until probe_ok; do :; done'",
    "nohup bash -c 'while probe; do :; done' >/dev/null 2>&1",
    "bash <<'EOF'\nwhile probe; do :; done\nEOF",
    "flock -o lock bash -c 'while probe; do :; done'",
    "timeout 5 true; while probe; do :; done",
    "until timeout 5 probe_ok; do :; done",
    "timeout 5 bash -c 'true' && while probe; do :; done",
    "/usr/bin/nohup bash -c 'while probe; do :; done' >/dev/null 2>&1",
    # loops bounded by timeout
    "/usr/bin/timeout 5 bash -c 'while probe; do :; done'",
    "timeout --kill-after 2 5 bash -c 'until probe_ok; do :; done'",
    "timeout 5 bash -c 'while probe; do :; done'",
    "timeout -k 2 5 bash -c 'until probe_ok; do :; done'",
    "flock -o lock timeout 5 bash -c 'while probe; do :; done'",
    "timeout 5 bash <<'EOF'\nwhile probe; do :; done\nEOF",
    'timeout 5 bash -c "echo $(echo hi) && while probe; do :; done"',
    'echo "${x:-$(while probe; do :; done)}"',
    # loops as text
    "echo 'while probe; do :; done'",
    "cat > w.sh <<'EOF'\nwhile probe; do :; done\nEOF",
    'echo "$(echo "x; while probe; do :; done")"',
    "true # while probe; do :; done",
    "echo while probe",
    '"while" 2>/dev/null; true',
]


needs_bash = pytest.mark.skipif(
    BASH is None or not pathlib.Path("/proc/self/stat").exists(), reason="needs bash and /proc"
)


def disagreement(cs, command: str, ran: list[str]) -> str | None:
    """How the guard's verdict on COMMAND differs from what bash RAN, or None."""
    full = any(
        line.split()[0] in ("pkill", "pgrep") and cs.full_match(line.split()[0], line.split()[1:])
        for line in ran
    )
    unbounded = "unbounded" in ran
    denies = cs.check(command, True, BOTH)
    said_full = cs.FULL_DENY["pkill"] in denies or cs.FULL_DENY["pgrep"] in denies
    if said_full != full or (cs.LOOP_DENY in denies) != unbounded:
        return f"{command!r}: bash ran {ran}, the guard said {[d[:40] for d in denies]}"
    return None


@needs_bash
@pytest.mark.parametrize("command", DIFFERENTIAL)
def test_verdicts_match_what_bash_runs(cs, tmp_path, command):
    assert disagreement(cs, command, bash_ran(command, tmp_path)) is None


# Generated cases: a shape (or a harmless command) under nested wrappers, each code or text.
SHAPES = [
    "pkill -f m",
    "pgrep -af m",
    "pkill -x m",
    "while probe; do :; done",
    "until probe_ok; do :; done",
    "true",
]


def _dq(text: str) -> str:
    """TEXT inside double quotes, as itself: what bash -c gets back is TEXT."""
    for ch in ("\\", '"', "$", "`"):
        text = text.replace(ch, "\\" + ch)
    return f'"{text}"'


WRAPS = [
    lambda c: f"bash -c {shlex.quote(c)}",
    lambda c: f"bash -c {_dq(c)}",  # not sh: dash rejects `<<<`, which the guard reads as bash
    lambda c: f"eval {shlex.quote(c)}",
    lambda c: f"timeout 5 bash -c {shlex.quote(c)}",
    lambda c: f"flock -o lock{len(c)} bash -c {shlex.quote(c)}",  # nested: a lock of its own
    lambda c: f"echo {shlex.quote(c)}",
    lambda c: f"echo {_dq(c)}",
    lambda c: f"echo $({c}\n)",
    lambda c: f'echo "$({c}\n)"',
    lambda c: f"{{ {c}\n}}",
    lambda c: f"( {c}\n)",
    lambda c: f"if true; then {c}\nfi",
    lambda c: f"x=1 && {c}",
    lambda c: f"true # {c}",
    # Each heredoc's delimiter is its own: a nested one ending on the outer's line is a syntax
    # error, which bash runs nothing of and the guard reads leniently (refusing).
    lambda c: f"cat > f <<'E{len(c)}'\n{c}\nE{len(c)}",
    # An unquoted heredoc holding a nested heredoc inside $(...) is a known over-refusal (below).
    lambda c: f"cat <<E{len(c)}\n{c}\nE{len(c)}" if "<<" not in c else c,
    lambda c: f"bash <<'E{len(c)}'\n{c}\nE{len(c)}",
    lambda c: f"timeout 5 bash <<'E{len(c)}'\n{c}\nE{len(c)}",
    lambda c: f"bash <<< {shlex.quote(c)}",
    lambda c: f"nohup bash -c {shlex.quote(c)} >/dev/null 2>&1",
    # an unset name: the guard reads a default's code as run, which it is only when unset
    lambda c: f'echo "${{unset_369:-$({c}\n)}}"',
    lambda c: f"script -qc {shlex.quote(c)} /dev/null",
    lambda c: f"function f{len(c)} {{ {c}\n}}; f{len(c)}",
    lambda c: f"bash -s x <<'E{len(c)}'\n{c}\nE{len(c)}",
    lambda c: f"bash -c \"$(cat <<'E{len(c)}'\n{c}\nE{len(c)}\n)\"",
    lambda c: f"flock lock{len(c)} --command {shlex.quote(c)}",
    lambda c: f"flock lock{len(c)} bash -c {shlex.quote(c)}",
    # arithmetic shifts, parentheses and comments with apostrophes before and inside $(...)
    lambda c: f"echo $((1<<2))\n{c}",
    lambda c: f"(( m = 1 << 2 ))\n{c}",
    lambda c: f'echo "$(\nn=$((1+1))  # what\'s left\n{c}\n)"',
    lambda c: f'echo "$( (echo a) # it\'s\n{c}\n)"',
    lambda c: f"echo ${{unset_369:- #}}; {c}",
    lambda c: f"x=1 # it's a comment\n{c}",
    lambda c: f"echo ${{unset_369:-'}}'}}; {c}",
    lambda c: f'echo "${{unset_369:-"{{"}}"; {c}',
    lambda c: f"echo \"${{unset_369:-'}}'}}\"; {c}",
    lambda c: f"bash -s -- arg <<'E{len(c)}'\n{c}\nE{len(c)}",
    lambda c: f"eval \"$(cat <<'E{len(c)}'\n{c}\nE{len(c)}\n)\"",
]
GENERATED = 250


def generated(seed: int = int(os.environ.get("SHAPE_SEED", "369"))) -> list[str]:
    rng = random.Random(seed)
    out = []
    for _ in range(GENERATED):
        command = rng.choice(SHAPES)
        for _ in range(rng.randint(1, 3)):
            command = rng.choice(WRAPS)(command)
        out.append(command)
    return out


@needs_bash
def test_generated_verdicts_match_what_bash_runs(cs, tmp_path):
    cases = generated()
    found = []
    for c in cases:
        ran, stderr = bash_run(c, tmp_path)
        try:
            found.append(disagreement(cs, c, ran))
        except ValueError as exc:
            # The check may fail closed only on text bash rejects too, when it parses it or
            # when it reaches it (a broken `eval` or `bash -c` string).
            broken = "syntax error" in stderr or "unexpected EOF" in stderr
            if bash_parses(c) and not broken:
                found.append(f"{c!r}: the check raised on valid bash: {exc}")
    assert [f for f in found if f] == []

    # The generator reached every verdict, so the agreement is not vacuous.
    def verdict(c: str) -> tuple[str, ...]:
        try:
            return tuple(cs.check(c, True, BOTH))
        except ValueError:
            return ("raised",)

    verdicts = {verdict(c) for c in cases}
    assert (cs.LOOP_DENY,) in verdicts and () in verdicts
    assert any(cs.FULL_DENY["pkill"] in v for v in verdicts)
    assert any(cs.FULL_DENY["pgrep"] in v for v in verdicts)


def test_the_differential_cases_cover_both_verdicts(tmp_path):
    """Guard against a stand-in that never logs: some cases must run each shape."""
    assert bash_ran("pkill -f m; while probe; do :; done", tmp_path) == [
        "pkill -f m",
        "unbounded",
    ]
    assert bash_ran("timeout 5 bash -c 'while probe; do :; done'", tmp_path)[-1:] == ["bounded"]


# --- labeled cases bash cannot judge ------------------------------------------------------


@pytest.mark.parametrize(
    ("args", "want"),
    [
        (["-f", "x"], True),
        (["-af", "x"], True),
        (["-fa", "x"], True),
        (["--full", "x"], True),
        (["--fu", "x"], True),
        (["x", "-f"], True),  # getopt reads options after the pattern
        (["-9", "-f", "x"], True),
        (["-x", "x"], False),
        (["-F", "pidfile"], False),
        (["-u", "f", "x"], False),  # -u takes the next word
        (["-uf", "x"], False),  # -u takes the rest of the word
        (["-P", "1", "x"], False),
        (["--signal", "-f", "x"], False),
        (["--signal=KILL", "-f", "x"], True),
        (["--", "-f"], False),
        (["-"], False),
        (["--fullx"], False),
        (["--f", "x"], True),  # getopt_long takes a unique prefix
    ],
)
def test_pgrep_options_read_as_procps_reads_them(cs, args, want):
    assert cs.full_match("pgrep", args) is want


@pytest.mark.parametrize(
    ("args", "want"),
    [
        (["-XFSZ", "x"], False),
        (["-xfsz", "x"], False),
        (["-SIGKILL", "x"], False),
        (["-RTMIN+1", "x"], False),
        (["-15", "-f", "x"], True),
        (["-HUP", "-af", "x"], True),
    ],
)
def test_pkill_reads_a_signal_as_no_option(cs, args, want):
    assert cs.full_match("pkill", args) is want


def test_pgrep_reads_a_signal_name_as_options(cs):
    """pgrep takes no -SIGNAL, so `-fxsz` holds -f there."""
    assert cs.full_match("pgrep", ["-fxsz", "x"]) is True


@pytest.mark.parametrize(
    "command",
    [
        "until gh pr checks 3 || [ $SECONDS -gt 1800 ]; do sleep 30; done",
        "while [ ${SECONDS} -lt 600 ] && ! test -f done; do sleep 5; done",
        "while (( SECONDS < 600 )); do sleep 5; done",
        "timeout 600 bash -c 'until gh pr checks 3; do sleep 30; done'",
        "gh pr checks 3 --watch --fail-fast",
        "sleep 600",
        "for i in 1 2 3; do sleep 1; done",
        "until x; do [ $SECONDS -gt 9 ] && break; sleep 1; done",  # a clock test that breaks out
        "while true; do if [ $SECONDS -gt 60 ]; then break; fi; sleep 1; done",
        "while true; do (( SECONDS > 60 )) && exit 1; sleep 1; done",
        "while read -r l; do echo $l; done < notes.txt",
        "while IFS= read -r l; do echo $l; done <<< 'a b'",
        "while read -r l; do echo $l; done <<'EOF'\na\nEOF",
        "timeout $T bash -c 'until x; do sleep 1; done'",  # a duration this check cannot read
        "timeout 1.5m bash -c 'until x; do sleep 1; done'",
    ],
)
def test_a_bounded_background_wait_passes(cs, command):
    assert cs.check(command, True, BOTH) == []


@pytest.mark.parametrize(
    "command",
    [
        "until gh pr checks 3; do sleep 30; done",
        "while true; do sleep 1; done",
        "until x; do sleep 1; done; echo $SECONDS",  # the clock is read after the loop
        "until x; do echo $SECONDS; sleep 1; done",  # read in the body, but nothing breaks out
        "while [ 1 ]; do while [ $SECONDS -lt 9 ]; do sleep 1; done; done",
        "timeout 0 bash -c 'while true; do sleep 1; done'",  # GNU timeout: 0 is no limit
        "timeout -s KILL 0s bash -c 'while true; do sleep 1; done'",
        "/usr/bin/nohup bash -c 'while true; do sleep 1; done'",
        "while read -r l; do :; done < f; until x; do sleep 1; done",
        "tail -f log | while read l; do echo $l; done",  # a pipe that never ends
        "gh run watch 5 | while read l; do echo $l; done",
        "git ls-files | while read f; do echo $f; done",
        "while read l; do echo $l; done < <(tail -f log)",
        "timeout inf bash -c 'while true; do sleep 1; done'",
        "timeout infinity bash -c 'while true; do sleep 1; done'",
        "script -qc 'while true; do sleep 1; done' /dev/null",
    ],
)
def test_an_unbounded_background_wait_is_refused(cs, command):
    assert cs.check(command, True, BOTH) == [cs.LOOP_DENY]


@pytest.mark.parametrize(
    ("command", "want"),
    [
        ("pkill -x -fpe foo", True),  # procps reads -SIGNAL from argv[1] only: -f -p e
        ("pkill -fpe foo", False),  # the first argument: SIGFPE, any case (checked on procps 4)
        ("pkill -FPE foo", False),
        ("flock /tmp/l --command 'pkill -f x'", True),
        ("flock /tmp/l -c 'pkill -f x'", True),
        # flock rejects these (exit 64, or runs a program named --command=...), so nothing runs
        ("flock /tmp/l --command='pkill -f x'", False),
        ("flock -xc 'pkill -f x' /tmp/l", False),
        ("flock -w 5 /tmp/l -c 'pkill -f x'", True),
        ("flock /tmp/l pkill -f x", True),  # flock stops reading options at its lock file
        ("flock /tmp/l pkill -x x", False),
        ("script -qc 'pkill -f x' /dev/null", True),
        ("script --command='pkill -f x' /dev/null", True),
        ("script -q log.txt", False),
        ("busybox sh -c 'pkill -f x'", True),
        ("coproc pkill -f x", True),
        # a line continuation joins the lines, as bash reads it
        ("pkill \\\n-f marker", True),
        ("./time pkill -x x", False),
        ("./scripts/pkill -f x", False),  # a program of its own, not procps
        ("~/bin/pgrep -f x", False),
        ("/usr/bin/pkill -f x", True),
    ],
)
def test_wrappers_that_run_a_command_string(cs, command, want):
    assert (cs.check(command, False, {FULL}) != []) is want


@pytest.mark.parametrize(
    ("command", "want"),
    [
        ("function w { while true; do sleep 5; done; }; w", [True]),
        ("coproc while true; do sleep 1; done", [True]),
        ("bash -c \"$(cat <<'EOF'\nwhile true; do sleep 5; done\nEOF\n)\"", [True]),
        ("bash -s x <<'EOF'\nwhile true; do sleep 5; done\nEOF", [True]),
        ("bash -s <<< 'while true; do sleep 5; done'", [True]),
        ("for ((;;)); do sleep 5; done", [True]),
        ("for ((;;)); do [ $SECONDS -gt 1800 ] && break; sleep 1; done", [False]),
        ("for ((;;)); do sleep 1; done; for ((;;)); do sleep 1; done", [True]),
        ("for (( ; ; )); do sleep 5; done", [True]),
        ("for ((i=0; i<3; i++)); do sleep 1; done", [False]),
        ("T=/usr/bin/timeout bash -c 'while true; do :; done'", [True]),  # an assignment
        ("sudo -u timeout bash -c 'while true; do :; done'", [True]),  # a flag's value
        ("timeout 60 bash -c 'while true; do :; done'", [False]),
        (
            "until gh pr checks 1; do if (( SECONDS > 1800 )); then echo late >&2; exit 1; fi;"
            " sleep 30; done",
            [False],
        ),
        ("until x; do [ $SECONDS -gt 1800 ] && { echo late; exit 1; }; sleep 30; done", [False]),
        # a clock that is only printed bounds nothing
        (
            'while true; do echo "t=$SECONDS"; if gh pr checks 1; then break; fi; sleep 30; done',
            [True],
        ),
        ("while true; do echo $SECONDS; [ -f done ] && break; sleep 1; done", [True]),
        ("while true; do read l < /dev/tty; done", [True]),
        # `&` detaches the loop even in a foreground call: refused (see the foreground table)
        (
            "while true; do [ $SECONDS -gt 600 ] && echo slow;"
            " if gh pr checks 1; then break; fi; sleep 30; done",
            [True],
        ),
        (
            "while true; do [ $SECONDS -gt 9 ] && echo late; [ -f done ] && break; sleep 1; done",
            [True],
        ),
        (
            "while true; do if [ $SECONDS -gt 9 ]; then echo late; else break; fi; sleep 1; done",
            [True],
        ),
        (
            "while true; do if [ $SECONDS -gt 9 ]; then echo late; exit 1; fi; sleep 1; done",
            [False],
        ),
        ("while read l; do :; done < /dev/tty", [True]),
        ("while read l; do :; done < /dev/null", [False]),
        # a script that shares a wrapper's name is no wrapper
        ("./timeout 5 bash -c 'while true; do :; done'", [False]),  # a script: its args unread
        ("/usr/bin/timeout 5 bash -c 'while true; do :; done'", [False]),
        ("until x; do echo $SECONDS; sleep 30; done; exit 1", [True]),  # the exit is after done
        # a break that leaves only an inner loop, an exit that leaves only a subshell
        ("while true; do for i in 1; do [ $SECONDS -gt 9 ] && break; done; sleep 1; done", [True]),
        ("while true; do ( [ $SECONDS -gt 9 ] && exit ); sleep 1; done", [True]),
        (
            "while true; do for i in 1; do [ $SECONDS -gt 9 ] && break 2; done; sleep 1; done",
            [False],
        ),
        # `return` outside a function only errors, and a bash -c runs at the top level
        ("while true; do [ $SECONDS -gt 9 ] && return; sleep 1; done", [True]),
        # the consequent is the test's own and-or list, not what follows a `;` or a newline
        ("while true; do [ $SECONDS -gt 0 ] && echo slow; false && break; sleep 1; done", [True]),
        ("while true; do [ $SECONDS -gt 600 ] && echo slow; gh pr checks 1 && break; done", [True]),
        ("while true; do (( e = SECONDS )); false && exit 0; sleep 1; done", [True]),
        ("while true; do [ $SECONDS -gt 9 ]\nbreak; done", [True]),
        ("while true; do [ $SECONDS -gt 9 ] && { echo late; exit 1; }; sleep 1; done", [False]),
        ("while true; do if [ $SECONDS -gt 9 ]; then echo late; break; fi; sleep 1; done", [False]),
        ("until read l; do sleep 1; done < notes.txt", [True]),  # loops forever at end of input
        ("time -p while true; do sleep 1; done", [True]),
    ],
)
def test_review_round_2_loop_shapes(cs, command, want):
    """Each loop shape: whether it is refused in the background."""
    assert [cs.LOOP_DENY in cs.check(command, True, {LOOPS})] == want


@pytest.mark.parametrize(
    "command",
    [
        "pkill -f mutate.py",  # 11-02 and 11-09: exit 144, a mutant left in a tracked file
        'pkill -f "http.server 8765" 2>/dev/null; python3 -m http.server 8765 &',  # 11-14
        "kill $(pgrep -f 'scripts/mutation.py') 2>/dev/null || true",
    ],
)
def test_the_live_failures_are_refused(cs, command):
    """The commands that ended their own shell (techne#331), each refused."""
    assert cs.check(command, False, {FULL}) != []


def test_a_foreground_loop_passes(cs):
    assert cs.check("while true; do sleep 1; done", False, BOTH) == []


@pytest.mark.parametrize(
    ("command", "refused"),
    [
        # `&` runs the loop in the background of a foreground call (the 11-17 failure)
        ("nohup bash -c 'until gh pr checks 1; do sleep 30; done' >/dev/null 2>&1 &", True),
        ("while true; do sleep 1; done &", True),
        ("setsid bash -c 'while true; do sleep 1; done' &", True),
        ("(while true; do sleep 1; done) &", True),
        ("while true; do sleep 1; done | tee log &", True),
        ("{ while true; do sleep 1; done; } &", True),
        ("until a; do :; done && echo hi &", True),
        ("(sleep 1; while true; do sleep 1; done) &", True),
        ("for ((;;)); do sleep 1; done &", True),
        ("for ((;;)); do [ $SECONDS -gt 9 ] && break; sleep 1; done &", False),
        ("for ((i=0;i<3;i++)); do sleep 1; done &", False),
        ("while true; do sleep 1; done; echo hi &", False),
        ("{ while true; do sleep 1; done; } > log 2>&1 &", True),
        ("(while true; do sleep 1; done) > log 2>&1 &", True),
        ("while true; do sleep 1; done | tee log &", True),
        ("while true; do sleep 1; done |& tee log &", True),
        # a loop detached inside a timeout shell outlives the timeout
        ("timeout 60 bash -c 'while true; do sleep 1; done &'", True),
        ("timeout 60 bash -c 'nohup bash -c \"while true; do sleep 1; done\" &'", True),
        ("timeout 60 setsid -f bash -c 'while true; do sleep 1; done'", True),
        ("setsid -f timeout 60 bash -c 'while true; do sleep 1; done'", False),
        ("timeout 60 setsid bash -c 'while true; do sleep 1; done'", False),
        ("timeout 60 bash -c 'while true; do sleep 1; done' &", False),
        ("nohup sleep 5 &", False),
        ("while true; do sleep 1; done; echo done &", False),
        ("until x || [ $SECONDS -gt 9 ]; do sleep 1; done &", False),
    ],
)
def test_a_loop_that_ampersand_detaches_counts_as_background(cs, command, refused):
    assert (cs.check(command, False, {LOOPS}) != []) is refused


@pytest.mark.parametrize(
    ("word", "name"),
    [
        ("sudo", "sudo"),
        ("/usr/bin/sudo", "sudo"),
        ("/bin/timeout", "timeout"),
        ("/usr/local/bin/nice", "nice"),
        ("./timeout", ""),
        ("scripts/timeout", ""),
        ("/home/u/bin/sudo", ""),
        ("~/bin/pkill", ""),
    ],
)
def test_wrapper_name_counts_a_path_only_in_a_system_folder(cs, word, name):
    assert cs.wrapper_name(word) == name


def test_flock_long_options_read_as_getopt_long_reads_them(cs):
    """--wait is --timeout's alias and any unique prefix works (util-linux 2.39)."""
    assert cs._long("--wai", cs.FLOCK_LONG) == "--wait"
    assert cs._long("--timeout", cs.FLOCK_LONG) == "--timeout"
    assert cs._long("--no", cs.FLOCK_LONG) == "--no"  # --nonblock or --no-fork: ambiguous
    assert cs._long("--", cs.FLOCK_LONG) == "--"
    # before its lock file flock rejects --command, so nothing is read from it
    assert cs.check("flock --command 'pkill -f x' lk", False, {FULL}) == []


def test_an_unclosed_unquoted_heredoc_substitution_refuses(cs):
    """The body of an unquoted heredoc runs its $(...): one that never closes is refused."""
    with pytest.raises(ValueError, match="never closed"):
        cs.check("cat <<EOF\nx $(pkill -x y\nEOF", False, {FULL})


def test_each_option_refuses_only_its_own_shape(cs):
    command = "pkill -f x; while true; do sleep 1; done"
    assert cs.check(command, True, {LOOPS}) == [cs.LOOP_DENY]
    assert cs.check(command, True, {FULL}) == [cs.FULL_DENY["pkill"]]
    assert cs.check(command, True, set()) == []


def test_pkill_and_pgrep_get_their_own_refusal_once(cs):
    denies = cs.check("pkill -f a; pkill -f b; pgrep -f c", False, {FULL})
    assert denies == [cs.FULL_DENY["pkill"], cs.FULL_DENY["pgrep"]]


def test_refusals_name_the_form_that_works(cs):
    assert "timeout 1800 bash -c" in cs.LOOP_DENY
    assert "gh pr checks N --watch --fail-fast" in cs.LOOP_DENY
    assert "$SECONDS" in cs.LOOP_DENY
    assert "pkill -x NAME" in cs.FULL_DENY["pkill"] and "`kill PID`" in cs.FULL_DENY["pkill"]
    assert "pgrep -x NAME" in cs.FULL_DENY["pgrep"]


@pytest.mark.parametrize("wrap", ["eval {}", "echo $({})", "bash -c {}"])
def test_nesting_past_the_limit_refuses(cs, wrap):
    """A command nested deeper than MAX_DEPTH cannot be read through, so the check fails (and
    the hook refuses, saying why); one level less is read."""

    def nest(levels: int, inner: str) -> str:
        # json.dumps escapes a quote by one backslash a level, so the text roughly doubles a
        # level; shlex.quote grows about fivefold a level and runs a 17-level case out of memory.
        for _ in range(levels):
            inner = wrap.format(
                json.dumps(inner) if wrap.endswith("{}") and "$(" not in wrap else inner
            )
        return inner

    deep = nest(cs.MAX_DEPTH + 1, "pkill -x a")
    assert len(deep) < 1 << 21  # a bound on the case itself: the test must stay cheap
    with pytest.raises(ValueError, match="more than 16 deep"):
        cs.check(deep, False, {FULL})
    assert cs.check(nest(cs.MAX_DEPTH - 1, "pkill -f x"), False, {FULL}) == [cs.FULL_DENY["pkill"]]


@pytest.mark.parametrize(
    "command",
    [
        "pkill -x a; echo 'unterminated",
        'pkill -x a; echo "unterminated',
        "pkill -x a; echo $(unterminated",
        "pkill -x a; echo ${x",
        "pkill -x a; `x",
    ],
)
def test_text_bash_would_reject_is_refused(cs, command):
    """An open quote, substitution or ${ runs to the end, hiding whatever follows it: bash
    rejects the command, so refusing it costs an honest command nothing."""
    with pytest.raises(ValueError, match="never closed"):
        cs.check(command, True, BOTH)


# --- known gaps, pinned so a change to them is seen --------------------------------------

# These run pkill -f or an unbounded loop, but the guard does not see it: the name is built
# at run time, or the code is in a file or a pipe. The guards catch an honest agent's slip,
# not a hostile one (docs/configuration.md says so); a change here updates those docs.
KNOWN_GAPS = [
    "P=pkill; $P -f marker",
    "echo 'pkill -f marker' | bash",
    "printf 'pkill -f marker' > s.sh; bash s.sh",
    'bash -c "$CMD"',
    # a clock test that is always true still reads as a bound
    "while [ $SECONDS -ge 0 ]; do sleep 30; done",
    # a `case` pattern's `)` inside $(...) ends the substitution early here
    "x=$(case a in a) while true; do sleep 1; done;; esac)",
]


def test_known_over_refusal_nested_heredoc_in_an_unquoted_heredoc(cs, tmp_path):
    """Bash runs nothing for this; the guard reads the inner body as code and refuses, which
    errs toward safety on a shape no honest command takes."""
    command = "cat <<E1\nbash <<< 'bash -c \"$(cat <<'\"'\"'E2'\"'\"'\npkill -f m\nE2\n)\"'\nE1"
    assert bash_ran(command, tmp_path) == []
    assert cs.check(command, False, {FULL}) != []


@pytest.mark.parametrize("command", KNOWN_GAPS)
def test_known_gaps_pass_unseen(cs, command):
    assert cs.check(command, True, BOTH) == []


@pytest.mark.parametrize("command", ["p''kill -f marker", "pk\\ill -f marker"])
def test_known_gap_a_split_name_has_no_word_to_find(cs, command):
    """bash runs pkill, but the text holds no `pkill`: the word check, which keeps every other
    call off the lexer, never starts, in check() or in the hook."""
    assert cs.check(command, False, {FULL}) == []
    assert reason(run_guard(bash_payload(command), [FULL])) is None


# --- the hook, as Claude Code and Antigravity run it --------------------------------------


def bash_payload(command: str, background: bool | None = None) -> str:
    tool_input: dict = {"command": command}
    if background is not None:
        tool_input["run_in_background"] = background
    return json.dumps({"tool_name": "Bash", "tool_input": tool_input, "cwd": str(ROOT)})


def run_guard(stdin: str, on, shapes: bool = True) -> subprocess.CompletedProcess:
    """Run git_guards.py as hooks.json does: with --shapes while a shape option is on."""
    return subprocess.run(
        [HOOK_PYTHON, str(GUARDS), *(["--shapes"] if shapes else [])],
        input=stdin,
        capture_output=True,
        text=True,
        env=hook_env(on),
        check=False,
        timeout=60,
    )


def reason(proc: subprocess.CompletedProcess) -> str | None:
    assert proc.returncode == 0, proc.stderr
    if not proc.stdout.strip():
        return None
    out = json.loads(proc.stdout)
    if "hookSpecificOutput" in out:
        assert set(out) == {"hookSpecificOutput"}, out
        spec = out["hookSpecificOutput"]
        assert spec["permissionDecision"] == "deny"
        return spec["permissionDecisionReason"]
    assert out["decision"] == "deny", out
    return out["reason"]


@pytest.mark.parametrize("handler", hook_handlers("phylax", "PreToolUse", "Bash"))
def test_the_hooks_json_handler_refuses_each_shape(handler):
    for option, stdin, want in [
        (FULL, bash_payload("pkill -f marker"), "pkill -f"),
        (LOOPS, bash_payload("until gh pr checks 3; do sleep 30; done", True), "timeout"),
    ]:
        proc = run_hook_handler("phylax", handler, stdin, hook_env([option]))
        assert want in (reason(proc) or ""), proc.stderr
        proc = run_hook_handler("phylax", handler, stdin, hook_env([]))
        assert proc.returncode == 0 and proc.stdout == "", proc.stderr


@pytest.mark.parametrize(
    ("stdin", "on", "want"),
    [
        (bash_payload("pkill -f marker"), [FULL], "`pkill -f`"),
        (bash_payload("sudo pgrep -af marker"), [FULL], "`pgrep -f`"),
        (bash_payload("pkill -x marker"), [FULL], None),
        (bash_payload("pkill -f marker"), [LOOPS], None),
        (bash_payload("pkill -f marker"), [], None),
        (bash_payload("while true; do sleep 1; done", True), [LOOPS], "no `timeout`"),
        (bash_payload("while true; do sleep 1; done", False), [LOOPS], None),
        (bash_payload("while true; do sleep 1; done"), [LOOPS], None),
        (bash_payload("while true; do sleep 1; done", True), [FULL], None),
        # JSON may spell a letter as an escape
        (bash_payload("pkill -f x").replace("pkill", "\\u0070kill"), [FULL], "`pkill -f`"),
        # the git guards still run when a shape option is on with them
        (
            bash_payload("git commit -m 'x\n\nCo-Authored-By: Claude <noreply@anthropic.com>'"),
            [FULL, "block_attribution_trailers"],
            "attribution",
        ),
    ],
)
def test_the_guard_refuses_only_an_enabled_shape(stdin, on, want):
    got = reason(run_guard(stdin, on))
    assert (got is None) if want is None else (got is not None and want in got), got


def test_antigravity_commands_count_as_background():
    """agy backgrounds every run_command after at most 10 s, so an untimed loop is refused."""
    loop = "until gh pr checks 3; do sleep 30; done"
    stdin = json.dumps({"toolCall": {"name": "run_command", "args": {"CommandLine": loop}}})
    assert "no `timeout`" in (reason(run_guard(stdin, [LOOPS])) or "")


def test_nesting_too_deep_to_read_is_refused_with_its_reason():
    command = "echo " + "$(" * 60 + "pkill -x a" + ")" * 60  # the word passes the prefilter
    proc = run_guard(bash_payload(command), [FULL])
    assert proc.returncode == 2 and proc.stdout == ""
    assert "nests $(...) more than 50 deep" in proc.stderr


def test_a_shape_refusal_reaches_antigravity_in_its_own_shape():
    stdin = json.dumps({"toolCall": {"name": "run_command", "args": {"CommandLine": "pkill -f x"}}})
    proc = run_guard(stdin, [FULL])
    assert json.loads(proc.stdout) == {"decision": "deny", "reason": proc_reason(proc)}


def proc_reason(proc: subprocess.CompletedProcess) -> str:
    return json.loads(proc.stdout)["reason"]


def test_a_mod_checked_call_still_gets_the_shape_checks(monkeypatch):
    """The mod stamps the git calls it checked, and the fallback stands down for those; the
    mod runs no shape check, so the fallback must still run them."""
    stdin = json.loads(bash_payload("git status; pkill -f marker"))
    stdin["tool_use_id"] = "toolu_1"
    env = hook_env([FULL, "block_commits_md"], PHYLAX_GUARD_CHECKED="toolu_1")
    proc = subprocess.run(
        [HOOK_PYTHON, str(GUARDS), "--shapes"],
        input=json.dumps(stdin),
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=60,
    )
    assert "`pkill -f`" in (reason(proc) or "")


def test_a_shape_check_that_crashes_refuses_the_command():
    """A command that is not text crashes the check: with a shape guard on, it fails closed
    and says why on stderr, which reaches Claude with exit 2."""
    stdin = json.dumps({"tool_name": "Bash", "tool_input": {"command": ["pkill", "-f", "x"]}})
    proc = run_guard(stdin, [FULL])
    assert proc.returncode == 2
    assert "phylax shape guard error" in proc.stderr and "not run" in proc.stderr


def test_a_git_check_crash_still_follows_the_git_guards_rule():
    """A shape option on does not make a crash in the git checks refuse: with only the warning
    git guard on, a git check that fails lets the command run (exit 1), as before."""
    stdin = json.dumps({"tool_name": "Bash", "tool_input": {"command": "git commit -m x"}})
    proc = run_guard(stdin, [FULL, "warn_main_checkout_commit"])  # no cwd: the check fails
    assert proc.returncode == 1, proc.stderr


def test_a_call_without_the_words_starts_no_check(monkeypatch):
    """The prefilter: a call that cannot hold a shape exits before command_shapes loads."""
    (gg,) = load_phylax_hooks(monkeypatch, "git_guards")
    assert gg.may_hold_shape('{"tool_input": {"command": "ls"}}') is False
    for word in ("pkill", "pgrep", "while", "until", "((", "\\u0070kill"):
        assert gg.may_hold_shape('{"command": "x ' + word + ' y"}') is True, word
    # no run_in_background needed: `&` detaches a loop in a foreground call
    assert gg.may_hold_shape('{"command": "nohup bash -c \'until x\' &"}') is True
    assert gg.may_hold_shape('{"command": "sleep 1", "run_in_background": true}') is False


@pytest.mark.parametrize("command", ["ls -la", "git status", "echo hi"])
def test_a_decoded_command_without_the_words_is_not_lexed(cs, command):
    """A payload that holds a `\\u` escape (an em dash) is decoded and checked for the words
    first, so an ordinary command never reaches the lexer."""
    assert cs.may_hold(command) is False
    assert cs.check(command + " # \u2014", True, BOTH) == []


def test_no_option_is_read_for_a_call_without_the_words(monkeypatch):
    """The hot path: a call that cannot hold a shape reads no shape option at all."""
    (gg, go) = load_phylax_hooks(monkeypatch, "git_guards", "git_options")
    read: list[str] = []
    real = go.option_on
    monkeypatch.setattr(go, "option_on", lambda k: read.append(k) or real(k))
    monkeypatch.setattr(sys, "argv", ["git_guards.py", "--shapes"])
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO(bash_payload("ls -la")))
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_BLOCK_PKILL_FULL", "true")
    assert gg.main() == 0
    assert not set(read) & BOTH


def test_without_the_flag_no_shape_is_checked():
    """hooks.json passes --shapes only while a shape option is on; without it, none runs."""
    assert reason(run_guard(bash_payload("pkill -f marker"), [FULL], shapes=False)) is None


@pytest.mark.parametrize(
    ("on", "flag"),
    [([FULL], True), ([LOOPS], True), (BOTH, True), (["block_commits_md"], False)],
)
def test_hooks_json_passes_the_flag_exactly_while_a_shape_option_is_on(tmp_path, on, flag):
    """The handler's own sh decides --shapes: a stand-in python3 prints its arguments."""
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "python3").write_text('#!/bin/sh\necho "$@"\n')
    (fake / "python3").chmod(0o755)
    for handler in hook_handlers("phylax", "PreToolUse", "Bash"):
        shell = handler["command"].replace("${CLAUDE_PLUGIN_ROOT}", str(PLUGIN))
        env = {**hook_env(on), "PATH": f"{fake}:/usr/bin:/bin"}
        proc = subprocess.run(
            ["sh", "-c", shell], input="{}", capture_output=True, text=True, env=env, check=False
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip().endswith("--shapes") is flag, proc.stdout


@pytest.mark.parametrize("handler", hook_handlers("phylax", "PreToolUse", "Bash"))
def test_a_missing_python3_refuses_while_a_shape_option_is_on(tmp_path, handler):
    """No python3 means no check: with a shape option on the call is refused (exit 2) and says
    why, rather than running unchecked."""
    empty = tmp_path / "bin"  # a PATH with cat, as any machine has, and no python3
    empty.mkdir()
    (empty / "cat").symlink_to(shutil.which("cat") or "/bin/cat")
    shell = handler["command"].replace("${CLAUDE_PLUGIN_ROOT}", str(PLUGIN))
    env = {**hook_env([FULL]), "PATH": str(empty)}

    def run(command: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["/bin/sh", "-c", shell],
            input=bash_payload(command),
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

    refused = run("pkill -x server")
    assert refused.returncode == 2 and "python3 is not on PATH" in refused.stderr
    # A call that cannot hold a shape still runs, so the user can install python3.
    assert run("ls -la").returncode == 0
