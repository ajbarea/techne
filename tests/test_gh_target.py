"""phylax's block_gh_implicit_repo guard: a gh post that names no repo is refused unless every
remote of the clone names one repo."""

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
    "gh pr close 3 --comment B",
    "gh issue close 3 -c B",
    "gh pr reopen 3 -c B",
    "gh pr edit 3 --add-label x",
    "gh pr merge 3 --squash",
    "gh issue edit 3 --add-label x",
    "gh label create x",
    "gh release create v1",
    "gh workflow run ci.yml",
    "gh run rerun 9",
    "gh variable set X --body y",
    "gh repo edit --description x",
    "gh repo delete --yes",
    "gh api repos/{owner}/{repo}/issues/3/comments -f body=hi",
    "gh api -X PATCH repos/:owner/:repo/pulls/3 -f title=t",
    # an argument that only looks like a named repo
    'gh pr comment 3 -b "https://github.com/org/other/pull/9 is related"',
    'gh pr comment 3 -b "-Rather not"',
    "gh pr comment 3 -b https://github.com/org/other/pull/9",
    'gh pr create -R "$UNSET_REPO" -t T -b B',
    'gh pr create -R "" -t T -b B',
    "GH_REPO=me/tool; gh pr create -t T -b B",  # set, never exported: gh does not see it
    "(export GH_REPO=me/tool); gh pr create -t T -b B",
    "export GH_REPO=me/tool; GH_REPO=; gh pr create -t T -b B",  # still exported, now empty
    "export GH_REPO=me/tool; unset GH_REPO; gh pr create -t T -b B",
    'gh pr comment 3 -b "-R me/tool"',
    'gh pr comment 3 -b "--repo=me/tool"',
    'gh pr create -R me/tool -R "" -t T -b B',  # gh takes the last
    "gh pr create -R $FORK -t T -b B",  # unset
    "gh secret set FOO --body x",
    "gh secret delete FOO",
    "gh discussion create -t T -b B",  # a group this gh may not have is checked too
    "gh some-extension do-something",
    "gh project link 1",  # links a project to the resolved repo
    "gh project unlink 1",
    "gh label create bug -d -Rme/tool",  # -Rme/tool is the description
    "gh release create v1 --notes -Rme/tool",
    "gh pr close 3 -c -Rme/tool",  # -Rme/tool is the closing comment
    "gh prc -t T -b B",  # one word: an alias for any subcommand
    "gh api -X GET -X DELETE repos/{owner}/{repo}/labels/x",  # gh takes the last -X
    "gh pr $ACTION 3 -c -Rme/tool",  # with ACTION=close, -Rme/tool is the comment
    "gh prc -c -Rme/tool",
    "gh repo rename new-name",
    "gh repo archive --yes",
    "gh repo deploy-key add key.pub",
    "gh repo autolink create JIRA- https://example.com/<num>",
    "gh api -X DELETE repos/{owner}/{repo}/labels/x",
    "gh api --method=DELETE repos/{owner}/{repo}/labels/x",
    "gh api -XPOST repos/{owner}/{repo}/issues",
    "gh api repos/{owner}/{repo}/issues -F title=x",
    "gh api repos/{owner}/{repo}/issues --input issue.json",
]


@pytest.mark.parametrize("command", POSTS)
def test_a_fork_clone_with_an_upstream_remote_refuses_a_post_with_no_repo(tmp_path, command):
    # gh ranks `upstream` before `origin`, so the post would land on the parent.
    repo = clone(tmp_path, {"origin": FORK, "upstream": PARENT})
    why = refusal(command, repo)
    assert why and "name github.com/me/tool, github.com/org/tool" in why
    assert "add `-R github.com/me/tool`" in why


