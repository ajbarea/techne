"""git_env.batch_ssh: batch-mode ssh for unattended git, unless the user chose an ssh command."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from conftest import ROOT, _load

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


def test_a_variable_a_newer_git_reports_is_dropped_too(ge, monkeypatch):
    class Done:
        stdout = "GIT_DIR GIT_SOME_NEW_REDIRECT GIT_CONFIG_PARAMETERS\n"

    monkeypatch.setattr(ge, "_local_env_cache", None)
    monkeypatch.setattr(ge.subprocess, "run", lambda *a, **k: Done())
    drop = ge.local_env()
    assert "GIT_SOME_NEW_REDIRECT" in drop and "GIT_CONFIG_PARAMETERS" not in drop
    assert set(ge.LOCAL_ENV) <= drop
