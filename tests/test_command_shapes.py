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
    subprocess.run(
        [str(BASH), "-c", command], cwd=work, env=env, capture_output=True, timeout=30, check=False
    )
    return log.read_text().splitlines()


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
    "env A=1 pkill -f marker",
    "echo x | xargs pkill -f",
    "flock -o lock pkill -f marker",
    "flock -o lock -c 'pkill -f marker'",
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
    # pkill / pgrep as text
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
    "p''kill -f marker",
    "pk\\ill -f marker",
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
    # loops bounded by timeout
    "timeout 5 bash -c 'while probe; do :; done'",
    "timeout -k 2 5 bash -c 'until probe_ok; do :; done'",
    "flock -o lock timeout 5 bash -c 'while probe; do :; done'",
    "timeout 5 bash <<'EOF'\nwhile probe; do :; done\nEOF",
    'timeout 5 bash -c "echo $(echo hi) && while probe; do :; done"',
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
    lambda c: f"cat <<E{len(c)}\n{c}\nE{len(c)}",
    lambda c: f"bash <<'E{len(c)}'\n{c}\nE{len(c)}",
    lambda c: f"timeout 5 bash <<'E{len(c)}'\n{c}\nE{len(c)}",
    lambda c: f"bash <<< {shlex.quote(c)}",
    lambda c: f"nohup bash -c {shlex.quote(c)} >/dev/null 2>&1",
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
    found = [disagreement(cs, c, bash_ran(c, tmp_path)) for c in cases]
    assert [f for f in found if f] == []
    # The generator reached every verdict, so the agreement is not vacuous.
    verdicts = {tuple(cs.check(c, True, BOTH)) for c in cases}
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
        "until x; do [ $SECONDS -gt 9 ] && break; sleep 1; done",  # in the body, not the test
        "while [ 1 ]; do while [ $SECONDS -lt 9 ]; do sleep 1; done; done",
    ],
)
def test_an_unbounded_background_wait_is_refused(cs, command):
    assert cs.check(command, True, BOTH) == [cs.LOOP_DENY]


def test_a_foreground_loop_passes(cs):
    assert cs.check("while true; do sleep 1; done", False, BOTH) == []


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


def test_nesting_past_the_limit_is_not_read(cs):
    """A bound on recursion: a command nested deeper than MAX_DEPTH is not followed."""
    inner = "pkill -f x"
    for _ in range(cs.MAX_DEPTH + 2):
        inner = f"eval {json.dumps(inner)}"
    assert cs.check(inner, False, {FULL}) == []
    inner = "pkill -f x"
    for _ in range(cs.MAX_DEPTH - 1):
        inner = f"eval {json.dumps(inner)}"
    assert cs.check(inner, False, {FULL}) == [cs.FULL_DENY["pkill"]]


@pytest.mark.parametrize(
    "command",
    ["echo 'unterminated", 'echo "unterminated', "echo $(unterminated", "echo ${x", "`x"],
)
def test_text_bash_would_reject_still_parses(cs, command):
    assert cs.check(command, True, BOTH) == []


# --- known gaps, pinned so a change to them is seen --------------------------------------

# These run pkill -f or an unbounded loop, but the guard does not see it: the name is built
# at run time, or the code is in a file or a pipe. The guards catch an honest agent's slip,
# not a hostile one (docs/configuration.md says so); a change here updates those docs.
KNOWN_GAPS = [
    "P=pkill; $P -f marker",
    "echo 'pkill -f marker' | bash",
    "printf 'pkill -f marker' > s.sh; bash s.sh",
    'bash -c "$CMD"',
]


@pytest.mark.parametrize("command", KNOWN_GAPS)
def test_known_gaps_pass_unseen(cs, command):
    assert cs.check(command, True, BOTH) == []


@pytest.mark.parametrize("command", ["p''kill -f marker", "pk\\ill -f marker"])
def test_known_gap_a_split_name_passes_the_hook_prefilter(command):
    """check() reads `p''kill` as bash does, but the hook's word prefilter never starts it."""
    assert reason(run_guard(bash_payload(command), [FULL])) is None


# --- the hook, as Claude Code and Antigravity run it --------------------------------------


def bash_payload(command: str, background: bool | None = None) -> str:
    tool_input: dict = {"command": command}
    if background is not None:
        tool_input["run_in_background"] = background
    return json.dumps({"tool_name": "Bash", "tool_input": tool_input, "cwd": str(ROOT)})


def run_guard(stdin: str, on) -> subprocess.CompletedProcess:
    return subprocess.run(
        [HOOK_PYTHON, str(GUARDS)],
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
        [HOOK_PYTHON, str(GUARDS)],
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
    assert "phylax git guard error" in proc.stderr


def test_a_call_without_the_words_starts_no_check(monkeypatch):
    """The prefilter: a call that cannot hold a shape exits before command_shapes loads."""
    (gg,) = load_phylax_hooks(monkeypatch, "git_guards")
    assert gg.may_hold_shape('{"tool_input": {"command": "ls"}}', BOTH) is False
    assert gg.may_hold_shape('{"command": "pkill -x a"}', {FULL}) is True
    assert gg.may_hold_shape('{"command": "pgrep -x a"}', {FULL}) is True
    assert gg.may_hold_shape('{"command": "pkill -f a"}', {LOOPS}) is False
    loop = '{"command": "while x", "run_in_background": true}'
    assert gg.may_hold_shape(loop, {LOOPS}) is True
    assert gg.may_hold_shape(loop.replace("while", "until"), {LOOPS}) is True
    assert gg.may_hold_shape(loop, {FULL}) is False
    assert gg.may_hold_shape('{"command": "while x"}', {LOOPS}) is False
    assert gg.may_hold_shape('{"command": "sleep 1", "run_in_background": true}', {LOOPS}) is False
    assert gg.may_hold_shape('{"command": "\\u0070kill"}', {FULL}) is True
