"""Unit tests for _shared/repo_kind.py, which decides whether docsync and ci-audit act or ask.

The failure that matters is a false solo: a skill that edits someone else's repo without asking.
Only GitHub facts about the user may make a repo solo, so every other path must read as team.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

ME = "ajbarea"
SLUG = f"{ME}/myrepo"
QUERY = (
    "query($o:String!,$n:String!){repository(owner:$o,name:$n){"
    "owner{login} parent{name owner{login}} isInOrganization viewerPermission "
    'object(expression:"HEAD:.claude/skill-context.md"){... on Blob{text isBinary isTruncated}}}}'
)


def repo_query(name: str = "myrepo") -> list[str]:
    return [
        "gh", "api", "--hostname", "github.com", "graphql", "-f", f"query={QUERY}",
        "-f", f"o={ME}", "-f", f"n={name}", "--jq", ".data.repository",
    ]  # fmt: skip


REPO = repo_query()
PUSHERS = [
    "gh", "api", "--hostname", "github.com", "--paginate", f"repos/{SLUG}/collaborators",
    "--jq", ".[] | select(.permissions.push) | .login",
]  # fmt: skip
INVITED = [
    "gh", "api", "--hostname", "github.com", "--paginate", f"repos/{SLUG}/invitations",
    "--jq", ".[].invitee.login",
]  # fmt: skip
MINE = json.dumps(
    {
        "owner": {"login": ME},
        "parent": None,
        "isInOrganization": False,
        "viewerPermission": "ADMIN",
        "object": None,
    }
)


def view(**changes) -> str:
    return json.dumps({**json.loads(MINE), **changes})


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
def gh(fp, tmp_path, monkeypatch):
    """Real git runs; gh calls are stubbed per test. A gh call no test stubbed reaches a fake gh
    that records it, and the test fails, so no test can pass on a real network answer."""
    fp.allow_unregistered(True)
    bin_dir, log = tmp_path / "fake-bin", tmp_path / "unstubbed-gh.log"
    bin_dir.mkdir()
    fake = bin_dir / "gh"
    fake.write_text(f'#!/bin/sh\necho "$*" >> "{log}"\nexit 97\n', encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{__import__('os').environ['PATH']}")
    yield fp
    assert not log.exists(), f"unstubbed gh call: {log.read_text(encoding='utf-8')}"


def mine(gh, pushers: str = f"{ME}\n", invited: str = "", on_default: str = "") -> None:
    blob = {"text": on_default, "isBinary": False} if on_default else None
    gh.register(REPO, stdout=view(object=blob))
    gh.register(PUSHERS, stdout=pushers)
    gh.register(INVITED, stdout=invited)


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


def test_an_unreadable_toml_reads_as_team(rk, origin, tmp_path, gh):
    mine(gh)  # GitHub alone would say solo, so team must come from the signal
    bad = tmp_path / "techne.toml"
    bad.write_text("this is = = not toml", encoding="utf-8")
    kind, why = rk.classify(str(origin), bad)
    assert kind == "team" and why.startswith("cannot read")


# ---------------------------------------------- signals that only say team --


def test_owner_team_in_the_repo_section_is_team(rk, origin, no_toml, gh):
    mine(gh)  # GitHub alone would say solo, so team must come from the signal
    skill_context(origin, "# ctx\n\n## repo\n\n- name: x\n- owner: Team, lab site\n")
    assert rk.classify(str(origin), no_toml) == ("team", "owner: team in .claude/skill-context.md")


def test_owner_solo_is_not_trusted_on_its_own(rk, repo, no_toml):
    skill_context(repo, "## repo\n- owner: solo\n")
    assert rk.classify(str(repo), no_toml)[0] == "team"


@pytest.mark.parametrize(
    "body",
    [
        "## audit\n- owner: team\n",
        "- owner: team\n\n## repo\n- name: x\n",
        "## repo\n* owner: team\n",
        "## repo\n+ owner: team\n",
        "## repo\n- **owner:** team\n",
    ],
    ids=["other-section", "above-headings", "star", "plus", "bold"],
)
def test_an_owner_team_line_counts_anywhere_in_any_form(rk, origin, no_toml, gh, body):
    mine(gh)  # GitHub alone would say solo, so team must come from the signal
    skill_context(origin, body)
    assert rk.classify(str(origin), no_toml)[0] == "team"


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
    "stdout",
    [
        view(isInOrganization=True),
        view(viewerPermission="WRITE"),
        view(parent={"name": "up", "owner": {"login": "lab"}}),
        "not json",
        "",
    ],
    ids=["organization", "not-admin", "fork-of-live-upstream", "bad-json", "empty"],
)
def test_github_facts_short_of_ownership_are_team(rk, origin, no_toml, gh, stdout):
    gh.register(REPO, stdout=stdout)
    gh.register(PUSHERS, stdout=f"{ME}\n")
    gh.register(INVITED, stdout="")
    assert rk.classify(str(origin), no_toml)[0] == "team"


@pytest.mark.parametrize(
    "entry, kind",
    [('name = "myrepo"\nkind = "solo"', "solo"), ('name = "myrepo"\nkind = "Solo"', "solo"),
     ('name = "myrepo"', "team")],
    ids=["kind-solo", "kind-Solo", "listed-without-kind"],
)  # fmt: skip
def test_a_fork_is_solo_only_when_its_sister_entry_says_so(rk, origin, tmp_path, gh, entry, kind):
    toml = roster(tmp_path, origin.parent, entry)
    gh.register(REPO, stdout=view(parent={"name": "up", "owner": {"login": "lab"}}))
    gh.register(PUSHERS, stdout=f"{ME}\n")
    gh.register(INVITED, stdout="")
    assert rk.classify(str(origin), toml)[0] == kind


@pytest.mark.parametrize("pushers", [None, ""], ids=["gh-fails", "nobody-listed"])
def test_unlistable_or_empty_collaborators_are_team(rk, origin, no_toml, gh, pushers):
    gh.register(REPO, stdout=MINE)
    if pushers is None:
        gh.register(PUSHERS, returncode=1)
    else:
        gh.register(PUSHERS, stdout=pushers)
    gh.register(INVITED, stdout="")
    assert rk.classify(str(origin), no_toml)[0] == "team"


def test_gh_failing_outright_is_team(rk, origin, no_toml, gh):
    for call in (REPO, PUSHERS, INVITED):
        gh.register(call, returncode=1)
    assert rk.classify(str(origin), no_toml) == ("team", f"could not read {SLUG} on GitHub")


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
    assert not rk.says_team(template.read_text(encoding="utf-8"))


@pytest.mark.parametrize("line", ["owner: team", 'owner: "team"', "  - Owner: TEAM (lab)"])
def test_owner_team_counts_with_or_without_a_dash_or_quotes(rk, origin, no_toml, gh, line):
    mine(gh)  # GitHub alone would say solo, so team must come from the signal
    skill_context(origin, f"## repo\n- name: x\n{line}\n")
    assert rk.classify(str(origin), no_toml)[0] == "team"


def test_a_separate_git_dir_checkout_finds_its_roster_entry(rk, tmp_path, gh):
    mine(gh)  # GitHub alone would say solo, so team must come from the signal
    root = tmp_path / "ws" / "myrepo"
    root.mkdir(parents=True)
    (tmp_path / "gitdirs").mkdir()
    git(root, "init", "-q", "-b", "main", f"--separate-git-dir={tmp_path / 'gitdirs' / 'myrepo'}")
    git(root, "remote", "add", "origin", f"git@github.com:{SLUG}.git")
    toml = roster(tmp_path, root.parent, 'name = "myrepo"\nkind = "team"')
    assert rk.classify(str(root), toml)[0] == "team"


def test_the_script_runs_on_the_oldest_python(tmp_path):
    """make test-hooks-oldest sets TECHNE_GUARD_PYTHON, so this runs the script on 3.9 there."""
    from conftest import HOOK_PYTHON, ROOT

    repo = init(tmp_path / "plain")
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "techne.toml").write_text('workspace_root = "/x"\n', encoding="utf-8")
    script = ROOT / "plugins/techne/_shared/repo_kind.py"
    env = {"HOME": str(home), "PATH": __import__("os").environ["PATH"]}
    done = subprocess.run(
        [HOOK_PYTHON, str(script), str(repo)], capture_output=True, text=True, env=env
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.startswith("team: "), done.stdout


# ----------------------------------------------------- round-4 regressions --


def worktree_of_bare(tmp_path: Path, bare: Path, wt: Path) -> Path:
    src = init(tmp_path / "src")
    subprocess.run(["git", "clone", "-q", "--bare", str(src), str(bare)], check=True)
    git(bare, "worktree", "add", "-q", str(wt))
    git(wt, "remote", "set-url", "origin", f"git@github.com:{SLUG}.git")
    return wt


@pytest.mark.parametrize("layout", ["dot-bare", "name-dot-git"])
def test_a_worktree_of_a_bare_repo_finds_its_roster_entry(rk, tmp_path, gh, layout):
    mine(gh)  # GitHub alone would say solo, so team must come from the signal
    ws = tmp_path / "ws"
    if layout == "dot-bare":
        wt = worktree_of_bare(tmp_path, ws / "myrepo" / ".bare", ws / "myrepo" / "main")
    else:
        wt = worktree_of_bare(tmp_path, ws / "myrepo.git", tmp_path / "wts" / "main")
    toml = roster(tmp_path, ws, 'name = "myrepo"\nkind = "team"')
    assert rk.classify(str(wt), toml)[0] == "team"


@pytest.mark.parametrize("kind", ["Team", "TEAM"])
def test_the_roster_kind_is_case_insensitive(rk, origin, tmp_path, gh, kind):
    mine(gh)  # GitHub alone would say solo, so team must come from the signal
    toml = roster(tmp_path, origin.parent, f'name = "myrepo"\nkind = "{kind}"')
    assert rk.classify(str(origin), toml)[0] == "team"


def test_a_pending_invitation_makes_it_team(rk, origin, no_toml, gh):
    mine(gh, invited="classmate\n")
    assert rk.classify(str(origin), no_toml) == ("team", f"classmate is invited to {SLUG}")


def test_unlistable_invitations_are_team(rk, origin, no_toml, gh):
    gh.register(REPO, stdout=MINE)
    gh.register(PUSHERS, stdout=f"{ME}\n")
    gh.register(INVITED, returncode=1)
    assert rk.classify(str(origin), no_toml)[0] == "team"


# ----------------------------------------------------- round-5 regressions --


def test_a_non_utf8_toml_reads_as_team(rk, origin, tmp_path, gh):
    mine(gh)  # GitHub alone would say solo, so team must come from the signal
    bad = tmp_path / "techne.toml"
    bad.write_bytes(b"# caf\xe9\nworkspace_root = '/x'\n")
    kind, why = rk.classify(str(origin), bad)
    assert kind == "team" and why.startswith("cannot read")


@pytest.mark.parametrize(
    "url",
    [
        "https://git.example.org/mirrors/github.com/ajbarea/myrepo",
        "https://evilgithub.com/ajbarea/myrepo",
    ],
)
def test_an_origin_on_another_host_is_not_checked_on_github(rk, repo, no_toml, gh, url):
    mine(gh)  # GitHub alone would say solo, so team must come from the host check
    git(repo, "remote", "add", "origin", url)
    assert rk.classify(str(repo), no_toml) == (
        "team",
        "no GitHub origin to check ownership against",
    )


def test_every_plugin_ships_the_same_git_env():
    from conftest import ROOT

    source = ROOT / "plugins/techne/_shared/git_env.py"
    copies = sorted(ROOT.glob("plugins/*/_shared/git_env.py"))
    assert len(copies) >= 2
    for copy in copies:
        assert copy.read_bytes() == source.read_bytes(), copy


def test_running_the_script_writes_no_bytecode_into_the_plugin(tmp_path):
    import shutil

    from conftest import HOOK_PYTHON, ROOT

    shared = tmp_path / "_shared"
    shutil.copytree(
        ROOT / "plugins/techne/_shared", shared, ignore=shutil.ignore_patterns("__pycache__")
    )
    repo = init(tmp_path / "plain")
    env = {"HOME": str(tmp_path), "PATH": __import__("os").environ["PATH"]}
    subprocess.run([HOOK_PYTHON, str(shared / "repo_kind.py"), str(repo)], env=env, check=True)
    assert not (shared / "__pycache__").exists()


# ----------------------------------------------------- round-6 regressions --


@pytest.mark.parametrize(
    "line",
    ["- owner: __team__", "- owner: _team_", "1. owner: team", "> owner: team",
     "| owner | team |", "owner = team"],
)  # fmt: skip
def test_owner_team_in_more_markdown_forms(rk, origin, no_toml, gh, line):
    mine(gh)  # GitHub alone would say solo, so team must come from the signal
    skill_context(origin, f"## repo\n{line}\n")
    assert rk.classify(str(origin), no_toml)[0] == "team"


@pytest.mark.parametrize("line", ["- owner: solo", "- ownership: team-x", "- teams: 3"])
def test_near_miss_owner_lines_do_not_count(rk, origin, no_toml, gh, line):
    mine(gh)
    skill_context(origin, f"## repo\n{line}\n")
    assert rk.classify(str(origin), no_toml)[0] == "solo"


def test_the_owner_line_on_githubs_default_branch_counts(rk, origin, no_toml, gh):
    mine(gh, on_default="# ctx\n## repo\n- owner: team\n")  # not fetched into this clone
    assert rk.classify(str(origin), no_toml) == (
        "team",
        f"owner: team in .claude/skill-context.md on {SLUG}'s default branch",
    )


def test_a_binary_default_branch_copy_is_team(rk, origin, no_toml, gh):
    gh.register(REPO, stdout=view(object={"text": None, "isBinary": True}))  # e.g. UTF-16
    gh.register(PUSHERS, stdout=f"{ME}\n")
    gh.register(INVITED, stdout="")
    assert rk.classify(str(origin), no_toml)[0] == "team"


def test_another_clone_of_a_team_sister_is_team(rk, tmp_path, gh):
    mine(gh)  # GitHub alone would say solo, so team must come from the signal
    clone = init(tmp_path / "scratch" / "review-copy")
    git(clone, "remote", "add", "origin", f"git@github.com:{SLUG}.git")
    toml = roster(tmp_path, tmp_path / "ws", 'name = "myrepo"\nkind = "team"')
    toml.write_text(f'github_user = "{ME}"\n' + toml.read_text(encoding="utf-8"), encoding="utf-8")
    assert rk.classify(str(clone), toml)[0] == "team"


def test_a_sole_pusher_who_is_not_the_owner_is_team(rk, origin, no_toml, gh):
    mine(gh, pushers="someone-else\n")
    assert rk.classify(str(origin), no_toml)[0] == "team"


# ----------------------------------------------------- round-7 regressions --


@pytest.mark.parametrize(
    "line",
    ["### owner: team", "- owner: [team]", "<li>owner: team</li>", "owner \u2013 team",
     "\ufeff- owner: team"],
)  # fmt: skip
def test_owner_team_through_headings_brackets_html_dashes_and_bom(rk, origin, no_toml, gh, line):
    mine(gh)  # GitHub alone would say solo, so team must come from the signal
    skill_context(origin, f"{line}\n")
    assert rk.classify(str(origin), no_toml)[0] == "team"


def test_a_utf16_working_copy_still_counts(rk, origin, no_toml, gh):
    mine(gh)  # GitHub alone would say solo, so team must come from the signal
    (origin / ".claude").mkdir()
    (origin / ".claude" / "skill-context.md").write_bytes("- owner: team\n".encode("utf-16"))
    assert rk.classify(str(origin), no_toml)[0] == "team"


def test_a_team_roster_entry_wins_over_another_match(rk, origin, tmp_path, gh):
    renamed = f"{ME}/renamed"  # GitHub alone would say solo, so team must come from the roster
    gh.register(repo_query("renamed"), stdout=MINE)
    gh.register([*PUSHERS[:5], f"repos/{renamed}/collaborators", *PUSHERS[6:]], stdout=f"{ME}\n")
    gh.register([*INVITED[:5], f"repos/{renamed}/invitations", *INVITED[6:]], stdout="")
    git(origin, "remote", "set-url", "origin", f"git@github.com:{ME}/renamed.git")
    toml = tmp_path / "techne.toml"
    toml.write_text(
        f'github_user = "{ME}"\nworkspace_root = "{origin.parent}"\n\n'
        '[[sisters]]\nname = "myrepo"\n\n[[sisters]]\nname = "renamed"\nkind = "team"\n',
        encoding="utf-8",
    )
    assert rk.classify(str(origin), toml)[0] == "team"


# ----------------------------------------------------- round-8 regressions --


@pytest.mark.parametrize(
    "body",
    ["requires python <3.12\n- owner: team\nphases: setup -> lint\n",
     "x < y\n- owner: team\n> note\n", "- owner: __team__\n", "- owner:: team\n",
     "- - owner: team\n"],
    ids=["stray-angle", "angle-then-quote", "underscore-bold", "double-colon", "nested"],
)  # fmt: skip
def test_owner_team_survives_stray_markup_around_it(rk, origin, no_toml, gh, body):
    mine(gh)  # GitHub alone would say solo, so team must come from the signal
    skill_context(origin, body)
    assert rk.classify(str(origin), no_toml)[0] == "team"


@pytest.mark.parametrize(
    "line", ["- owner: teamwork", "<!-- - owner: team -->", "- ownership: team-x"]
)
def test_a_line_that_is_not_an_owner_team_line_does_not_count(rk, origin, no_toml, gh, line):
    mine(gh)
    skill_context(origin, f"{line}\n")
    assert rk.classify(str(origin), no_toml)[0] == "solo"


def test_a_utf16_owner_line_committed_but_not_in_the_working_copy_counts(rk, origin, no_toml, gh):
    mine(gh)  # GitHub alone would say solo, so team must come from the signal
    (origin / ".claude").mkdir()
    ctx = origin / ".claude" / "skill-context.md"
    ctx.write_bytes("- owner: team\n".encode("utf-16"))
    git(origin, "add", ".claude")
    git(origin, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "ctx")
    ctx.write_bytes("- name: x\n".encode("utf-16"))
    assert rk.classify(str(origin), no_toml)[0] == "team"


# ----------------------------------------------------- round-9 regressions --


@pytest.mark.parametrize(
    "line", ["<!-- note --> owner: team", "- owner: lab team", "owner: the team"]
)
def test_owner_team_after_a_closed_comment_or_with_words_between(rk, origin, no_toml, gh, line):
    mine(gh)  # GitHub alone would say solo, so team must come from the signal
    skill_context(origin, f"{line}\n")
    assert rk.classify(str(origin), no_toml)[0] == "team"


def test_an_ssh_alias_for_github_is_followed(rk, repo, no_toml, gh):
    git(repo, "remote", "add", "origin", f"git@github-work:{SLUG}.git")
    gh.register(
        ["ssh", "-G", "--", "github-work"], stdout="user git\nhostname github.com\nport 22\n"
    )
    mine(gh)
    assert rk.classify(str(repo), no_toml)[0] == "solo"


def test_an_ssh_alias_for_another_host_is_not_github(rk, repo, no_toml, gh):
    git(repo, "remote", "add", "origin", f"git@gitlab-work:{SLUG}.git")
    gh.register(["ssh", "-G", "--", "gitlab-work"], stdout="hostname gitlab.com\n")
    mine(gh)
    assert rk.classify(str(repo), no_toml) == (
        "team",
        "no GitHub origin to check ownership against",
    )


def test_any_unexpected_error_prints_team(rk, capsys, monkeypatch):
    def boom(*_args, **_kwargs):
        raise RuntimeError("Could not determine home directory.")

    monkeypatch.setattr(rk, "classify", boom)
    assert rk.main(["repo_kind.py", "."]) == 0
    assert capsys.readouterr().out.startswith("team: could not classify: RuntimeError")


def test_an_ambiguous_owner_line_fails_toward_team(rk, origin, no_toml, gh):
    """`owner: not team` reads as team: a wrong ask costs a confirmation, a wrong act does not."""
    mine(gh)
    skill_context(origin, "- owner: not team\n")
    assert rk.classify(str(origin), no_toml)[0] == "team"


# ---------------------------------------------------- round-10 regressions --


@pytest.mark.parametrize(
    "line",
    ["| **owner** | **team** |", "owner:       team", "<td><b>owner</b></td><td><b>team</b></td>",
     "owners: team", "Team owner: the lab"],
)  # fmt: skip
def test_owner_and_team_on_one_line_in_any_order_or_spacing(rk, origin, no_toml, gh, line):
    mine(gh)  # GitHub alone would say solo, so team must come from the signal
    skill_context(origin, f"{line}\n")
    assert rk.classify(str(origin), no_toml)[0] == "team"


def test_a_line_inside_a_multiline_comment_does_not_count(rk, origin, no_toml, gh):
    mine(gh)
    skill_context(origin, "<!--\n- owner: team\n-->\n")
    assert rk.classify(str(origin), no_toml)[0] == "solo"


def test_a_broken_toml_symlink_reads_as_team(rk, origin, tmp_path, gh):
    mine(gh)  # GitHub alone would say solo, so team must come from the signal
    link = tmp_path / "techne.toml"
    link.symlink_to(tmp_path / "moved-away" / "techne.toml")
    assert rk.classify(str(origin), link)[0] == "team"


def test_a_truncated_default_branch_copy_is_team(rk, origin, no_toml, gh):
    gh.register(REPO, stdout=view(object={"text": "x", "isBinary": False, "isTruncated": True}))
    gh.register(PUSHERS, stdout=f"{ME}\n")
    gh.register(INVITED, stdout="")
    assert rk.classify(str(origin), no_toml)[0] == "team"


def test_a_remote_host_starting_with_a_dash_never_reaches_ssh(rk, repo, no_toml, gh):
    git(repo, "config", "remote.origin.url", f"-oHostname=github.com:{SLUG}.git")
    gh.register(["ssh", gh.any()], stdout="hostname github.com\n", occurrences=5)
    assert rk.classify(str(repo), no_toml) == (
        "team",
        "no GitHub origin to check ownership against",
    )
    assert gh.call_count(["ssh", gh.any()]) == 0
