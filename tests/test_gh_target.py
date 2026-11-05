"""phylax's block_gh_implicit_repo guard: a gh post that names no repo is refused when gh
would send it to a repo other than origin's."""

from __future__ import annotations

import json
import os
import pathlib
import random
import re
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor

import pytest
from conftest import HOOK_PYTHON, hook_env, load_phylax_hooks

ROOT = pathlib.Path(__file__).resolve().parent.parent
GUARDS = ROOT / "plugins" / "phylax" / "hooks" / "git_guards.py"
KEY = "block_gh_implicit_repo"
FORK = "https://github.com/me/tool.git"
PARENT = "https://github.com/org/tool.git"


def _git(repo: pathlib.Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def clone(tmp_path: pathlib.Path, remotes: dict[str, str], marks=None, push=None) -> pathlib.Path:
    """A repo with REMOTES (name: url), `gh-resolved` MARKS (name: value) and push URLs PUSH
    (name: url)."""
    repo = tmp_path / "clone"
    repo.mkdir()
    _git(repo, "init", "-q")
    for name, url in remotes.items():
        _git(repo, "remote", "add", name, url)
    for name, value in (marks or {}).items():
        _git(repo, "config", f"remote.{name}.gh-resolved", value)
    for name, url in (push or {}).items():
        _git(repo, "remote", "set-url", "--push", name, url)
    return repo


def refusal(command: str, cwd: pathlib.Path, on=(KEY,), **env: str) -> str | None:
    payload = json.dumps({"cwd": str(cwd), "tool_input": {"command": command}})
    proc = subprocess.run(
        [HOOK_PYTHON, str(GUARDS)],
        input=payload,
        capture_output=True,
        text=True,
        env=hook_env(on, drop=("GH_",), **env),
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout) if proc.stdout.strip() else {}
    spec = out.get("hookSpecificOutput", {})
    if spec.get("permissionDecision") != "deny":
        return None
    return spec["permissionDecisionReason"]


POSTS = [
    "gh pr create -t T -b B",
    "gh pr new -t T -b B",
    "gh pr comment 3 -b B",
    "gh pr review 3 --approve",
    "gh issue create -t T -b B",
    "gh issue new -t T -b B",
    "gh issue comment 3 -b B",
]


@pytest.mark.parametrize("command", POSTS)
def test_a_fork_clone_with_an_upstream_remote_refuses_a_post_with_no_repo(tmp_path, command):
    # gh ranks `upstream` before `origin`, so the post would land on the parent.
    repo = clone(tmp_path, {"origin": FORK, "upstream": PARENT})
    why = refusal(command, repo)
    assert why and "org/tool" in why and "origin's me/tool" in why and "-R me/tool" in why
    assert "remote `upstream` comes first" in why


@pytest.mark.parametrize(
    "command",
    [
        "gh pr create -R me/tool -t T -b B",
        "gh pr create --repo me/tool -t T -b B",
        "gh pr create --repo=me/tool -t T -b B",
        "gh pr create -Rme/tool -t T -b B",
        "gh -R me/tool pr create -t T -b B",
        "GH_REPO=me/tool gh pr create -t T -b B",
        "env GH_REPO=me/tool gh pr create -t T -b B",
        "export GH_REPO=me/tool; gh pr create -t T -b B",
        "gh pr comment https://github.com/org/tool/pull/3 -b B",
        "gh issue comment https://github.com/org/tool/issues/3 -b B",
        "gh pr view 3",
        "gh pr list",
        "gh issue list",
        "gh repo view",
    ],
)
def test_a_named_repo_or_a_read_passes(tmp_path, command):
    repo = clone(tmp_path, {"origin": FORK, "upstream": PARENT})
    assert refusal(command, repo) is None


def test_gh_repo_in_the_environment_names_the_repo(tmp_path):
    repo = clone(tmp_path, {"origin": FORK, "upstream": PARENT})
    assert refusal("gh pr create -t T -b B", repo, GH_REPO="me/tool") is None


def test_an_empty_prefix_assignment_names_nothing(tmp_path):
    repo = clone(tmp_path, {"origin": FORK, "upstream": PARENT})
    assert refusal("GH_REPO= gh pr create -t T -b B", repo)


@pytest.mark.parametrize(
    ("remotes", "marks", "refused"),
    [
        ({"origin": FORK}, {}, False),  # one remote: gh uses it
        ({"origin": FORK, "upstream": PARENT}, {"upstream": "base"}, True),  # gh repo fork --clone
        ({"origin": FORK, "upstream": PARENT}, {"origin": "base"}, False),  # set-default origin
        ({"origin": FORK, "upstream": PARENT}, {"upstream": "me/tool"}, False),
        ({"origin": FORK, "upstream": PARENT}, {"upstream": "ME/Tool"}, False),  # any case
        ({"origin": FORK, "upstream": "https://www.github.com/org/tool"}, {}, True),
        ({"origin": FORK}, {"origin": "org/tool"}, True),  # a default on the parent
        ({"origin": FORK, "github": PARENT}, {}, True),
        ({"origin": PARENT, "fork": FORK}, {}, False),  # a clone of the parent: origin first
        ({"a": FORK, "b": PARENT}, {}, True),  # no origin, no order between them
        ({"a": FORK, "b": "git@github.com:Me/Tool.git"}, {}, False),  # one repo, two spellings
        ({"origin": FORK, "upstream": "https://gitlab.com/org/tool.git"}, {}, False),
        ({"origin": "git@github.com:me/tool.git", "upstream": "ssh://git@github.com/ME/tool"},
         {}, False),
    ],
)  # fmt: skip
def test_the_refusal_follows_the_repo_gh_would_pick(tmp_path, remotes, marks, refused):
    repo = clone(tmp_path, remotes, marks)
    assert bool(refusal("gh pr create -t T -b B", repo)) is refused


def test_a_remote_is_read_by_its_fetch_url(tmp_path):
    # gh names a remote's repo by where it fetches from; a push URL elsewhere does not count.
    repo = clone(tmp_path, {"origin": FORK, "upstream": PARENT}, push={"origin": PARENT})
    assert refusal("gh pr create -t T -b B", repo)


def test_remotes_of_several_repos_with_no_origin_say_so(tmp_path):
    repo = clone(tmp_path, {"a": FORK, "b": PARENT})
    why = refusal("gh pr create -t T -b B", repo)
    assert why and "pick from me/tool, org/tool" in why and "none is gh's default" in why


def test_the_check_follows_cd_into_the_clone(tmp_path):
    repo = clone(tmp_path, {"origin": FORK, "upstream": PARENT})
    assert refusal(f"cd {repo} && gh pr create -t T -b B", tmp_path)


def test_a_folder_outside_any_repo_passes(tmp_path):
    assert refusal("gh pr create -t T -b B", tmp_path) is None


def test_the_guard_off_or_switched_off_in_the_repo_passes(tmp_path):
    repo = clone(tmp_path, {"origin": FORK, "upstream": PARENT})
    assert refusal("gh pr create -t T -b B", repo, on=("block_long_bodies",)) is None
    _git(repo, "config", "phylax.blockGhImplicitRepo", "false")
    assert refusal("gh pr create -t T -b B", repo) is None


# --- against gh itself ------------------------------------------------------------------------

GH = shutil.which("gh")
NAMES = ("upstream", "github", "origin", "fork", "mirror")
REPOS = ("me/tool", "org/tool", "Org/Tool", "other/tool")
FORMS = (
    "https://github.com/{}.git",
    "git@github.com:{}.git",
    "ssh://git@github.com/{}",
    "https://www.github.com/{}",
)
QUERY_RE = re.compile(r'"owner":"([^"]*)","repo":"([^"]*)"')


def gh_base(repo: pathlib.Path, config: str) -> str | None:
    """The repo gh itself resolves in REPO, read from its logged request. A dead proxy and a
    fake token keep it off the network; it is stopped once the request is logged."""
    env = {
        **{k: v for k, v in os.environ.items() if not k.startswith("GH_")},
        "GH_CONFIG_DIR": config,
        "GH_TOKEN": "fake",
        "GH_DEBUG": "api",
        "HTTPS_PROXY": "http://127.0.0.1:9",
        "HTTP_PROXY": "http://127.0.0.1:9",
        "NO_PROXY": "",
    }
    proc = subprocess.Popen(
        [str(GH), "issue", "list", "-L", "1"],
        cwd=repo,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert proc.stderr is not None
        for line in proc.stderr:
            m = QUERY_RE.search(line)
            if m:
                return f"{m.group(1)}/{m.group(2)}"
        return None
    finally:
        proc.kill()
        proc.wait()


@pytest.mark.skipif(GH is None, reason="no gh")
def test_the_target_matches_gh_on_generated_remotes(monkeypatch, tmp_path):
    # Generated remote layouts, URL spellings and set-default marks: the repo the guard says gh
    # would use is the one gh uses, run without a terminal as Claude runs it.
    (git_checks,) = load_phylax_hooks(monkeypatch, "git_checks")

    rng = random.Random(301)
    layouts = []
    for i in range(40):
        names = [n for n in NAMES if rng.random() < 0.5] or ["origin"]
        remotes = {n: rng.choice(FORMS).format(rng.choice(REPOS)) for n in names}
        marks = {}
        if rng.random() < 0.4:
            marks[rng.choice(names)] = rng.choice(("base", *REPOS))
        repo = tmp_path / f"r{i}"
        repo.mkdir()
        _git(repo, "init", "-q")
        for n, url in remotes.items():
            _git(repo, "remote", "add", n, url)
        for n, value in marks.items():
            _git(repo, "config", f"remote.{n}.gh-resolved", value)
        for n in names:
            if rng.random() < 0.2:
                push = rng.choice(FORMS).format(rng.choice(REPOS))
                _git(repo, "remote", "set-url", "--push", n, push)
        target = git_checks.gh_target(repo, {})[0]
        if target is not None:  # a tie among unranked remotes: gh's sort is not stable
            layouts.append((repo, target, remotes, marks))
    with tempfile.TemporaryDirectory() as config, ThreadPoolExecutor(8) as pool:
        seen = list(pool.map(lambda lay: gh_base(lay[0], config), layouts))
    assert all(seen), "gh logged no request"
    wrong = [
        (r, m, t, s)
        for (_, t, r, m), s in zip(layouts, seen, strict=True)
        if t.lower() != (s or "").lower()
    ]
    assert not wrong and len(layouts) >= 30, wrong
