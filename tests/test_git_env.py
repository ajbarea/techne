"""git_env.batch_ssh: batch-mode ssh for unattended git, unless the user chose an ssh command."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest
from conftest import ROOT, _load, assert_gone

GIT_ENV = ROOT / "plugins" / "techne" / "_shared" / "git_env.py"


@pytest.fixture(scope="module")
def ge():
    return _load("techne_git_env", GIT_ENV)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    return path


def test_no_choice_gets_batch_ssh(ge, repo):
    env = {"PATH": "/usr/bin:/bin", "KEEP": "1"}
    out = ge.batch_ssh(env, repo)
    assert out["GIT_SSH_COMMAND"] == ge.BATCH_SSH
    assert "BatchMode=yes" in ge.BATCH_SSH
    assert out["KEEP"] == "1"
    assert "GIT_SSH_COMMAND" not in env  # the caller's dict is not changed


@pytest.mark.parametrize(
    "chosen", [{"GIT_SSH_COMMAND": "ssh -i key"}, {"GIT_SSH": "/opt/bin/my-ssh"}]
)
def test_an_ssh_command_in_the_environment_is_kept(ge, repo, chosen):
    env = {"PATH": "/usr/bin:/bin", **chosen}
    assert ge.batch_ssh(env, repo) == env


def test_the_repos_core_sshcommand_is_kept(ge, repo):
    subprocess.run(["git", "-C", str(repo), "config", "core.sshCommand", "ssh -i work"], check=True)
    env = {"PATH": "/usr/bin:/bin"}
    assert "GIT_SSH_COMMAND" not in ge.batch_ssh(env, repo)


@pytest.mark.parametrize("error", [subprocess.TimeoutExpired("git", 10), OSError("no git")])
def test_a_failed_config_read_falls_back_to_batch_ssh(ge, repo, monkeypatch, error):
    def fail(*a, **kw):
        raise error

    monkeypatch.setattr(ge.subprocess, "run", fail)
    assert ge.batch_ssh({"PATH": "/usr/bin:/bin"}, repo)["GIT_SSH_COMMAND"] == ge.BATCH_SSH


CONFIG_VARS = {"GIT_CONFIG", "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT"}


def test_local_env_matches_what_git_reports(ge):
    """git's own list, minus the config variables a job injects on purpose."""
    reported = subprocess.run(
        ["git", "rev-parse", "--local-env-vars"], capture_output=True, text=True, check=True
    ).stdout.split()
    # Every entry is one git still reports, and no config variable is stripped. A git release
    # that adds a variable leaves this green; LOCAL_ENV then misses it until someone adds it.
    assert set(ge.LOCAL_ENV) <= set(reported)
    assert not set(ge.LOCAL_ENV) & CONFIG_VARS


def test_repo_overrides_are_dropped_and_injected_config_is_kept(ge):
    env = {
        "GIT_DIR": "/elsewhere/.git",
        "GIT_INDEX_FILE": "/elsewhere/index",
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "safe.directory",
        "GIT_CONFIG_VALUE_0": "*",
        "GIT_CONFIG_PARAMETERS": "'credential.helper'='store'",
        "PATH": "/bin",
    }
    kept = ge.without_repo_overrides(env)
    assert "GIT_DIR" not in kept and "GIT_INDEX_FILE" not in kept
    assert {
        "GIT_CONFIG_COUNT",
        "GIT_CONFIG_KEY_0",
        "GIT_CONFIG_VALUE_0",
        "GIT_CONFIG_PARAMETERS",
    } <= kept.keys()


def test_the_installed_gits_own_list_is_used(ge, monkeypatch):
    class Done:
        returncode = 0
        stdout = "GIT_DIR GIT_SOME_NEW_REDIRECT GIT_CONFIG_PARAMETERS\n"

    monkeypatch.setattr(ge, "_local_env_cache", None)
    monkeypatch.setattr(ge.subprocess, "run", lambda *a, **k: Done())
    assert ge.local_env() == {"GIT_DIR", "GIT_SOME_NEW_REDIRECT"}