def test_a_subcommand_this_check_cannot_know_is_refused(tmp_path):
    repo = clone(tmp_path, {"origin": FORK, "upstream": PARENT})
    assert refusal("gh $GROUP create -t T -b B", repo)


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
        "GH_REPO=me/tool; export GH_REPO; gh pr create -t T -b B",
        "gh repo edit me/tool --description x",
        "gh repo edit https://github.com/me/tool --description x",
        "gh pr create -R https://github.com/me/tool -t T -b B",
        'gh pr create -R "" -R me/tool -t T -b B',
        "FORK=me/tool; gh pr create -R $FORK -t T -b B",
        "gh pr $ACTION 3 -R me/tool",
        "gh pr comment https://github.com/org/tool/pull/3/files -b B",
        # a value with a space is never an option, though its option is not in any table
        'gh workflow run ci.yml -R me/tool -f "-R x y"',
        "gh project list",
        "gh project link 1 -R me/tool",
        "gh issue create -R=me/tool -t T -b B",  # pflag drops the = of a joined shorthand
        "gh pr merge 3 -m -R me/tool",  # -m is --merge here, not a value
        "gh pr review 3 -c -R me/tool -b B",  # -c is --comment here, not a value
        "gh pr create --help",
        "gh pr create -h",
        "gh pr help create",
        "gh issue develop 3 --list",
        "gh secret list",
        "gh secret set FOO --org acme --body x",
        "gh variable set X --user --body y",
        "gh repo deploy-key list",
        "gh repo autolink list",
        "gh ruleset list",
        "gh auth status",
        "gh search repos tool",
        "gh pr comment https://github.com/org/tool/pull/3 -b B",
        "gh issue comment https://github.com/org/tool/issues/3 -b B",
        "gh pr view 3",
        "gh pr list",
        "gh issue list",
        "gh repo view",
        "gh run list",
        "gh release download v1",
        "gh api repos/{owner}/{repo}/issues",  # a read
        "gh api -X GET repos/{owner}/{repo}/issues -f state=open",
        "gh api repos/me/tool/issues/3/comments -f body=hi",  # names its repo
    ],
)
def test_a_named_repo_or_a_read_passes(tmp_path, command):
    repo = clone(tmp_path, {"origin": FORK, "upstream": PARENT})
    assert refusal(command, repo) is None


def test_gh_repo_in_the_environment_names_the_repo(tmp_path):
    repo = clone(tmp_path, {"origin": FORK, "upstream": PARENT})
    assert refusal("gh pr create -t T -b B", repo, GH_REPO="me/tool") is None
    # bash passes a changed or removed exported variable on as changed
    assert refusal("unset GH_REPO; gh pr create -t T -b B", repo, GH_REPO="me/tool")
    assert refusal("GH_REPO=; gh pr create -t T -b B", repo, GH_REPO="me/tool")


def test_a_subcommand_given_as_a_variable_passes_in_a_clone_of_one_repo(tmp_path):
    repo = clone(tmp_path, {"origin": FORK})
    assert refusal('gh pr "$SUB" 3', repo) is None


def test_an_empty_prefix_assignment_names_nothing(tmp_path):
    repo = clone(tmp_path, {"origin": FORK, "upstream": PARENT})
    assert refusal("GH_REPO= gh pr create -t T -b B", repo)


