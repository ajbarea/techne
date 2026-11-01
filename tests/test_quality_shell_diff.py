"""quality/run.py's shell reading never misses a network program bash runs, and clears the
data shapes it claims to.

Generated commands run under real bash with every network program replaced by a stub that
logs its name, and git's ssh transport pointed at the ssh stub, so a git remote command that
would connect logs too. Every command whose run logged must be flagged; a command built only
from shapes the reader can show are data (a grep pattern, a local git command, a variable's
value, a script it reads itself) must not be. Anything else may be flagged either way: a
text match counts unless the reader clears it.
"""

from __future__ import annotations

import json
import os
import pathlib
import random
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "quality"))
import run  # ty: ignore[unresolved-import]

pytestmark = pytest.mark.skipif(
    not (shutil.which("bash") and shutil.which("git") and shutil.which("python3")),
    reason="needs bash, git and python3",
)

NET = sorted(run.NET_PROGRAMS)
# Each connects through the ssh stub when it runs; the remote is ssh://h/r.
GIT_REMOTE = ["fetch origin", "pull origin main", "push origin HEAD", "ls-remote origin"]
GIT_LOCAL = ["status -s", "log -1 --oneline", "stash list", "rev-parse HEAD", "branch -a"]
GIT_OPTS = ["", "-C . ", "-c a.b=c ", "--no-pager "]
BENIGN = ["true", "echo hi", "printf %s x", "cat /dev/null", "ls >/dev/null"]
# Words that name a network program without running it, in shapes the reader clears.
DATA = [
    "grep -q 'curl x' /dev/null || true",
    'grep -c "git push" /dev/null; true',
    "A='ssh -x' true",
    "git log -1 --grep 'push origin' --oneline",
    "command -v curl >/dev/null",
    "printf '%s' 'gh wget' >/dev/null",
]
# The same, in shapes it may flag: printed text could be run by what reads it.
DECOYS = ["echo curl", "echo 'ssh -x'", "printf '%s' 'git push'", "echo gh wget"]
WRAPPERS = ["", "env A=1 ", "timeout 5 ", "nice -n 1 ", "command ", "nohup ", "stdbuf -o0 "]
WRAPPERS += ["E=; $E "]  # an unquoted expansion to nothing is no word


def spell(name: str, rng: random.Random) -> str:
    """NAME as bash would still run it: plain, quoted, or split by quotes and escapes."""
    i = rng.randrange(1, len(name)) if len(name) > 1 else 1
    return rng.choice(
        [name, f'"{name}"', f"'{name}'", f'{name[:i]}""{name[i:]}', f"{name[:i]}\\{name[i:]}"]
    )


def simple(rng: random.Random) -> tuple[str, bool]:
    """One command, and whether the reader must clear it."""
    kind = rng.randrange(6)
    wrap = rng.choice(WRAPPERS)
    if kind == 0:
        return f"{wrap}{spell(rng.choice(NET), rng)} x", False
    if kind == 1:
        return f"{wrap}{spell('git', rng)} {rng.choice(GIT_OPTS)}{rng.choice(GIT_REMOTE)}", False
    if kind == 2:
        return f"{wrap}git {rng.choice(GIT_OPTS)}{rng.choice(GIT_LOCAL)}", True
    if kind == 3:
        return rng.choice(DATA), True
    if kind == 4:
        return rng.choice(DECOYS), False
    return f"{wrap}{rng.choice(BENIGN)}", True


