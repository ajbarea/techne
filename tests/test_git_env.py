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
