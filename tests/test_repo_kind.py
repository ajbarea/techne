"""Unit tests for _shared/repo_kind.py, which decides whether docsync and ci-audit act or ask.

The failure that matters is a false solo: a skill that edits someone else's repo without asking.
Only GitHub facts about the user may make a repo solo, so every other path must read as team.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ME = "ajbarea"
SLUG = f"{ME}/myrepo"
VIEW = ["gh", "repo", "view", SLUG, "--json", "parent,isInOrganization,viewerPermission"]
PUSHERS = [
    "gh", "api", "--paginate", f"repos/{SLUG}/collaborators",
    "--jq", ".[] | select(.permissions.push) | .login",
]  # fmt: skip
MINE = '{"parent":null,"isInOrganization":false,"viewerPermission":"ADMIN"}'


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


def init(root: Path) -> Path:
    root.mkdir(parents=True)
    git(root, "init", "-q", "-b", "main")
    ident = ["-c", "user.name=t", "-c", "user.email=t@t"]
    git(root, *ident, "commit", "-q", "--allow-empty", "-m", "init")
    return root


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return init(tmp_path / "ws" / "myrepo")


@pytest.fixture
def origin(repo: Path) -> Path:
    git(repo, "remote", "add", "origin", f"git@github.com:{SLUG}.git")
    return repo


@pytest.fixture
def no_toml(tmp_path: Path) -> Path:
    return tmp_path / "absent.toml"


@pytest.fixture
def gh(fp):
    """Real git runs; gh calls are stubbed per test."""
    fp.allow_unregistered(True)
    return fp


def mine(gh, pushers: str = f"{ME}\n") -> None:
    gh.register(VIEW, stdout=MINE)
    gh.register(PUSHERS, stdout=pushers)


def roster(tmp_path: Path, workspace: Path, entry: str) -> Path:
    path = tmp_path / "techne.toml"
    path.write_text(f'workspace_root = "{workspace}"\n\n[[sisters]]\n{entry}\n', encoding="utf-8")
    return path


def skill_context(root: Path, body: str) -> None:
    (root / ".claude").mkdir(exist_ok=True)
    (root / ".claude" / "skill-context.md").write_text(body, encoding="utf-8")


# --------------------------------------------------------- the solo path ----


def test_own_repo_with_no_other_pusher_is_solo(rk, origin, no_toml, gh):
    mine(gh)
    assert rk.classify(str(origin), no_toml)[0] == "solo"


def test_a_file_target_is_classified_by_its_folder(rk, origin, no_toml, gh):
    (origin / "README.md").write_text("x", encoding="utf-8")
    mine(gh)
    assert rk.classify(str(origin / "README.md"), no_toml)[0] == "solo"


def test_a_missing_file_target_walks_up_to_its_repo(rk, origin, no_toml, gh):
    mine(gh)
    assert rk.classify(str(origin / "docs" / "new.md"), no_toml)[0] == "solo"


def test_an_exported_git_dir_does_not_redirect_the_check(
    rk, origin, tmp_path, no_toml, gh, monkeypatch
):
    other = init(tmp_path / "elsewhere")
    skill_context(other, "## repo\n- owner: team\n")
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    mine(gh)
    assert rk.classify(str(origin), no_toml)[0] == "solo"


def test_an_unreadable_toml_still_reaches_github(rk, origin, tmp_path, gh):
    bad = tmp_path / "techne.toml"
    bad.write_text("this is = = not toml", encoding="utf-8")
    mine(gh)
    assert rk.classify(str(origin), bad)[0] == "solo"


# ---------------------------------------------- signals that only say team --


def test_owner_team_in_the_repo_section_is_team(rk, origin, no_toml, gh):
    mine(gh)  # GitHub alone would say solo, so team must come from the signal
    skill_context(origin, "# ctx\n\n## repo\n\n- name: x\n- owner: Team, lab site\n")
    assert rk.classify(str(origin), no_toml) == ("team", "owner: team in .claude/skill-context.md")


def test_owner_solo_is_not_trusted_on_its_own(rk, repo, no_toml):
    skill_context(repo, "## repo\n- owner: solo\n")
    assert rk.classify(str(repo), no_toml)[0] == "team"


def test_an_owner_line_outside_the_repo_section_is_ignored(rk, origin, no_toml, gh):
    skill_context(origin, "## repo\n- name: x\n\n## audit\n- owner: team\n")
    mine(gh)
    assert rk.classify(str(origin), no_toml)[0] == "solo"


def test_a_sister_marked_team_is_team(rk, origin, tmp_path, gh):
    mine(gh)  # GitHub alone would say solo, so team must come from the signal
    toml = roster(tmp_path, origin.parent, 'name = "myrepo"\nkind = "team"')
    assert rk.classify(str(origin), toml)[0] == "team"


def test_a_worktree_finds_its_main_checkouts_roster_entry(rk, origin, tmp_path, gh):
    mine(gh)  # GitHub alone would say solo, so team must come from the signal
    wt = tmp_path / "wt" / "feature-x"
    git(origin, "worktree", "add", "-q", str(wt), "-b", "feature-x")
    toml = roster(tmp_path, origin.parent, 'name = "myrepo"\nkind = "team"')
    assert rk.classify(str(wt), toml)[0] == "team"


def test_a_listed_sister_still_needs_github_to_be_solo(rk, repo, tmp_path):
    toml = roster(tmp_path, repo.parent, 'name = "myrepo"')
    assert rk.classify(str(repo), toml) == ("team", "no GitHub origin to check ownership against")


def test_a_same_named_sister_elsewhere_does_not_match(rk, origin, tmp_path, gh):
    toml = roster(tmp_path, tmp_path / "other-workspace", 'name = "myrepo"\nkind = "team"')
    mine(gh)
    assert rk.classify(str(origin), toml)[0] == "solo"


# ----------------------------------------------------------------- GitHub --


def test_another_pusher_makes_it_team(rk, origin, no_toml, gh):
    mine(gh, pushers=f"{ME}\nclassmate\n")
    assert rk.classify(str(origin), no_toml) == ("team", f"{ME}, classmate can push to {SLUG}")


@pytest.mark.parametrize(
    "view",
    [
        '{"parent":null,"isInOrganization":true,"viewerPermission":"ADMIN"}',
        '{"parent":null,"isInOrganization":false,"viewerPermission":"WRITE"}',
        '{"parent":{"name":"up","owner":{"login":"lab"}},"isInOrganization":false,'
        '"viewerPermission":"ADMIN"}',
        "not json",
        "",
    ],
    ids=["organization", "not-admin", "fork-of-live-upstream", "bad-json", "empty"],
)
def test_github_facts_short_of_ownership_are_team(rk, origin, no_toml, gh, view):
    gh.register(VIEW, stdout=view)
    gh.register(PUSHERS, stdout=f"{ME}\n")
    assert rk.classify(str(origin), no_toml)[0] == "team"


def test_a_fork_listed_as_a_sister_is_the_users_own_line(rk, origin, tmp_path, gh):
    toml = roster(tmp_path, origin.parent, 'name = "myrepo"')
    fork = '{"parent":{"name":"up","owner":{"login":"lab"}},"isInOrganization":false,'
    gh.register(VIEW, stdout=fork + '"viewerPermission":"ADMIN"}')
    gh.register(PUSHERS, stdout=f"{ME}\n")
    assert rk.classify(str(origin), toml)[0] == "solo"


@pytest.mark.parametrize("pushers", [None, ""], ids=["gh-fails", "nobody-listed"])
def test_unlistable_or_empty_collaborators_are_team(rk, origin, no_toml, gh, pushers):
    gh.register(VIEW, stdout=MINE)
    if pushers is None:
        gh.register(PUSHERS, returncode=1)
    else:
        gh.register(PUSHERS, stdout=pushers)
    assert rk.classify(str(origin), no_toml)[0] == "team"


def test_gh_failing_outright_is_team(rk, origin, no_toml, gh):
    gh.register(VIEW, returncode=1)
    assert rk.classify(str(origin), no_toml) == ("team", f"could not read {SLUG} on GitHub")


# -------------------------------------------------------------- fallbacks --


def test_outside_a_repo_is_team(rk, tmp_path, no_toml):
    assert rk.classify(str(tmp_path), no_toml)[0] == "team"


def test_no_github_origin_is_team(rk, repo, no_toml):
    git(repo, "remote", "add", "origin", "https://gitlab.com/x/myrepo.git")
    assert rk.classify(str(repo), no_toml)[0] == "team"


def test_main_prints_one_line_and_exits_zero(rk, origin, capsys, monkeypatch, no_toml, gh):
    monkeypatch.setattr(rk.classify, "__defaults__", (".", no_toml))
    mine(gh)
    assert rk.main(["repo_kind.py", str(origin)]) == 0
    assert capsys.readouterr().out == (
        f"solo: {ME} owns {SLUG} and is its only collaborator with push access\n"
    )


# ----------------------------------------------------- round-2 regressions --


def test_python_without_tomllib_reads_an_existing_toml_as_team(
    rk, origin, tmp_path, gh, monkeypatch
):
    toml = roster(tmp_path, origin.parent, 'name = "myrepo"')
    monkeypatch.setitem(__import__("sys").modules, "tomllib", None)  # as on python3 3.9
    mine(gh)
    kind, why = rk.classify(str(origin), toml)
    assert kind == "team" and "cannot read" in why


def test_a_symlinked_workspace_root_still_matches(rk, origin, tmp_path, gh):
    mine(gh)  # GitHub alone would say solo, so team must come from the signal
    link = tmp_path / "link"
    link.symlink_to(origin.parent)
    toml = roster(tmp_path, link, 'name = "myrepo"\nkind = "team"')
    assert rk.classify(str(origin), toml)[0] == "team"


def test_an_exported_git_common_dir_does_not_redirect_the_check(
    rk, origin, tmp_path, no_toml, gh, monkeypatch
):
    mine(gh)  # GitHub alone would say solo, so team must come from the signal
    other = init(tmp_path / "elsewhere")
    git(
        other, "remote", "add", "origin", f"git@github.com:{SLUG}.git"
    )  # a decoy that reaches GitHub
    monkeypatch.setenv("GIT_COMMON_DIR", str(other / ".git"))
    toml = roster(tmp_path, origin.parent, 'name = "myrepo"\nkind = "team"')
    assert rk.classify(str(origin), toml)[0] == "team"


def test_a_repo_heading_with_other_case_or_suffix_still_counts(rk, origin, no_toml, gh):
    mine(gh)  # GitHub alone would say solo, so team must come from the signal
    skill_context(origin, "## Repo (lab site)\n- owner: team\n")
    assert rk.classify(str(origin), no_toml)[0] == "team"


def test_a_committed_owner_line_counts_when_the_working_copy_lacks_it(rk, origin, no_toml, gh):
    mine(gh)  # GitHub alone would say solo, so team must come from the signal
    skill_context(origin, "## repo\n- owner: team\n")
    git(origin, "add", ".claude")
    git(origin, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "ctx")
    (origin / ".claude" / "skill-context.md").write_text("## repo\n- name: x\n", encoding="utf-8")
    assert rk.classify(str(origin), no_toml)[0] == "team"


def test_the_shipped_template_does_not_mark_a_repo_team(rk):
    from conftest import ROOT

    template = ROOT / "plugins/techne/skills/setup/skill-context.template.md"
    assert not rk.OWNER_TEAM.search(rk.repo_section(template.read_text(encoding="utf-8")))