def nest(cmd: str, rng: random.Random) -> tuple[str, bool]:
    """CMD run another way bash still runs it, and whether that way keeps it clearable."""
    q = cmd.replace("'", "'\\''")
    forms = [
        (cmd, True),
        (f"bash -c '{q}'", True),
        (f"bash -lc '{q}'", True),
        (f"bash -euc '{q}'", True),
        (f"sh <<'EOF'\n{cmd}\nEOF", True),
        (f"bash <<< '{q}'", True),
        (f"eval '{q}'", True),
        (f"( {cmd} )", True),
        (f"{{ {cmd}; }}", True),
        (f"find . -maxdepth 0 -exec sh -c '{q}' \\;", True),
        (f"python3 - <<'PY'\nimport os\nos.system({cmd!r})\nPY", True),
        (f"false || {cmd}", True),
        (f"if true; then\n{cmd}\nfi", True),
        (f"for i in 1; do\n{cmd}\ndone", True),
        (f"case x in x)\n{cmd}\n;; esac", True),
        (f"echo $({cmd}) >/dev/null", False),
        (f"echo '{q}' | bash", False),
        (f"cat <<'EOF' | sh\n{cmd}\nEOF", False),
    ]
    if ";" not in cmd:  # `true | a; b` pipes only a: b never sees a's assignments
        forms.append((f"true | {cmd}", True))
    if not any(s in cmd for s in ("<<", "|", ";")) and not cmd.startswith(("A=", "command ")):
        forms.append((f"echo y | xargs {cmd}", True))
    if "<<" not in cmd:  # tree-sitter reads this as `(true && cmd 2>&1) | cat`
        forms.append((f"true && {cmd} 2>&1 | cat", True))
    return rng.choice(forms)


def generate(rng: random.Random) -> tuple[str, bool]:
    """A command line, and whether the reader must clear all of it."""
    parts = [simple(rng) for _ in range(rng.randint(1, 3))]
    nested = [nest(c, rng) for c, _ in parts]
    cmds = [c for c, _ in nested]
    # A heredoc ends only on a line holding its word alone.
    sep = "\n" if any("<<" in c for c in cmds) else rng.choice(["; ", " && ", "\n"])
    clear = all(ok for _, ok in parts) and all(ok for _, ok in nested)
    return sep.join(cmds), clear


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    root = tmp_path_factory.mktemp("box")
    stubs = root / "stubs"
    stubs.mkdir()
    for name in NET:
        stub = stubs / name
        stub.write_text(f'#!/bin/sh\necho {name} >> "$NETLOG"\nexit 1\n')
        stub.chmod(0o755)
    home = root / "home"
    home.mkdir()
    repo = root / "repo"
    env = {
        "PATH": f"{stubs}:{os.environ['PATH']}",
        "HOME": str(home),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_SSH_COMMAND": str(stubs / "ssh"),
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
        "NETLOG": str(root / "net.log"),
    }
    for args in (
        ["init", "-q", "-b", "main", str(repo)],
        ["-C", str(repo), "commit", "-q", "--allow-empty", "-m", "i"],
        ["-C", str(repo), "remote", "add", "origin", "ssh://h/r"],
    ):
        subprocess.run(["git", *args], env=env, check=True)
    return repo, env, root / "net.log"


def ran_network(cmd: str, box) -> bool:
    repo, env, log = box
    log.unlink(missing_ok=True)
    subprocess.run(
        ["bash", "-c", cmd],
        cwd=repo,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=30,
    )
    return log.exists() and log.read_text().strip() != ""


@pytest.mark.parametrize("seed", range(8))
def test_the_leak_check_never_misses_what_bash_runs(box, seed):
    rng = random.Random(seed)
    ws = run.LIVE / "run" / "ws"
    wrong = []
    for _ in range(60):
        cmd, clear = generate(rng)
        real = ran_network(cmd, box)
        flagged, _ = run.shell_reach(cmd, str(ws), ws)
        if real and flagged != "ran":
            wrong.append(f"bash ran a network program, check said {flagged!r}: {cmd!r}")
        if clear and flagged:
            wrong.append(f"flagged data the reader should clear: {cmd!r}")
    assert not wrong, "\n".join(wrong)


def test_the_generator_reaches_every_answer(box):
    rng = random.Random(0)
    seen = set()
    for _ in range(80):
        cmd, clear = generate(rng)
        seen.add((ran_network(cmd, box), clear))
    assert {(True, False), (False, True), (False, False)} <= seen


def test_the_leak_check_never_calls_ran_what_bash_did_not_run(box):
    rng = random.Random(99)
    ws = run.LIVE / "run" / "ws"
    wrong = []
    for _ in range(200):
        cmd, _clear = generate(rng)
        flagged, _ = run.shell_reach(cmd, str(ws), ws)
        if flagged == "ran" and not ran_network(cmd, box):
            wrong.append(f"check said 'ran', bash ran no network program: {cmd!r}")
    assert not wrong, "\n".join(wrong)


