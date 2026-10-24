"""scripts/check_private_names.py: tracked and addable files against private repo names."""

import json
import os
import pathlib
import subprocess
import sys

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "check_private_names.py"
PRIVATE = ["secret-proj", "widgets", "a.b"]


def _git(repo: pathlib.Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: pathlib.Path) -> pathlib.Path:
    path = tmp_path / "repo"
    path.mkdir()
    _git(path, "init", "-q")
    (path / ".gitignore").write_text("ignored/\n")
    (path / "README.md").write_text("# demo\n\nNothing private here.\n")
    _git(path, "add", "-A")
    return path


def _rules(names: list[str] | None = PRIVATE) -> list[dict]:
    listing = json.dumps([{"name": n} for n in names or []])
    return [
        {"match": ["repo", "view"], "stdout": "acme\n"},
        {"match": ["repo", "list", "acme"], "stdout": listing},
    ]


def run(
    repo: pathlib.Path, gh_stub, rules: list[dict] | None = None
) -> subprocess.CompletedProcess:
    gh_stub.rules(_rules() if rules is None else rules)
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=repo,
        env=gh_stub.env,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=60,
    )


def write(repo: pathlib.Path, rel: str, text: str, add: bool = True) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    if add:
        _git(repo, "add", "--", rel)


def words_file(repo: pathlib.Path, text: str) -> None:
    (repo / ".git" / "info").mkdir(exist_ok=True)
    (repo / ".git" / "info" / "private-words").write_text(text)


def test_a_clean_repo_passes_and_says_what_it_checked(repo, gh_stub):
    result = run(repo, gh_stub)
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout and "3 private repo names" in result.stdout
    assert "OK: 2 texts" in result.stdout  # .gitignore and README.md
    # It asked for the owner's private repos, not the signed-in user's.
    assert ["repo", "list", "acme", "--visibility", "private"] == gh_stub.argvs()[1][:5]


@pytest.mark.parametrize(
    "text",
    [
        "see secret-proj for the rest\n",
        "SECRET-PROJ in capitals\n",
        "secret proj with a space\n",
        "secret_proj with an underscore\n",
        "SecretProj as a class name\n",
        "class SecretProjClient:\n",
        "newSecretProj = 1\n",
        "secret.proj, secret  proj and secretproj\n",
        "ab\n",
        "a-b\n",
        "secret-proj-v2 as a prefix\n",
        "(secret-proj)\n",
        "a.b\n",
        "acme/widgets on GitHub\n",
        "https://github.com/ACME/Widgets/pull/3\n",
        "fixed in widgets#12\n",
    ],
)
def test_a_private_name_in_a_tracked_file_fails(repo, gh_stub, text):
    write(repo, "docs/page.md", "intro\n" + text)
    result = run(repo, gh_stub)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "docs/page.md:2" in result.stdout


@pytest.mark.parametrize(
    "text",
    ["a secret-projector\n", "mysecret-proj\n", "axb\n", "secretprojects\n", "SecretProjector\n"],
)
def test_a_longer_word_or_a_near_miss_passes(repo, gh_stub, text):
    write(repo, "docs/page.md", text)
    result = run(repo, gh_stub)
    assert result.returncode == 0, result.stdout + result.stderr


def test_a_listed_word_passes_as_prose_and_fails_as_a_repo_reference(repo, gh_stub):
    words_file(repo, "# names that are ordinary words\n\nWidgets\nnot-a-repo\n")
    write(repo, "docs/page.md", "Two widgets and a widgets-style monorepo.\n")
    assert run(repo, gh_stub).returncode == 0
    write(repo, "docs/ref.md", "moved to acme/widgets\n")
    result = run(repo, gh_stub)
    assert result.returncode == 1
    assert "docs/ref.md:1" in result.stdout and "docs/page.md" not in result.stdout


@pytest.mark.parametrize(
    "text",
    [
        "acme/widgets-site\n",
        "acme/widgets.site\n",
        "other/widgets#3\n",
        "foo-widgets#12\n",
        "acme/widgetsy\n",
        "notacme/widgets\n",
        "foo-acme/widgets\n",
        "see widgets#readme\n",
    ],
)
def test_a_listed_word_inside_another_slug_passes(repo, gh_stub, text):
    words_file(repo, "widgets\n")
    write(repo, "docs/page.md", text)
    result = run(repo, gh_stub)
    assert result.returncode == 0, result.stdout