@pytest.mark.parametrize("failure", ["exit", "empty", "missing"])
def test_the_fixed_list_is_used_when_git_cannot_be_asked(ge, monkeypatch, failure):
    class Done:
        returncode = 1 if failure == "exit" else 0
        stdout = "GIT_PARTIAL\n" if failure == "exit" else ""

    def run(*args, **kwargs):
        if failure == "missing":
            raise FileNotFoundError("git")
        return Done()

    monkeypatch.setattr(ge, "_local_env_cache", None)
    monkeypatch.setattr(ge.subprocess, "run", run)
    assert ge.local_env() == set(ge.LOCAL_ENV)


def test_a_github_remote_needs_no_ssh(ge, fp):
    assert ge.github_slug("https://github.com/o/r.git") == ("o", "r")
    assert ge.github_slug("git@github.com:o/r") == ("o", "r")
    assert fp.call_count(["ssh", fp.any()]) == 0


@pytest.mark.parametrize(
    "url, slug",
    [("git@github-work:o/r.git", ("o", "r")), ("ssh://git@github-work/o/r", ("o", "r")),
     ("github-work:o/r", ("o", "r")), ("git@github-work:1234/r.git", ("1234", "r")),
     ("ssh://git@github-work:22/o/r.git", ("o", "r")), ("git+ssh://github-work/o/r", ("o", "r"))],
)  # fmt: skip
def test_an_ssh_alias_resolving_to_github_counts(ge, fp, url, slug):
    fp.register(["ssh", "-G", "--", "github-work"], stdout="user git\nhostname github.com\n")
    assert ge.github_slug(url) == slug


@pytest.mark.parametrize(
    "stdout, returncode", [("hostname gitlab.com\n", 0), ("", 255)], ids=["other-host", "ssh-fails"]
)
def test_an_ssh_alias_elsewhere_or_unresolved_does_not_count(ge, fp, stdout, returncode):
    fp.register(["ssh", "-G", "--", "work"], stdout=stdout, returncode=returncode)
    assert ge.github_slug("git@work:o/r") is None


@pytest.mark.parametrize(
    "url",
    ["/srv/git/r.git", "-oProxyCommand=x:o/r", "https://gitlab.com/o/r", "../o/r", "o/r",
     "ssh://github-work:1234/r"],
)  # fmt: skip
def test_paths_options_and_other_hosts_never_reach_ssh(ge, fp, url):
    fp.register(["ssh", fp.any()], stdout="hostname github.com\n", occurrences=3)
    assert ge.github_slug(url) is None
    assert fp.call_count(["ssh", fp.any()]) == 0


def test_ssh_g_cannot_leave_a_child_holding_the_pipe(ge, tmp_path, monkeypatch):
    pidfile, bindir = tmp_path / "pid", tmp_path / "bin"
    bindir.mkdir()
    ssh = bindir / "ssh"
    ssh.write_text(f'#!/bin/sh\n/bin/sleep 30 &\necho $! > "{pidfile}"\n/bin/sleep 30\n')
    ssh.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}:/usr/bin:/bin")
    monkeypatch.setattr(ge, "CONFIG_TIMEOUT", 1)
    started = time.monotonic()
    assert ge.github_slug("git@github-work:o/r") is None
    assert time.monotonic() - started < 5
    assert_gone(int(pidfile.read_text()))


def test_git_env_loaded_by_file_path_alone_still_resolves_an_alias(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "ssh").write_text("#!/bin/sh\necho 'hostname github.com'\n")
    (bindir / "ssh").chmod(0o755)
    code = (
        "import importlib.util, sys\n"
        f"spec = importlib.util.spec_from_file_location('git_env', {str(GIT_ENV)!r})\n"
        "mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)\n"
        "print(mod.github_slug('git@github-work:o/r'))\n"
    )
    out = subprocess.run(
        [sys.executable, "-I", "-B", "-c", code],
        capture_output=True,
        text=True,
        env={"PATH": f"{bindir}:/usr/bin:/bin"},
        check=True,
    ).stdout
    assert out.strip() == "('o', 'r')"