# Where paths land. A probe program logs its folder and where each argument lands, and a
# DEBUG trap (inherited by functions, subshells and every bash started) logs the shell's
# folder before each command; the check must say "ran" exactly when one of them is in a
# registered folder outside the workspace (the test's workspace sits under /tmp, which is
# one). A move is followed by `:`, so the folder it enters is logged.
DIRS = ["/", "/usr", "/usr/lib", "..", "../..", "{ws}", "{ws}/sub/deep", "~"]
LANDS = ["x", "..", "../x", "../../x", "sub/x", "~/x", "/usr/x", "/tmp/zz", "~root/x"]
LANDS += ["//tmp/zz", "/t?p", "/{tmp,usr}/zz", "/u?r/x", "s*"]  # globs match what exists
MOVES = [
    "cd {d}",
    "builtin cd {d}",
    "pushd {d} >/dev/null",
    "pushd {d} >/dev/null && popd >/dev/null",
    "cd {d} && cd - >/dev/null",
    "eval 'cd {d}'",
    "f() {{ cd {d}; }}; f",
]


def folder_step(rng: random.Random, ws: str) -> str:
    d = rng.choice(DIRS).format(ws=ws)
    p = rng.choice(LANDS)
    kind = rng.randrange(4)
    if kind == 0:
        return f"probe {p}"
    if kind == 1:
        return f"env -C {d} probe {p}"
    return rng.choice(MOVES).format(d=d) + "; :"


def folder_group(rng: random.Random, ws: str, depth: int = 0, step=folder_step) -> str:
    steps = [
        folder_group(rng, ws, depth + 1, step)
        if depth < 2 and rng.random() < 0.3
        else step(rng, ws)
        for _ in range(rng.randint(1, 4))
    ]
    body = "; ".join(steps)
    q = body.replace("'", "'\\''")
    return rng.choice(
        [
            body,
            f"( {body} )",
            f"{{ {body}; }}",
            f"bash -c '{q}'",
            f"echo $( {body} ) >/dev/null",
            f"true | ( {body} )",
            f"g() {{ {body}; }}; g",
        ]
    )


@pytest.fixture(scope="module")
def folders(box):
    repo, env, _log = box
    (repo / "sub" / "deep").mkdir(parents=True, exist_ok=True)
    probe = repo.parent / "stubs" / "probe"
    probe.write_text(
        "#!/usr/bin/env python3\nimport os, sys\n"
        "with open(os.environ['PROBELOG'], 'a') as f:\n"
        "    f.write(os.getcwd() + '\\n')\n"
        "    for a in sys.argv[1:]:\n"
        "        f.write(os.path.normpath(os.path.join(os.getcwd(), a)) + '\\n')\n"
    )
    probe.chmod(0o755)
    trap = repo.parent / "trap.sh"
    trap.write_text('set -T\ntrap \'printf "%s\\n" "$PWD" >> "$PROBELOG"\' DEBUG\n')
    home = repo.parent / "home"
    probe_log = str(repo.parent / "probe.log")
    return repo, {**env, "PROBELOG": probe_log, "HOME": str(home), "BASH_ENV": str(trap)}


def landed_outside(cmd: str, folders) -> list[str]:
    repo, env = folders
    log = pathlib.Path(env["PROBELOG"])
    log.unlink(missing_ok=True)
    subprocess.run(
        ["bash", "-c", cmd],
        cwd=repo,
        env={k: v for k, v in env.items() if k != "OLDPWD"},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=30,
    )
    landed = log.read_text().split() if log.exists() else []
    return [p for p in landed if run.restricted(p, repo)]


@pytest.mark.parametrize("seed", range(6))
def test_the_leak_check_follows_the_folder_as_bash_does(folders, seed):
    repo, _env = folders
    rng = random.Random(1000 + seed)
    wrong = []
    for _ in range(50):
        cmd = folder_group(rng, str(repo))
        real = landed_outside(cmd, folders)
        flagged, _ = run.shell_reach(cmd, str(repo), repo)
        if real and flagged != "ran":
            wrong.append(f"bash used {real[0]}, check said {flagged!r}: {cmd!r}")
        if flagged == "ran" and not real:
            wrong.append(f"check said 'ran', bash used no registered folder: {cmd!r}")
    assert not wrong, "\n".join(wrong)