def test_the_words_file_matches_any_spelling_of_a_name(repo, gh_stub):
    words_file(repo, "Secret Proj\n")
    write(repo, "docs/page.md", "a secret proj in prose\n")
    assert run(repo, gh_stub).returncode == 0
    write(repo, "docs/ref.md", "acme/secret-proj\n")
    assert run(repo, gh_stub).returncode == 1


def test_a_longer_name_is_reported_as_itself(repo, gh_stub):
    write(repo, "docs/page.md", "see foo-bar\n")
    result = run(repo, gh_stub, _rules(["foo", "foo-bar"]))
    assert result.returncode == 1
    assert "'foo-bar'" in result.stdout and "'foo'" not in result.stdout


def test_staged_content_is_scanned_when_the_working_tree_differs(repo, gh_stub):
    write(repo, "docs/page.md", "acme/secret-proj\n")
    (repo / "docs" / "page.md").write_text("clean\n")  # edited, not staged
    assert run(repo, gh_stub).returncode == 1
    (repo / "docs" / "page.md").unlink()  # deleted, not staged
    result = run(repo, gh_stub)
    assert result.returncode == 1 and "docs/page.md:1" in result.stdout


def test_an_unstaged_edit_is_scanned(repo, gh_stub):
    (repo / "README.md").write_text("# demo\n\nsee secret-proj\n")
    result = run(repo, gh_stub)
    assert result.returncode == 1 and "README.md:3" in result.stdout


def test_line_numbers_count_newlines_only(repo, gh_stub):
    write(repo, "LICENSE", "terms\x0cmore\rterms\u2028x\nsecret-proj\n")
    result = run(repo, gh_stub)
    assert "LICENSE:2" in result.stdout, result.stdout


def test_an_unlisted_word_fails_and_the_message_names_the_words_file(repo, gh_stub):
    write(repo, "docs/page.md", "Two widgets.\n")
    result = run(repo, gh_stub)
    assert result.returncode == 1
    assert "info/private-words" in result.stdout


def test_the_words_file_is_shared_by_every_worktree(repo, gh_stub, tmp_path):
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x"],
        check=True,
    )
    words_file(repo, "widgets\n")
    tree = tmp_path / "wt"
    _git(repo, "worktree", "add", "-q", str(tree))
    write(tree, "page.md", "Two widgets.\n")
    assert run(tree, gh_stub).returncode == 0


def test_a_file_name_is_scanned(repo, gh_stub):
    write(repo, "notes/secret-proj.md", "nothing\n")
    result = run(repo, gh_stub)
    assert result.returncode == 1
    assert "notes/secret-proj.md" in result.stdout


def test_an_untracked_file_is_scanned_and_an_ignored_one_is_not(repo, gh_stub):
    write(repo, "ignored/x.md", "secret-proj\n", add=False)
    assert run(repo, gh_stub).returncode == 0
    write(repo, "new.md", "secret-proj\n", add=False)
    assert run(repo, gh_stub).returncode == 1


