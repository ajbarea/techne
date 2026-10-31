"""quality/run.py's shell reading agrees with bash on which network programs a command runs.

Generated commands run under real bash with every network program replaced by a stub that
logs its name, and git's ssh transport pointed at the ssh stub, so a git remote command that
would connect logs too. The leak check must flag exactly the commands whose run logged.
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
    not (shutil.which("bash") and shutil.which("git")), reason="needs bash and git"
)

NET = sorted(run.NET_PROGRAMS)
# Each connects through the ssh stub when it runs; the remote is ssh://h/r.
GIT_REMOTE = ["fetch origin", "pull origin main", "push origin HEAD", "ls-remote origin"]
GIT_LOCAL = ["status -s", "log -1 --oneline", "stash list", "rev-parse HEAD", "branch -a"]
GIT_OPTS = ["", "-C . ", "-c a.b=c ", "--no-pager "]
BENIGN = ["true", "echo hi", "printf %s x", "cat /dev/null", "ls >/dev/null"]
# Words that name a network program without running it.
DECOYS = ["echo curl", "echo 'ssh -x'", "printf '%s' 'git push'", "echo gh wget"]
WRAPPERS = ["", "env A=1 ", "timeout 5 ", "nice -n 1 ", "command ", "nohup ", "stdbuf -o0 "]


def spell(name: str, rng: random.Random) -> str:
    """NAME as bash would still run it: plain, quoted, or split by quotes and escapes."""
    i = rng.randrange(1, len(name)) if len(name) > 1 else 1
    return rng.choice(
        [name, f'"{name}"', f"'{name}'", f'{name[:i]}""{name[i:]}', f"{name[:i]}\\{name[i:]}"]
    )


def simple(rng: random.Random) -> tuple[str, bool]:
    """One command and whether it runs a network program."""
    kind = rng.randrange(5)
    wrap = rng.choice(WRAPPERS)
    if kind == 0:
        return f"{wrap}{spell(rng.choice(NET), rng)} x", True
    if kind == 1:
        return f"{wrap}{spell('git', rng)} {rng.choice(GIT_OPTS)}{rng.choice(GIT_REMOTE)}", True
    if kind == 2:
        return f"{wrap}git {rng.choice(GIT_OPTS)}{rng.choice(GIT_LOCAL)}", False
    if kind == 3:
        return rng.choice(DECOYS), False
    return f"{wrap}{rng.choice(BENIGN)}", False


def nest(cmd: str, rng: random.Random) -> str:
    """CMD run another way bash still runs it."""
    q = cmd.replace("'", "'\\''")
    return rng.choice(
        [
            cmd,
            f"bash -c '{q}'",
            f"sh <<'EOF'\n{cmd}\nEOF",
            f"echo $({cmd}) >/dev/null",
            f"eval '{q}'",
            f"( {cmd} )",
            f"{{ {cmd}; }}",
            f"true | {cmd}",
        ]
    )


def generate(rng: random.Random) -> tuple[str, bool]:
    parts = [simple(rng) for _ in range(rng.randint(1, 3))]
    cmds = [nest(c, rng) for c, _ in parts]
    # A heredoc ends only on a line holding its word alone.
    sep = "\n" if any("<<" in c for c in cmds) else rng.choice(["; ", " && ", "\n"])
    return sep.join(cmds), any(net for _, net in parts)


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


@pytest.mark.parametrize("seed", range(6))
def test_the_leak_check_agrees_with_bash(box, seed):
    rng = random.Random(seed)
    ws = run.LIVE / "run" / "ws"
    wrong = []
    for _ in range(60):
        cmd, _expected = generate(rng)
        real = ran_network(cmd, box)
        flagged, _ = run.shell_reach(cmd, str(ws), ws)
        if real != flagged:
            wrong.append(f"bash ran network={real}, check={flagged}: {cmd!r}")
    assert not wrong, "\n".join(wrong)


def test_the_generator_reaches_both_answers(box):
    rng = random.Random(0)
    seen = {ran_network(generate(rng)[0], box) for _ in range(40)}
    assert seen == {True, False}