@pytest.mark.parametrize(
    ("remotes", "marks", "refused"),
    [
        ({"origin": FORK}, {}, False),  # one remote: gh uses it
        ({"origin": FORK}, {"origin": "base"}, False),
        ({"origin": FORK}, {"origin": "ME/Tool"}, False),  # a default naming its own repo
        ({"origin": FORK}, {"origin": "org/tool"}, True),  # a default on the parent
        ({"origin": FORK}, {"origin": "not-a-repo"}, True),
        ({"origin": FORK, "upstream": PARENT}, {"upstream": "base"}, True),  # gh repo fork --clone
        # gh secret, variable and project ignore a default, so it never settles two repos
        ({"origin": FORK, "upstream": PARENT}, {"origin": "base"}, True),
        ({"origin": FORK, "upstream": PARENT}, {"upstream": "me/tool"}, True),
        ({"origin": PARENT, "fork": FORK}, {}, True),  # a clone of the parent with a fork remote
        ({"Origin": PARENT, "fork": FORK}, {}, True),
        ({"a": FORK, "b": PARENT}, {}, True),
        ({"a": FORK, "b": "git@github.com:Me/Tool.git"}, {}, False),  # one repo, two spellings
        ({"origin": FORK, "github": "https://www.github.com/me/tool"}, {}, False),
        ({"origin": "git@github.com:me/tool.git", "upstream": "ssh://git@github.com/ME/tool"},
         {}, False),
        # gh skips a local path or file:// remote
        ({"origin": FORK, "backup": "/srv/b.git"}, {}, False),
        ({"origin": FORK, "backup": "file:///srv/b.git"}, {}, False),
        # a URL with a host but no OWNER/NAME, or one this check does not parse, could be any
        ({"origin": FORK, "odd": "https://github.com/x/me/tool.git"}, {}, True),
        ({"origin": "https://github.com/x/me/tool.git", "zzz": PARENT}, {}, True),
        ({"origin": "https://gitlab.com/me/tool.git", "zzz": "git@github.com://org/tool"},
         {}, True),
        ({"origin": "https://gitlab.com/grp/sub/tool.git"}, {}, False),  # its only remote
        # one OWNER/NAME on two hosts is two repos
        ({"origin": "https://ghe.corp.example/org/tool.git", "upstream": PARENT}, {}, True),
        ({"origin": "https://ghe.corp.example/me/tool.git"}, {"origin": "me/tool"}, False),
        # gh resolves an ssh host through ssh config, an https one as written
        ({"origin": "https://corp/me/tool.git", "zzz": "git@corp:me/tool.git"}, {}, True),
        ({"origin": "git@gh-me:me/tool.git", "upstream": "git@gh-me:org/tool.git"}, {}, True),
        ({"origin": FORK, "upstream": PARENT}, {"upstream": "not-a-repo"}, True),
    ],
)  # fmt: skip
def test_the_guard_passes_only_a_clone_of_one_repo(tmp_path, remotes, marks, refused):
    repo = clone(tmp_path, remotes, marks)
    assert bool(refusal("gh pr create -t T -b B", repo)) is refused


def test_a_remote_is_read_by_its_fetch_url(tmp_path):
    # gh names a remote's repo by where it fetches from; a push URL elsewhere does not count.
    repo = clone(tmp_path, {"origin": FORK}, push={"origin": PARENT})
    assert refusal("gh pr create -t T -b B", repo) is None


@pytest.mark.parametrize("fetch", ["/srv/mirror.git", "file:///srv/m.git"])
def test_a_local_fetch_url_falls_back_to_the_push_url(tmp_path, fetch):
    repo = clone(tmp_path, {"origin": fetch, "upstream": PARENT}, push={"origin": FORK})
    why = refusal("gh pr create -t T -b B", repo)
    assert why and "github.com/me/tool, github.com/org/tool" in why


def test_the_refusal_names_the_host_and_never_offers_a_default(tmp_path):
    # gh reads a bare OWNER/NAME on its default host, and some commands ignore a default
    repo = clone(tmp_path, {"origin": "https://ghe.corp.example/me/tool.git", "public": PARENT})
    why = refusal("gh pr create -t T -b B", repo)
    assert why and "add `-R ghe.corp.example/me/tool`" in why and "set-default me" not in why
    (tmp_path / "alias").mkdir()
    alias = clone(tmp_path / "alias", {"origin": "git@gh-me:me/tool.git", "upstream": PARENT})
    assert "add `-R me/tool`" in (refusal("gh pr create -t T -b B", alias) or "")


def test_remotes_of_several_repos_with_no_origin_say_so(tmp_path):
    repo = clone(tmp_path, {"a": FORK, "b": "https://github.com/x/y/z.git"})
    why = refusal("gh pr create -t T -b B", repo)
    assert why and "remote `b` (a URL it cannot read)" in why
    assert "add `-R HOST/OWNER/NAME`" in why


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
NAMES = ("upstream", "github", "origin", "fork", "mirror")  # each drawn in one of three cases
REPOS = ("me/tool", "org/tool", "Org/Tool", "other/tool")
FORMS = (
    "https://github.com/{}.git",
    "git@github.com:{}.git",
    "ssh://git@github.com/{}",
    "https://www.github.com/{}",
)
# What gh logs for the repo it resolved: GraphQL variables (gh issue list, which reads a
# `gh repo set-default` mark) or a REST path (gh variable list, which does not).
QUERIES = {
    ("issue", "list", "-L", "1"): re.compile(r'"owner":"([^"]*)","repo":"([^"]*)"'),
    ("variable", "list"): re.compile(r"Request to https://\S+?/repos/([^/]+)/([^/?]+)/actions/"),
}