def test_a_symlink_is_checked_by_its_target_not_followed(repo, gh_stub, tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text("secret-proj\n")
    os.symlink(outside, repo / "link.md")
    _git(repo, "add", "link.md")
    assert run(repo, gh_stub).returncode == 0
    os.symlink("secret-proj/x", repo / "link2")
    _git(repo, "add", "link2")
    assert run(repo, gh_stub).returncode == 1


def test_odd_files_do_not_stop_the_scan(repo, gh_stub):
    (repo / "bin.dat").write_bytes(b"\x00\x01secret-proj")
    write(repo, "gone.md", "x\n")
    (repo / "gone.md").unlink()
    (repo / "latin1.txt").write_bytes("caf\xe9 secret-proj\n".encode("latin-1"))
    (repo / os.fsdecode(b"odd\xff.md")).write_text("clean\n")
    _git(repo, "add", "-A")
    result = run(repo, gh_stub)
    # The binary file is skipped; the latin-1 one is still read.
    assert result.returncode == 1
    assert "latin1.txt:1" in result.stdout and "bin.dat" not in result.stdout


def test_output_is_sorted(repo, gh_stub):
    for name in ["z.md", "a.md", "m.md"]:
        write(repo, name, "secret-proj\n")
    write(repo, "b.md", "x\n" * 8 + "secret-proj\n" * 2)
    lines = [ln.strip() for ln in run(repo, gh_stub).stdout.splitlines() if ".md:" in ln]
    # By path, then by line number as a number: line 9 before line 10.
    assert lines == ["a.md:1", "b.md:9", "b.md:10", "m.md:1", "z.md:1"]


def test_no_gh_skips_loudly(repo, gh_stub):
    env = {**gh_stub.env, "PATH": "/nonexistent"}
    result = subprocess.run(
        [sys.executable, str(SCRIPT)], cwd=repo, env=env, capture_output=True, text=True
    )
    assert result.returncode == 0
    assert "SKIP" in result.stderr and "gh" in result.stderr


def test_signed_out_skips_loudly(repo, gh_stub):
    rules = [
        {
            "match": ["repo"],
            "stderr": "To get started with GitHub CLI, please run:  gh auth login\n",
            "exit": 4,
        }
    ]
    result = run(repo, gh_stub, rules)
    assert result.returncode == 0
    assert "SKIP" in result.stderr and "signed in" in result.stderr


def test_no_visible_private_repo_skips_loudly(repo, gh_stub):
    result = run(repo, gh_stub, _rules([]))
    assert result.returncode == 0
    assert "SKIP" in result.stderr and "no private repo" in result.stderr


@pytest.mark.parametrize("failing", ["view", "list"])
def test_gh_unable_to_list_skips_with_its_reason(repo, gh_stub, failing):
    # Offline, an outage, or a remote gh cannot resolve.
    failure = {"match": ["repo", failing], "stderr": "error connecting to github\n", "exit": 1}
    result = run(repo, gh_stub, [failure, *_rules()])
    assert result.returncode == 0
    assert "SKIP" in result.stderr and "error connecting to github" in result.stderr


def test_a_listing_that_is_not_json_fails(repo, gh_stub):
    rules = [
        {"match": ["repo", "view"], "stdout": "acme\n"},
        {"match": ["repo", "list"], "stdout": "<html>"},
    ]
    result = run(repo, gh_stub, rules)
    assert result.returncode == 2 and "FAIL" in result.stderr


def test_outside_a_git_repo_fails(tmp_path, gh_stub):
    result = run(tmp_path, gh_stub)
    assert result.returncode == 2
    assert "git" in result.stderr


def test_a_commented_line_in_the_words_file_is_not_a_word(repo, gh_stub):
    words_file(repo, "# secret-proj\n")
    write(repo, "docs/page.md", "see secret-proj\n")
    assert run(repo, gh_stub).returncode == 1


def test_the_prefilter_holds_every_name_the_scan_matches(repo, gh_stub):
    # A name the prefilter missed would pass silently: every match must survive it.
    words_file(repo, "widgets\n")
    write(repo, "a.md", "x\n" * 5000 + "SecretProjClient and acme/widgets.git\n")
    result = run(repo, gh_stub)
    assert result.returncode == 1
    assert "a.md:5001" in result.stdout and "'widgets'" in result.stdout


@pytest.mark.parametrize(
    "text", ["moved to acme/widgets.\n", "git clone git@github.com:acme/widgets.git\n"]
)
def test_a_listed_word_ending_a_sentence_or_a_clone_url_fails(repo, gh_stub, text):
    words_file(repo, "widgets\n")
    write(repo, "docs/page.md", text)
    assert run(repo, gh_stub).returncode == 1


def test_a_camel_case_name_matches_its_parts(repo, gh_stub):
    write(repo, "docs/page.md", "see my-repo\n")
    result = run(repo, gh_stub, _rules(["MyRepo"]))
    assert result.returncode == 1 and "'MyRepo'" in result.stdout


def test_a_utf16_file_is_read(repo, gh_stub):
    (repo / "notes.txt").write_bytes("see secret-proj\r\n".encode("utf-16"))
    _git(repo, "add", "notes.txt")
    result = run(repo, gh_stub)
    assert result.returncode == 1 and "notes.txt:1" in result.stdout


@pytest.mark.parametrize("bad", ["latin-1", "folder"])
def test_an_unreadable_words_file_fails(repo, gh_stub, bad):
    target = repo / ".git" / "info" / "private-words"
    target.parent.mkdir(exist_ok=True)
    if bad == "folder":
        target.mkdir()
    else:
        target.write_bytes("caf\xe9\n".encode("latin-1"))
    result = run(repo, gh_stub)
    assert result.returncode == 2 and "FAIL" in result.stderr


def test_a_submodule_entry_is_skipped(repo, gh_stub):
    sha = "0" * 39 + "1"
    _git(repo, "update-index", "--add", "--cacheinfo", f"160000,{sha},vendor/lib")
    result = run(repo, gh_stub)
    assert result.returncode == 0, result.stdout + result.stderr


def commit(repo: pathlib.Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", message)


def test_an_unpushed_commit_is_scanned_after_the_name_is_removed(repo, gh_stub):
    write(repo, "docs/page.md", "acme/secret-proj\n")
    commit(repo, "add")
    (repo / "docs" / "page.md").write_text("clean\n")
    commit(repo, "remove")
    result = run(repo, gh_stub)
    assert result.returncode == 1
    assert "docs/page.md (an unpushed commit):1" in result.stdout


def test_a_commit_message_and_a_branch_name_are_scanned(repo, gh_stub):
    commit(repo, "init")
    _git(repo, "checkout", "-q", "-b", "feat/secret-proj")
    result = run(repo, gh_stub)
    assert result.returncode == 1 and "branch feat/secret-proj: in its name" in result.stdout
    _git(repo, "checkout", "-q", "-b", "feat/other")
    _git(
        repo,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@t",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "fix",
        "-m",
        "port the secret-proj loader",
    )
    result = run(repo, gh_stub)
    assert result.returncode == 1 and "message:3" in result.stdout


def test_pushed_history_is_not_scanned(repo, gh_stub, tmp_path):
    write(repo, "docs/page.md", "acme/secret-proj\n")
    commit(repo, "add")
    (repo / "docs" / "page.md").write_text("clean\n")
    commit(repo, "drop the secret-proj page")
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "push", "-q", "origin", "HEAD:main")
    _git(repo, "fetch", "-q", "origin")
    result = run(repo, gh_stub)
    assert result.returncode == 0, result.stdout


def test_a_renamed_file_name_in_an_unpushed_commit_is_scanned(repo, gh_stub):
    write(repo, "docs/secret-proj-notes.md", "clean\n")
    commit(repo, "add")
    _git(repo, "mv", "docs/secret-proj-notes.md", "docs/notes.md")
    commit(repo, "rename")
    result = run(repo, gh_stub)
    assert result.returncode == 1
    assert "docs/secret-proj-notes.md (an unpushed commit): in its name" in result.stdout


def test_a_deleted_empty_file_name_in_an_unpushed_commit_is_scanned(repo, gh_stub, tmp_path):
    # The remote already has the empty blob, so only the commit's path list names the file.
    write(repo, "__init__.py", "")
    commit(repo, "base")
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "push", "-q", "origin", "HEAD:main")
    _git(repo, "fetch", "-q", "origin")
    write(repo, "secret_proj_stub.py", "")
    commit(repo, "add")
    (repo / "secret_proj_stub.py").unlink()
    commit(repo, "remove")
    result = run(repo, gh_stub)
    assert result.returncode == 1 and "secret_proj_stub.py (an unpushed commit)" in result.stdout


def test_a_listed_word_as_an_issue_reference_fails(repo, gh_stub):
    words_file(repo, "widgets\n")
    write(repo, "docs/page.md", "intro\nfixed in widgets#12\n")
    result = run(repo, gh_stub)
    assert result.returncode == 1 and "docs/page.md:2" in result.stdout


def test_a_name_wrapped_across_two_lines_fails_at_its_first_line(repo, gh_stub):
    write(repo, "docs/page.md", "intro\nmoved to the Secret\n  Proj repo\n")
    result = run(repo, gh_stub)
    assert result.returncode == 1 and "docs/page.md:2" in result.stdout