# Moves that may not happen: a branch, a command after `||`, a loop, a background job, a
# pipe. The check may not know the folder after one; with the folder unknown only the
# registered climb of two `../` counts, so the steps here never climb one level, and the
# check must say "ran" whenever bash used a registered folder (the other way it may be
# stricter than bash).
MAYBE = [
    "cd {d} || cd ..",
    "cd nope 2>/dev/null || cd {d}",
    "false || cd {d}",
    "true || cd {d}",
    "cd {d} && true 2>&1 | cat",
    "true && cd {d} 2>&1 | cat",
    "if true; then cd {d}; fi",
    "if false; then cd {d}; else cd sub; fi",
    "for i in 1 2; do cd {d}; done",
    "while false; do cd {d}; done",
    "case x in x) cd {d};; esac",
    "cd {d} & wait",
]
MAYBE_DIRS = ["/", "/usr", "{ws}", "{ws}/sub", "{ws}/sub/deep", "~"]


def maybe_step(rng: random.Random, ws: str) -> str:
    d = rng.choice(MAYBE_DIRS).format(ws=ws)
    p = rng.choice([x for x in LANDS if x not in ("..", "../x")])
    if rng.randrange(3) == 0:
        return f"probe {p}"
    return rng.choice(MAYBE).format(d=d) + "; :"


@pytest.mark.parametrize("seed", range(4))
def test_a_move_that_may_not_happen_never_hides_a_landing(folders, seed):
    repo, _env = folders
    rng = random.Random(2000 + seed)
    wrong = []
    for _ in range(50):
        cmd = folder_group(rng, str(repo), step=maybe_step)
        real = landed_outside(cmd, folders)
        flagged, _ = run.shell_reach(cmd, str(repo), repo)
        if real and flagged != "ran":
            wrong.append(f"bash used {real[0]}, check said {flagged!r}: {cmd!r}")
    assert not wrong, "\n".join(wrong)


def test_the_folder_generator_reaches_both_answers(folders):
    repo, _env = folders
    rng = random.Random(1000)
    seen = {bool(landed_outside(folder_group(rng, str(repo)), folders)) for _ in range(60)}
    assert seen == {True, False}


# A script written in one call and run in a later one: the write must keep its text match.
WRITES = [
    ("cat > s.sh <<'EOF'\n{c}\nEOF", "bash s.sh"),
    ("echo '{q}' > s.sh", "sh s.sh"),
    ("printf '%s\\n' '{q}' | tee s.sh >/dev/null", ". ./s.sh"),
    ("git config alias.zz '!{q}'", "git zz"),
    ("cat > Makefile <<'MK'\nall:\n\t@{c}\nMK", "make -s"),
    ("cat > s.py <<'EOF'\nimport os\nos.system({p!r})\nEOF", "python3 s.py"),
]


def test_a_script_written_now_and_run_later_keeps_its_flag(box, tmp_path):
    repo, _env, _log = box
    rng = random.Random(7)
    wrong = []
    for _ in range(40):
        write, later = rng.choice(WRITES)
        if later.startswith("make") and not shutil.which("make"):
            continue
        c = f"{spell(rng.choice(NET), rng)} x"
        first = write.format(c=c, q=c.replace("'", "'\\''"), p=c)
        ran_network(first, box)
        if not ran_network(later, box):
            continue
        calls = [{"command": first}, {"command": later}]
        log = tmp_path / "t.jsonl"
        log.write_text(
            "\n".join(
                json.dumps(
                    {"message": {"content": [{"type": "tool_use", "name": "Bash", "input": inp}]}}
                )
                for inp in calls
            )
        )
        if not run.leaks(log, repo):
            wrong.append(f"no flag on a script run later: {first!r} then {later!r}")
    assert not wrong, "\n".join(wrong)
