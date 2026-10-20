"""Unit tests for _shared/repo_kind.py, which decides whether docsync and ci-audit act or ask.

The failure that matters is a false solo: a skill that edits someone else's repo without asking.
So every unsettled case must read as team, and the tests below pin each one.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ME = "ajbarea"
USER = ["gh", "api", "user", "--jq", ".login"]


def repo_info(owner: str, name: str) -> list[str]:
    jq = "{login: .owner.login, type: .owner.type}"
    return ["gh", "api", f"repos/{owner}/{name}", "--jq", jq]


def pushers(owner: str, name: str) -> list[str]:
    return [
        "gh",
        "api",
        "--paginate",
        f"repos/{owner}/{name}/collaborators",
        "--jq",
        ".[] | select(.permissions.push) | .login",
    ]


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "myrepo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    ident = ["-c", "user.name=t", "-c", "user.email=t@t"]
    git(root, *ident, "commit", "-q", "--allow-empty", "-m", "init")
    return root


@pytest.fixture
def no_toml(tmp_path: Path) -> Path:
    return tmp_path / "absent.toml"


def write_toml(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "techne.toml"
    path.write_text(body, encoding="utf-8")
    return path


def skill_context(root: Path, body: str) -> None:
    (root / ".claude").mkdir(exist_ok=True)
    (root / ".claude" / "skill-context.md").write_text(body, encoding="utf-8")


# ------------------------------------------------------------- skill-context --


@pytest.mark.parametrize("line, kind", [("- owner: team", "team"), ("- owner: Solo, mine", "solo")])
def test_the_committed_owner_line_decides(rk, repo, no_toml, line, kind):
    skill_context(repo, f"# ctx\n\n## repo\n\n- name: x\n{line}\n\n## audit\n- phases: lint\n")
    assert rk.classify(str(repo), no_toml)[0] == kind


def test_an_owner_line_outside_the_repo_section_is_ignored(rk, repo, no_toml, fp):
    fp.allow_unregistered(True)
    skill_context(repo, "## repo\n\n- name: x\n\n## audit\n- owner: solo\n")
    assert rk.classify(str(repo), no_toml) == (
        "team",
        "no GitHub origin to check ownership against",
    )


def test_the_owner_line_outranks_techne_toml(rk, repo, tmp_path):
    skill_context(repo, "## repo\n- owner: team\n")
    toml = write_toml(tmp_path, '[[sisters]]\nname = "myrepo"\nstatus = "active"\n')
    assert rk.classify(str(repo), toml)[0] == "team"


# ---------------------------------------------------------------- techne.toml --


def test_a_listed_sister_without_kind_is_solo(rk, repo, tmp_path):
    toml = write_toml(tmp_path, '[[sisters]]\nname = "myrepo"\nstatus = "active"\n')
    assert rk.classify(str(repo), toml)[0] == "solo"


def test_a_sister_marked_team_is_team(rk, repo, tmp_path):
    toml = write_toml(tmp_path, '[[sisters]]\nname = "myrepo"\nkind = "team"\n')
    assert rk.classify(str(repo), toml)[0] == "team"


def test_a_worktree_matches_its_main_checkouts_name(rk, repo, tmp_path):
    wt = tmp_path / "elsewhere" / "feature-x"
    git(repo, "worktree", "add", "-q", str(wt), "-b", "feature-x")
    toml = write_toml(tmp_path, '[[sisters]]\nname = "myrepo"\n')
    assert rk.classify(str(wt), toml)[0] == "solo"


def test_the_origin_name_matches_when_the_folder_differs(rk, repo, tmp_path):
    git(repo, "remote", "add", "origin", "git@github.com:ajbarea/other-name.git")
    toml = write_toml(tmp_path, '[[sisters]]\nname = "other-name"\n')
    assert rk.classify(str(repo), toml)[0] == "solo"


def test_an_unreadable_toml_falls_through_to_github(rk, repo, tmp_path, fp):
    fp.allow_unregistered(True)
    toml = write_toml(tmp_path, "this is = = not toml")
    assert rk.classify(str(repo), toml)[0] == "team"


# --------------------------------------------------------------------- GitHub --


@pytest.fixture
def origin(repo: Path) -> Path:
    git(repo, "remote", "add", "origin", f"https://github.com/{ME}/myrepo.git")
    return repo


def test_own_repo_with_no_other_pusher_is_solo(rk, origin, no_toml, fp):
    fp.allow_unregistered(True)
    fp.register(USER, stdout=f"{ME}\n")
    fp.register(repo_info(ME, "myrepo"), stdout=f'{{"login":"{ME}","type":"User"}}\n')
    fp.register(pushers(ME, "myrepo"), stdout=f"{ME}\n")
    assert rk.classify(str(origin), no_toml)[0] == "solo"


def test_another_pusher_makes_it_team(rk, origin, no_toml, fp):
    fp.allow_unregistered(True)
    fp.register(USER, stdout=f"{ME}\n")
    fp.register(repo_info(ME, "myrepo"), stdout=f'{{"login":"{ME}","type":"User"}}\n')
    fp.register(pushers(ME, "myrepo"), stdout=f"{ME}\nclassmate\n")
    assert rk.classify(str(origin), no_toml) == ("team", f"classmate can push to {ME}/myrepo")


@pytest.mark.parametrize(
    "info",
    [
        '{"login":"someone","type":"User"}',
        f'{{"login":"{ME}","type":"Organization"}}',
        "not json",
        "",
    ],
)
def test_a_repo_not_owned_by_the_user_or_unreadable_is_team(rk, origin, no_toml, fp, info):
    fp.allow_unregistered(True)
    fp.register(USER, stdout=f"{ME}\n")
    fp.register(repo_info(ME, "myrepo"), stdout=info)
    assert rk.classify(str(origin), no_toml)[0] == "team"


def test_no_signed_in_user_is_team(rk, origin, no_toml, fp):
    fp.allow_unregistered(True)
    fp.register(USER, returncode=1)
    assert rk.classify(str(origin), no_toml) == ("team", "could not read the signed-in GitHub user")


def test_unlistable_collaborators_is_team(rk, origin, no_toml, fp):
    fp.allow_unregistered(True)
    fp.register(USER, stdout=f"{ME}\n")
    fp.register(repo_info(ME, "myrepo"), stdout=f'{{"login":"{ME}","type":"User"}}\n')
    fp.register(pushers(ME, "myrepo"), returncode=1)
    assert rk.classify(str(origin), no_toml)[0] == "team"


# ------------------------------------------------------------------ fallbacks --


def test_outside_a_repo_is_team(rk, tmp_path, no_toml):
    assert rk.classify(str(tmp_path), no_toml)[0] == "team"


def test_main_prints_one_line_and_exits_zero(rk, repo, capsys, monkeypatch, tmp_path):
    monkeypatch.setattr(rk, "TECHNE_TOML", tmp_path / "absent.toml")
    monkeypatch.setattr(rk.classify, "__defaults__", (".", tmp_path / "absent.toml"))
    skill_context(repo, "## repo\n- owner: solo\n")
    assert rk.main(["repo_kind.py", str(repo)]) == 0
    assert capsys.readouterr().out == "solo: owner line in .claude/skill-context.md\n"