def gh_base(repo: pathlib.Path, config: str, args: tuple[str, ...]) -> str | None:
    """The repo gh itself resolves in REPO for ARGS, read from its logged request. A dead proxy
    and a fake token keep it off the network; it is stopped once the request is logged."""
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
        [str(GH), *args],
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
            m = QUERIES[args].search(line)
            if m:
                return f"{m.group(1)}/{m.group(2)}"
        return None
    finally:
        proc.kill()
        proc.wait()


@pytest.mark.skipif(GH is None, reason="no gh")
def test_whenever_the_guard_passes_gh_acts_on_that_repo(monkeypatch, tmp_path):
    # Generated remote layouts, URL spellings, local remotes and set-default marks: whenever
    # the guard lets a command that names no repo through, gh, run without a terminal as
    # Claude runs it, acts on the one repo the guard found, through both of its resolvers.
    (git_checks,) = load_phylax_hooks(monkeypatch, "git_checks")

    rng = random.Random(301)
    passed, refused = [], 0
    for i in range(60):
        names = [n for n in NAMES if rng.random() < 0.5] or ["origin"]
        names = [rng.choice((n, n.capitalize(), n.upper())) for n in names]
        pool = REPOS[:1] if i % 2 else REPOS  # half the layouts are clones of one repo
        remotes: dict[str, str] = {n: rng.choice(FORMS).format(rng.choice(pool)) for n in names}
        local = {n for n in names if rng.random() < 0.15}  # fetches from a path
        for n in local:
            remotes[n] = f"/srv/{n}.git"
        marks = {}
        if rng.random() < 0.4:
            marks[rng.choice(names)] = rng.choice(("base", *pool))
        repo = tmp_path / f"r{i}"
        repo.mkdir()
        _git(repo, "init", "-q")
        for n, url in remotes.items():
            _git(repo, "remote", "add", n, url)
        for n, value in marks.items():
            _git(repo, "config", f"remote.{n}.gh-resolved", value)
        for n in names:
            if n in local or rng.random() < 0.2:
                push = rng.choice(FORMS).format(rng.choice(pool))
                _git(repo, "remote", "set-url", "--push", n, push)
        found = git_checks.implicit_repo(repo)[0]
        if found:
            passed.append((repo, found.partition("/")[2], remotes, marks))
        else:
            refused += found is None
    with tempfile.TemporaryDirectory() as config, ThreadPoolExecutor(8) as pool:
        seen = {
            args: list(pool.map(lambda lay, a=args: gh_base(lay[0], config, a), passed))
            for args in QUERIES
        }
    wrong = [
        (r, m, want, args, s)
        for args, got in seen.items()
        for (_, want, r, m), s in zip(passed, got, strict=True)
        if (s or "").lower() != want
    ]
    assert not wrong and len(passed) >= 15 and refused >= 15, (len(passed), refused, wrong)


# --- the parsers, case by case ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "repo"),
    [
        ("ssh://git@gitlab.example/o/r", "ssh:gitlab.example/o/r"),
        ("SSH://git@gitlab.example/o/r", "ssh:gitlab.example/o/r"),
        ("ssh://git@gitlab.example:22/o/r", "ssh:gitlab.example/o/r"),
        ("git+ssh://git@h.example/o/r", "ssh:h.example/o/r"),
        ("ssh+git://h.example/o/r", "ssh:h.example/o/r"),
        ("https://h.example/o/r", "h.example/o/r"),
        ("ssh://git@ssh.github.com:443/o/r", "github.com/o/r"),
        ("https://github.com/Xavier/toolX", "github.com/xavier/toolx"),
        ("https://github.com//o/r/", "github.com/o/r"),
        ("not a url", ""),
        ("https://github.com/o", ""),
        ("/srv/mirror.git", None),
    ],
)
def test_a_remote_url_reads_as_its_repo(monkeypatch, url, repo):
    (git_checks,) = load_phylax_hooks(monkeypatch, "git_checks")
    assert git_checks.remote_repo(url) == repo


