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
        (f"true | {cmd}", True),
        (f"find . -maxdepth 0 -exec sh -c '{q}' \\;", True),
        (f"python3 - <<'PY'\nimport os\nos.system({cmd!r})\nPY", True),
        (f"echo $({cmd}) >/dev/null", False),
        (f"echo '{q}' | bash", False),
        (f"cat <<'EOF' | sh\n{cmd}\nEOF", False),
    ]
    if "<<" not in cmd and "|" not in cmd and ";" not in cmd and not cmd.startswith("A="):
        forms.append((f"echo y | xargs {cmd}", True))
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