@pytest.mark.parametrize(
    ("args", "parsed"),
    [
        (["-XPOST", "repos/o/r"], ("repos/o/r", [("-X", "POST")])),
        (["-fa", "repos/o/r"], ("repos/o/r", [("-f", "a")])),
        (["--method=POST", "repos/o/r"], ("repos/o/r", [("--method", "POST")])),
        (["-X", "POST", "repos/o/r"], ("repos/o/r", [("-X", "POST")])),
        (["repos/o/r", "-X"], ("repos/o/r", [("-X", "")])),
        (["repos/o/r", "--paginate"], ("repos/o/r", [])),
        (["repos/a/b", "repos/c/d"], ("repos/a/b", [])),
        (["--paginate", "repos/o/r"], ("repos/o/r", [])),
    ],
)
def test_gh_api_reads_its_endpoint_and_value_options(monkeypatch, args, parsed):
    (git_checks,) = load_phylax_hooks(monkeypatch, "git_checks")
    assert git_checks.parse_gh_api(args) == parsed


def test_a_clone_with_no_remote_leaves_gh_to_stop_on_its_own(monkeypatch, tmp_path):
    (git_checks,) = load_phylax_hooks(monkeypatch, "git_checks")
    assert git_checks.implicit_repo(clone(tmp_path, {})) == ("", "", "")


def test_a_remote_url_with_a_space_is_read_whole(monkeypatch, tmp_path):
    (git_checks,) = load_phylax_hooks(monkeypatch, "git_checks")
    repo = clone(tmp_path, {"origin": "https://github.com/me/my tool.git"})
    assert git_checks.implicit_repo(repo) == ("github.com/me/my tool", "", "github.com/me/my tool")


def test_a_remote_url_with_a_tab_is_read_whole(monkeypatch, tmp_path):
    (git_checks,) = load_phylax_hooks(monkeypatch, "git_checks")
    repo = clone(tmp_path, {"origin": "https://github.com/me/my\ttool.git"})
    assert git_checks.implicit_repo(repo) == (
        "github.com/me/my\ttool",
        "",
        "github.com/me/my\ttool",
    )


def test_a_local_fetch_url_with_an_unreadable_push_url_still_counts(tmp_path):
    repo = clone(
        tmp_path,
        {"origin": FORK, "m": "/srv/mirror.git"},
        push={"m": "https://github.com/x/me/tool.git"},
    )
    assert "remote `m` (a URL it cannot read)" in (refusal("gh pr create -t T -b B", repo) or "")


def test_a_remote_with_a_push_url_alone_or_no_url_still_counts(tmp_path):
    (tmp_path / "a").mkdir()
    repo = clone(tmp_path / "a", {"origin": FORK})
    _git(repo, "config", "remote.p.pushurl", PARENT)
    assert "github.com/org/tool" in (refusal("gh pr create -t T -b B", repo) or "")
    (tmp_path / "b").mkdir()
    repo = clone(tmp_path / "b", {"origin": FORK})
    _git(repo, "config", "remote.q.fetch", "+refs/heads/*:refs/remotes/q/*")
    assert "remote `q` (a URL it cannot read)" in (refusal("gh pr create -t T -b B", repo) or "")


@pytest.mark.parametrize(
    ("remotes", "marks"),
    [
        ({"origin": FORK}, {"origin": "org tool"}),  # a mark is its whole value, spaces and all
        ({"origin": "https://github.com/x/me/tool.git"}, {"origin": ""}),  # an unreadable remote
    ],
)
def test_a_mark_that_cannot_name_the_one_remote_refuses(tmp_path, remotes, marks):
    assert refusal("gh pr create -t T -b B", clone(tmp_path, remotes, marks))


def test_the_refusal_says_what_gh_would_weigh_and_never_suggests_an_unreadable_origin(tmp_path):
    repo = clone(tmp_path, {"origin": "https://github.com/x/me/tool.git", "b": FORK})
    why = refusal("gh pr create -t T -b B", repo) or ""
    assert "`gh pr create` names no repo" in why
    assert "so which one gh acts on depends on its remote order, `gh repo set-default`" in why
    assert "add `-R HOST/OWNER/NAME`" in why


def test_the_refusal_offers_gh_repo_for_a_command_with_no_r(tmp_path):
    repo = clone(tmp_path, {"origin": FORK, "upstream": PARENT})
    why = refusal("gh skill publish", repo) or ""
    assert "GH_REPO=github.com/me/tool" in why and "-R github.com/me/tool" in why
    assert refusal("GH_REPO=github.com/me/tool gh skill publish", repo) is None


def test_the_denial_log_names_this_guard(tmp_path):
    repo = clone(tmp_path, {"origin": FORK, "upstream": PARENT})
    state = tmp_path / "state"
    assert refusal("gh pr create -t T -b B", repo, XDG_STATE_HOME=str(state))
    rows = [json.loads(line) for line in (state / "phylax" / "denied-calls.jsonl").open()]
    assert [r["guard"] for r in rows] == [KEY]


@pytest.mark.parametrize(
    ("command", "refused", "env"),
    [
        ("gh pr create -a -R me/tool -t T -b B", True, {}),  # -R is -a's value
        ("gh pr create -t T -b B -R", True, {}),  # -R with no value names nothing
        ("gh pr create -Rx/tool -t T -b B", False, {}),
        ("gh pr create -Rx -t T -b B", True, {"GH_REPO": "me/tool"}),  # -R wins over GH_REPO
        ("GH_REPO=x=y gh pr create -t T -b B", True, {"GH_REPO": "me/tool"}),
        ("X=a=b gh pr create -t T -b B", True, {}),
        ("export FOO; gh pr create -t T -b B", True, {}),
        # unset drops the export: the plain assignment after it never reaches gh
        (
            "export GH_REPO=me/tool; unset GH_REPO; GH_REPO=me/tool; gh pr create -t T -b B",
            True,
            {},
        ),
        ("gh pr create -t T -R me/tool -b B", False, {}),  # -R after another option's value
        ("gh pr create -t 'a b' -R me/tool", False, {}),  # and after a quoted one
        ("gh pr merge https://github.com/me/tool/pull/3", False, {}),
        ("gh pr create -t T -b B -l bug", True, {}),  # -l is pr create's --label
        ("gh issue develop 3", True, {}),
        ("gh issue develop 3 -l", False, {}),
        ("gh issue develop 3 --list", False, {}),
        ("gh mystery help", False, {}),  # help only reads, in a group this check does not know
        ("gh secret set X --org=myorg -b v", False, {}),
        ("gh repo deploy-key ls", False, {}),
        ("gh repo deploy-key -- list", False, {}),
        ("gh repo autolink view 1", False, {}),
        ("gh repo deploy-key", False, {}),  # the group alone prints its help
        # Options are read as gh reads them (pflag), wherever they sit.
        ("gh -d -Rme/tool label create x", True, {}),  # -d is create's --description
        ("gh -b -Rme/tool pr comment 3", True, {}),  # -b is comment's --body
        ("gh label create x -fd -Rme/tool", True, {}),  # --force, then --description's value
        ("gh pr merge 3 -sb -Rme/tool", True, {}),  # --squash, then --body's value
        ("gh label create -- -Rme/tool", True, {}),  # after --, an argument
        ("gh workflow run ci.yml -f -Rme/tool", True, {}),  # -f is run's --raw-field
        # A nested group's subcommand is found as cobra finds it: past an option's value.
        ("gh repo deploy-key -t list add key.pub", True, {}),
        ("gh repo deploy-key --title view add key.pub", True, {}),
        ("gh repo deploy-key '' list", False, {}),  # cobra skips an empty word
        ("gh issue artifact list 3", False, {}),
        ("gh issue artifact create 3", True, {}),
        # gh 2.105 groups: event only reads; skill writes only on publish; repo read-*.
        ("gh event listen --resource https://github.com/org/tool/pull/1", False, {}),
        ("gh skill list", False, {}),
        ("gh skill publish", True, {}),
        ("gh repo read-file README.md", False, {}),
        ("gh repo read-dir docs", False, {}),
        ("gh pr create -R=x/tool -t T -b B", False, {}),  # gh drops the = of -R=
        ("R=me/tool; GH_REPO=$R gh pr create -t T -b B", False, {}),
        ("gh issue create -t GH_REPO=me/tool -b B", True, {}),  # an argument, not its env
        ("gh pr update-branch -c -R me/tool", False, {}),  # -c takes a value only in close
    ],
)
def test_how_a_command_names_its_repo_or_acts_on_none(tmp_path, command, refused, env):
    repo = clone(tmp_path, {"origin": FORK, "upstream": PARENT})
    assert bool(refusal(command, repo, **env)) is refused
