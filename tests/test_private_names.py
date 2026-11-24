"""scripts/check_private_names.py: tracked and addable files against private repo names."""

import json
import os
import pathlib
import shutil
import subprocess
import sys
import time

import pytest
from conftest import HOOK_PYTHON, load_phylax_hooks

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
        {"match": ["api", "user"], "stdout": "acme\n"},  # the owner's own login
    ]


def run(
    repo: pathlib.Path,
    gh_stub,
    rules: list[dict] | None = None,
    args: tuple[str, ...] = (),
    stdin: str | None = None,
) -> subprocess.CompletedProcess:
    gh_stub.rules(_rules() if rules is None else rules)
    return subprocess.run(
        [HOOK_PYTHON, str(SCRIPT), *args],
        cwd=repo,
        env=gh_stub.env,
        input=stdin,
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
        [HOOK_PYTHON, str(SCRIPT)], cwd=repo, env=env, capture_output=True, text=True
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


# --- push mode: only what a push sends -------------------------------------------------------

HOOK = SCRIPT.parent / "git-hooks" / "pre-push"
INSTALL = SCRIPT.parent / "install_git_hooks.sh"


def published(repo: pathlib.Path, tmp_path: pathlib.Path) -> pathlib.Path:
    """REPO with one clean commit on main, pushed to a bare origin."""
    _git(repo, "checkout", "-q", "-b", "main")
    commit(repo, "init")
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "push", "-q", "origin", "main")
    return remote


def leak_on(repo: pathlib.Path, branch: str) -> None:
    """A commit naming a private repo on BRANCH; HEAD goes back to a clean main."""
    _git(repo, "checkout", "-q", "-b", branch)
    write(repo, "docs/leak.md", "see acme/secret-proj\n")
    commit(repo, "add notes")
    _git(repo, "checkout", "-q", "main")


def test_push_mode_scans_the_pushed_branch_not_head(repo, gh_stub, tmp_path):
    published(repo, tmp_path)
    leak_on(repo, "feature")
    assert run(repo, gh_stub).returncode == 0  # the default scan reads HEAD: the old gap
    result = run(repo, gh_stub, args=("--push", "feature"))
    assert result.returncode == 1 and "docs/leak.md (a pushed commit):1" in result.stdout
    assert run(repo, gh_stub, args=("--push", "HEAD")).returncode == 0


@pytest.mark.parametrize("rev", ["--branches", "--all", "--glob=refs/heads/feat*"])
def test_push_mode_follows_rev_list_selectors(repo, gh_stub, tmp_path, rev):
    published(repo, tmp_path)
    leak_on(repo, "feature")
    assert run(repo, gh_stub, args=("--push", rev)).returncode == 1


def test_an_annotated_tag_message_and_a_tag_name_are_scanned(repo, gh_stub, tmp_path):
    published(repo, tmp_path)
    tag = ["-c", "user.name=t", "-c", "user.email=t@t", "tag", "-a"]
    _git(repo, *tag, "v1", "-m", "ports the secret-proj loader")
    result = run(repo, gh_stub, args=("--push", "--tags"))
    assert result.returncode == 1 and "tag v1:6" in result.stdout  # after its 5 header lines
    _git(repo, "tag", "-d", "v1")
    _git(repo, "tag", "secret-proj-v2")
    result = run(repo, gh_stub, args=("--push", "--tags"))
    assert result.returncode == 1 and "ref refs/tags/secret-proj-v2: in its name" in result.stdout


def test_push_mode_leaves_out_the_index_and_untracked_files(repo, gh_stub, tmp_path):
    published(repo, tmp_path)
    write(repo, "notes/todo.md", "acme/secret-proj\n", add=False)
    write(repo, "staged.md", "acme/secret-proj\n")
    assert run(repo, gh_stub).returncode == 1
    assert run(repo, gh_stub, args=("--push", "HEAD")).returncode == 0


def test_a_pushed_ref_name_is_scanned(repo, gh_stub, tmp_path):
    published(repo, tmp_path)
    result = run(repo, gh_stub, args=("--push", "HEAD", "--ref", "refs/heads/secret-proj-fix"))
    assert result.returncode == 1 and "ref refs/heads/secret-proj-fix: in its name" in result.stdout


def test_the_pre_push_mode_reads_gits_ref_lines(repo, gh_stub, tmp_path):
    published(repo, tmp_path)
    leak_on(repo, "feature")
    sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "feature"], capture_output=True, text=True
    ).stdout.strip()
    zero = "0" * 40
    line = f"refs/heads/feature {sha} refs/heads/feature {zero}\n"
    result = run(repo, gh_stub, args=("--pre-push", "origin", "url"), stdin=line)
    assert result.returncode == 1 and "docs/leak.md (a pushed commit)" in result.stdout
    delete = f"(delete) {zero} refs/heads/secret-proj {sha}\n"
    assert run(repo, gh_stub, args=("--pre-push", "o", "u"), stdin=delete).returncode == 0
    bad = run(repo, gh_stub, args=("--pre-push", "o", "u"), stdin="not four fields\n")
    assert bad.returncode == 2 and "unexpected pre-push line" in bad.stderr


def test_an_unknown_argument_fails(repo, gh_stub):
    result = run(repo, gh_stub, args=("--pushh",))
    assert result.returncode == 2 and "unknown argument" in result.stderr


def test_paired_refuses_unequal_lengths():
    sys.path.insert(0, str(SCRIPT.parent))
    try:
        import check_private_names as cpn  # ty: ignore[import-not-found]
    finally:
        sys.path.remove(str(SCRIPT.parent))
    assert cpn.paired([1, 2], ["a", "b"]) == [(1, "a"), (2, "b")]
    with pytest.raises(RuntimeError, match="2 records for 3 objects"):
        cpn.paired([1, 2, 3], ["a", "b"])


# --- the pre-push hook through a real `git push` --------------------------------------------


def ship_scanner(repo: pathlib.Path) -> None:
    (repo / "scripts" / "git-hooks").mkdir(parents=True, exist_ok=True)
    shutil.copy2(SCRIPT, repo / "scripts" / "check_private_names.py")
    shutil.copy2(HOOK, repo / "scripts" / "git-hooks" / "pre-push")
    shutil.copy2(INSTALL, repo / "scripts" / "install_git_hooks.sh")


def install(repo: pathlib.Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "scripts/install_git_hooks.sh"], cwd=repo, capture_output=True, text=True
    )


def push(
    repo: pathlib.Path, gh_stub, *args: str, before: tuple[str, ...] = ()
) -> subprocess.CompletedProcess:
    """`git BEFORE... push ARGS...` in REPO, with the fake gh and the guard's python3 first."""
    gh_stub.rules(_rules())
    env = {**gh_stub.env, "PATH": f"{pathlib.Path(HOOK_PYTHON).parent}:{gh_stub.env['PATH']}"}
    return subprocess.run(
        ["git", *before, "push", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


def test_the_hook_refuses_a_push_of_a_leaking_branch_while_head_is_clean(repo, gh_stub, tmp_path):
    ship_scanner(repo)  # on the remote before the test, as in a real clone
    published(repo, tmp_path)
    assert install(repo).returncode == 0
    leak_on(repo, "feature")
    refused = push(repo, gh_stub, "origin", "feature")
    assert refused.returncode != 0 and "secret-proj" in refused.stdout + refused.stderr
    assert push(repo, gh_stub, "origin", "main").returncode == 0


def test_the_hook_lets_a_deletion_through(repo, gh_stub, tmp_path):
    ship_scanner(repo)  # on the remote before the test, as in a real clone
    published(repo, tmp_path)
    assert install(repo).returncode == 0
    _git(repo, "push", "-q", "--no-verify", "origin", "main:secret-proj-old")
    assert push(repo, gh_stub, "origin", "--delete", "secret-proj-old").returncode == 0


def test_the_hook_refuses_when_the_repo_no_longer_has_the_scanner(repo, gh_stub, tmp_path):
    published(repo, tmp_path)
    hooks = repo / ".git" / "hooks"
    hooks.mkdir(exist_ok=True)
    shutil.copy2(HOOK, hooks / "pre-push")
    leak_on(repo, "feature")
    refused = push(repo, gh_stub, "origin", "feature")
    assert refused.returncode != 0 and "neither the work tree nor HEAD" in refused.stderr


def test_the_installer_keeps_a_foreign_hook_and_an_outside_hooks_path(repo, tmp_path):
    ship_scanner(repo)
    hooks = repo / ".git" / "hooks"
    hooks.mkdir(exist_ok=True)
    (hooks / "pre-push").write_text("#!/bin/sh\necho mine\n")
    result = install(repo)
    assert result.returncode == 0 and "is not techne's" in result.stderr
    assert (hooks / "pre-push").read_text() == "#!/bin/sh\necho mine\n"
    (hooks / "pre-push").unlink()
    assert install(repo).returncode == 0
    assert (hooks / "pre-push").read_text() == HOOK.read_text()
    assert os.access(hooks / "pre-push", os.X_OK)
    assert install(repo).returncode == 0  # its own hook is replaced, not refused
    for hooks_path in (tmp_path / "shared-hooks", repo / ".githooks"):  # outside or in the tree
        _git(repo, "config", "core.hooksPath", str(hooks_path))
        result = install(repo)
        assert result.returncode == 0 and "core.hooksPath is" in result.stderr
        assert not hooks_path.exists()
    _git(repo, "config", "--unset", "core.hooksPath")
    (hooks / "pre-push").unlink()
    (hooks / "pre-push").symlink_to(tmp_path / "gone")  # dangling: not techne's either
    assert "is not techne's" in install(repo).stderr
    assert (hooks / "pre-push").is_symlink()


def test_the_installer_skips_outside_a_git_repo(tmp_path):
    result = subprocess.run(["bash", str(INSTALL)], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0 and "not in a git repo" in result.stderr


def test_the_installer_reaches_the_shared_hooks_from_a_worktree(repo, tmp_path):
    ship_scanner(repo)
    published(repo, tmp_path)
    wt = tmp_path / "wt"
    _git(repo, "worktree", "add", "-q", str(wt), "-b", "w")
    result = subprocess.run(
        ["bash", "scripts/install_git_hooks.sh"], cwd=wt, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert (repo / ".git" / "hooks" / "pre-push").read_text() == HOOK.read_text()


def test_a_push_of_a_branch_named_like_a_private_repo_is_refused_by_the_hook(
    repo, gh_stub, tmp_path
):
    ship_scanner(repo)
    published(repo, tmp_path)
    assert install(repo).returncode == 0
    _git(repo, "checkout", "-q", "-b", "secret-proj-fix")  # clean content, private name
    for args in (("-u", "origin", "HEAD"), ("origin", "secret-proj-fix:other")):
        refused = push(repo, gh_stub, *args)
        assert refused.returncode != 0 and "secret-proj-fix" in refused.stdout, args
    refused = push(repo, gh_stub, "origin", "HEAD:refs/heads/secret-proj-x")
    assert refused.returncode != 0 and "refs/heads/secret-proj-x" in refused.stdout


def test_follow_tags_sends_a_tag_the_hook_scans(repo, gh_stub, tmp_path):
    ship_scanner(repo)
    published(repo, tmp_path)
    assert install(repo).returncode == 0
    tag = ["-c", "user.name=t", "-c", "user.email=t@t", "tag", "-a", "v1", "-m"]
    _git(repo, *tag, "ports the secret-proj loader")
    write(repo, "next.md", "next\n")
    commit(repo, "next")
    refused = push(repo, gh_stub, "--follow-tags", "origin", "main")
    assert refused.returncode != 0 and "tag v1" in refused.stdout


def test_a_commit_another_remote_holds_is_still_scanned_for_this_one(repo, gh_stub, tmp_path):
    ship_scanner(repo)
    published(repo, tmp_path)
    assert install(repo).returncode == 0
    leak_on(repo, "feature")
    backup = tmp_path / "backup.git"
    subprocess.run(["git", "init", "-q", "--bare", str(backup)], check=True)
    _git(repo, "remote", "add", "backup", str(backup))
    _git(repo, "push", "-q", "--no-verify", "backup", "feature")
    refused = push(repo, gh_stub, "origin", "feature")
    assert refused.returncode != 0 and "docs/leak.md" in refused.stdout


def test_push_mode_scans_a_named_ref(repo, gh_stub, tmp_path):
    published(repo, tmp_path)
    _git(repo, "branch", "secret-proj-fix")
    result = run(repo, gh_stub, args=("--push", "secret-proj-fix"))
    assert result.returncode == 1 and "ref secret-proj-fix: in its name" in result.stdout


# --- phylax's push check: the hook must run ------------------------------------------------

GUARDS = SCRIPT.parents[1] / "plugins" / "phylax" / "hooks" / "git_guards.py"


def guard(cwd: pathlib.Path, command: str, env: dict | None = None):
    """(decision, reason) phylax gives COMMAND run in CWD: "deny" or None."""
    environ = {
        **os.environ,
        "CLAUDE_PLUGIN_OPTION_BLOCK_COMMITS_MD": "true",
        "XDG_STATE_HOME": str(cwd.parent / "state"),
        **(env or {}),
    }
    payload = json.dumps({"session_id": "s1", "cwd": str(cwd), "tool_input": {"command": command}})
    proc = subprocess.run(
        [HOOK_PYTHON, str(GUARDS)], input=payload, capture_output=True, text=True, env=environ
    )
    assert proc.returncode == 0, proc.stderr
    if not proc.stdout.strip():
        return None, ""
    out = json.loads(proc.stdout)["hookSpecificOutput"]
    return out.get("permissionDecision"), out.get("permissionDecisionReason", "")


@pytest.fixture
def hooked(repo, tmp_path):
    """A published repo that ships the scanner, with its pre-push hook installed."""
    ship_scanner(repo)
    published(repo, tmp_path)
    assert install(repo).returncode == 0
    return repo


@pytest.mark.parametrize(
    "command",
    [
        "git push origin main",
        "git push",
        "git push --no-verify --verify origin main",  # the last one wins
        "git push --dry-run origin main",
        "git push origin -- --no-verify",  # after --, a ref name
    ],
)
def test_a_push_that_runs_the_hook_is_let_through(hooked, command):
    assert guard(hooked, command) == (None, "")


@pytest.mark.parametrize(
    ("command", "env", "says"),
    [
        ("git push --no-verify origin main", None, "--no-verify skips"),
        ("git push --verify --no-verify", None, "--no-verify skips"),
        ("git -c core.hooksPath=/dev/null push", None, "without techne's pre-push hook"),
        ("git -c CORE.HOOKSPATH=x push", None, "without techne's pre-push hook"),
        ("git --config-env=core.hooksPath=H push", {"H": "/x"}, "without techne's pre-push hook"),
        ("git --config-env core.hooksPath=H push", {"H": "/x"}, "without techne's pre-push hook"),
        ("git -c alias.p='push --no-verify' p origin main", None, "--no-verify skips"),
        ("HOME=$OTHER git push", None, "cannot read"),
        (
            "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.hooksPath GIT_CONFIG_VALUE_0=/x git push",
            None,
            "without techne's pre-push hook",
        ),
        (
            "git push",
            {"GIT_CONFIG_PARAMETERS": "'core.hooksPath'='/dev/null'"},
            "without techne's pre-push hook",
        ),
        ("git config core.hooksPath /x && git push origin main", None, "same call"),
        ("chmod -x .git/hooks/pre-push && git push origin main", None, "same call"),
    ],
)
def test_a_push_that_skips_the_hook_is_refused(hooked, command, env, says):
    decision, reason = guard(hooked, command, env)
    assert decision == "deny" and (says in reason or "/dev or /proc" in reason), reason


def test_a_missing_or_foreign_hook_is_refused_with_the_fix(hooked):
    hook = hooked / ".git" / "hooks" / "pre-push"
    hook.unlink()
    decision, reason = guard(hooked, "git push origin main")
    assert decision == "deny" and "install_git_hooks.sh" in reason
    hook.write_text("#!/bin/sh\nexit 0\n")
    hook.chmod(0o755)
    assert guard(hooked, "git push origin main")[0] == "deny"
    hook.write_text('#!/bin/sh\nexec scripts/git-hooks/pre-push "$@"\n')  # chained: fine
    assert guard(hooked, "git push origin main") == (None, "")
    hook.chmod(0o644)  # not executable: git skips it
    assert guard(hooked, "git push origin main")[0] == "deny"


def test_a_push_into_a_folder_made_in_the_same_command_is_refused(hooked, tmp_path):
    wt = tmp_path / "wt"
    for command in (
        f"git worktree add -q {wt} -b x && git -C {wt} push origin x",
        f"git clone -q {hooked} {wt} && cd {wt} && git push",
    ):
        decision, reason = guard(hooked, command)
        assert decision == "deny" and "does not exist yet" in reason, command


def test_a_repo_without_the_scanner_is_left_alone(repo, tmp_path):
    published(repo, tmp_path)
    assert guard(repo, "git push --no-verify origin main") == (None, "")


def test_phylax_runs_none_of_the_repos_code(hooked, tmp_path):
    marker = tmp_path / "ran"
    (hooked / "scripts" / "check_private_names.py").write_text(f"open({str(marker)!r}, 'w')\n")
    guard(hooked, "git push origin main")
    assert not marker.exists()


def test_the_refusal_is_logged_under_its_own_name(hooked):
    guard(hooked, "git push --no-verify origin main")
    log = hooked.parent / "state" / "phylax" / "denied-calls.jsonl"
    (row,) = [json.loads(line) for line in log.read_text().splitlines()]
    assert row["guard"] == "private_repo_names"


def test_the_hook_reads_the_scanner_from_head_when_the_work_tree_is_elsewhere(
    repo, gh_stub, tmp_path
):
    ship_scanner(repo)
    published(repo, tmp_path)
    assert install(repo).returncode == 0
    leak_on(repo, "feature")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    refused = push(repo, gh_stub, "origin", "feature", before=(f"--work-tree={elsewhere}",))
    assert refused.returncode != 0 and "docs/leak.md" in refused.stdout, refused.stderr


def test_a_push_to_a_url_scans_what_another_remote_holds(repo, gh_stub, tmp_path):
    ship_scanner(repo)
    remote = published(repo, tmp_path)
    assert install(repo).returncode == 0
    leak_on(repo, "feature")
    backup = tmp_path / "backup.git"
    subprocess.run(["git", "init", "-q", "--bare", str(backup)], check=True)
    _git(repo, "remote", "add", "backup", str(backup))
    _git(repo, "push", "-q", "--no-verify", "backup", "feature")
    refused = push(repo, gh_stub, str(remote), "feature")  # origin's URL: origin's refs only
    assert refused.returncode != 0 and "docs/leak.md" in refused.stdout
    other = tmp_path / "other.git"
    subprocess.run(["git", "init", "-q", "--bare", str(other)], check=True)
    refused = push(repo, gh_stub, str(other), "feature")  # no remote has this URL: all history
    assert refused.returncode != 0 and "docs/leak.md" in refused.stdout


def test_a_config_file_from_the_environment_that_moves_the_hooks_is_refused(hooked, tmp_path):
    cfg = tmp_path / "g.cfg"
    cfg.write_text("[core]\n\thooksPath = /nonexistent\n")
    decision, reason = guard(hooked, f"GIT_CONFIG_GLOBAL={cfg} git push origin main")
    assert decision == "deny" and "without techne's pre-push hook" in reason
    cfg.write_text("[user]\n\tname = x\n")  # a config that leaves the hooks alone
    assert guard(hooked, f"GIT_CONFIG_GLOBAL={cfg} git push origin main") == (None, "")


def test_a_bare_clone_with_the_hook_is_held_to_it(hooked, tmp_path):
    bare = tmp_path / "bare.git"
    _git(hooked, "clone", "-q", "--bare", str(hooked), str(bare))
    shutil.copy2(HOOK, bare / "hooks" / "pre-push")
    decision, reason = guard(bare, "git push --no-verify origin main")
    assert decision == "deny" and "--no-verify skips" in reason


def test_a_read_only_command_before_the_push_does_not_hold_it(hooked):
    for command in (
        "git status && git push origin main",
        "git commit -qm 'update config' --allow-empty && git push origin main",
    ):
        assert guard(hooked, command) == (None, ""), command


def test_a_git_config_write_before_the_push_holds_it(hooked, tmp_path):
    cfg = tmp_path / "inc.cfg"
    cfg.write_text("[core]\n\thooksPath = /nonexistent\n")
    decision, reason = guard(hooked, f"git config include.path {cfg} && git push origin main")
    assert decision == "deny" and "same call" in reason


def test_a_push_by_url_leaves_out_what_that_remote_already_has(repo, gh_stub, tmp_path):
    ship_scanner(repo)
    remote = published(repo, tmp_path)
    assert install(repo).returncode == 0
    leak_on(repo, "feature")
    _git(repo, "push", "-q", "--no-verify", "origin", "feature")  # already public there
    _git(repo, "fetch", "-q", "origin")
    assert push(repo, gh_stub, str(remote), "feature:again").returncode == 0


@pytest.mark.parametrize(
    "command",
    [
        "git commit -qm 'docs: webhook notes' --allow-empty && git push origin main",
        "git commit -qm 'fix(hooks): x' --allow-empty && git push origin main",
        "git checkout -qb fix/hook-order && git push -u origin fix/hook-order",
        "true test-hooks-oldest && git push origin main",
        "ls tests/test_git_hooks.py; git push origin main",
        "git config --get user.name; git push origin main",
        "git config get user.name; git push origin main",
        "cat .git/config && git push origin main",
    ],
)
def test_ordinary_work_before_a_push_does_not_hold_it(hooked, command):
    assert guard(hooked, command) == (None, ""), command


@pytest.mark.parametrize(
    "command",
    [
        "printf '[include]\\n\\tpath = /x\\n' >> .git/config && git push origin main",
        "cp /dev/null .git/h*/pre-push && git push origin main",
        "rm .git/hooks/pre-push; git push origin main",
        "ln -sf /bin/true .git/hooks/pre-push && git push origin main",
        "git config --global include.path /x && git push origin main",
        "export X=1; echo core.hooksPath; git push origin main",
    ],
)
def test_a_change_to_config_or_hooks_in_the_same_call_holds_the_push(hooked, command):
    decision, reason = guard(hooked, command)
    assert decision == "deny" and "same call" in reason, command


def alias_file(tmp_path: pathlib.Path, home: bool = False) -> pathlib.Path:
    path = tmp_path / ("home/.gitconfig" if home else "g.cfg")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[alias]\n\tp = push --no-verify\n")
    return path


@pytest.mark.parametrize("source", ["global", "home", "count", "config-env"])
def test_an_alias_from_any_config_source_is_resolved_before_the_push_check(
    hooked, tmp_path, source
):
    if source == "global":
        command = f"GIT_CONFIG_GLOBAL={alias_file(tmp_path)} git p origin main"
    elif source == "home":
        command = f"HOME={alias_file(tmp_path, home=True).parent} git p origin main"
    elif source == "count":
        count = "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=alias.p GIT_CONFIG_VALUE_0=push"
        command = f"{count} git p --no-verify origin main"
    else:
        command = "git --config-env=alias.p=A p --no-verify origin main"
    env = {"A": "push"} if source == "config-env" else None
    decision, reason = guard(hooked, command, env)
    assert decision == "deny" and "--no-verify skips" in reason, (source, reason)


def test_git_dir_names_the_repo_from_anywhere(hooked, tmp_path):
    away = tmp_path / "away"
    away.mkdir()
    for command in (
        f"GIT_DIR={hooked}/.git git push --no-verify origin main",
        f"export GIT_DIR={hooked}/.git; git push --no-verify origin main",
    ):
        decision, reason = guard(away, command)
        assert decision == "deny" and "--no-verify skips" in reason, command


def test_a_flag_held_in_a_variable_is_read(hooked):
    decision, reason = guard(hooked, "NV=--no-verify; git push $NV origin main")
    assert decision == "deny" and "--no-verify skips" in reason
    decision, reason = guard(hooked, "git push $(printf -- --no-verify) origin main")
    assert decision == "deny" and "cannot read" in reason


def test_phylax_s_own_git_writes_no_trace_file(hooked, tmp_path):
    trace = tmp_path / "trace.log"
    guard(hooked, f"GIT_TRACE={trace} GIT_TRACE2_EVENT={trace} git push origin main")
    assert not trace.exists()


def test_two_remotes_with_one_url_mean_a_full_scan(repo, gh_stub, tmp_path):
    ship_scanner(repo)
    remote = published(repo, tmp_path)
    assert install(repo).returncode == 0
    leak_on(repo, "feature")
    _git(repo, "push", "-q", "--no-verify", "origin", "feature")
    _git(repo, "fetch", "-q", "origin")
    _git(repo, "remote", "add", "twin", str(remote))  # same URL, so the URL names no one remote
    refused = push(repo, gh_stub, str(remote), "feature:again")
    assert refused.returncode != 0 and "docs/leak.md" in refused.stdout


def test_a_user_git_config_written_in_the_same_call_holds_the_push(hooked, tmp_path):
    decision, reason = guard(hooked, f"printf '' >> {tmp_path}/.gitconfig && git push origin main")
    assert decision == "deny" and "same call" in reason


def test_an_exported_trace_variable_never_reaches_phylax_s_git(hooked, tmp_path):
    trace = tmp_path / "trace.log"
    guard(hooked, f"export GIT_TRACE={trace}; git push origin main")
    assert not trace.exists()


def test_an_alias_under_an_unreadable_variable_is_refused(hooked):
    decision, reason = guard(hooked, "GIT_CONFIG_GLOBAL=$CFG git p origin main")
    assert decision == "deny" and "cannot read" in reason


@pytest.mark.parametrize(
    ("command", "says"),
    [
        ("H=/dev/null git --config-env=core.hooksPath=H push origin main", "without techne's"),
        ("A='push --no-verify' git --config-env=alias.p=A p origin main", "--no-verify skips"),
        ("git --config-env=core.hooksPath=NOPE push origin main", "cannot read"),
        ("git --config-env=alias.p=NOPE p origin main", "stands for"),
        ('git --git-dir="$UNSET_DIR/.git" push --no-verify origin main', "could not read"),
    ],
)
def test_config_env_and_repo_options_are_read_or_refused(hooked, command, says):
    decision, reason = guard(hooked, command)
    assert decision == "deny" and (says in reason or "/dev or /proc" in reason), (command, reason)


def test_an_aliased_commit_through_config_env_is_still_checked(hooked):
    _git(hooked, "config", "alias.ci", "commit")
    trailer = "Co-Authored-By: Claude <noreply@anthropic.com>"
    command = f"N=me git --config-env=user.name=N ci --allow-empty -m x -m '{trailer}'"
    env = {"CLAUDE_PLUGIN_OPTION_BLOCK_ATTRIBUTION_TRAILERS": "true"}
    decision, reason = guard(hooked, command, env)
    assert decision == "deny" and "attribution line" in reason


def test_a_git_dir_from_a_substitution_is_refused(hooked, tmp_path):
    away = tmp_path / "away"
    away.mkdir()
    command = f"export GIT_DIR=$(printf %s {hooked}/.git); git push --no-verify origin main"
    assert guard(away, command)[0] == "deny"


@pytest.mark.parametrize(
    "command",
    [
        "rm .git/hooks/pre-push; git push origin main",
        "printf '[include]\\n' >> .git/config && git push origin main",
        "mv .git/hooks/pre-push x && git push origin main",
        "mv .git/hooks x && git push origin main",
        "printf '[include]\\n' >> .gi?/config && git push origin main",
    ],
)
def test_a_hooks_change_is_seen_through_symlinks_moves_and_globs(hooked, tmp_path, command):
    link = tmp_path / "link"
    link.symlink_to(hooked)
    for cwd in (hooked, link):
        decision, reason = guard(cwd, command)
        assert decision == "deny" and "same call" in reason, (cwd, command)


def test_a_trace2_target_in_config_writes_nothing(hooked, tmp_path):
    trace = tmp_path / "t2.json"
    cfg = tmp_path / "t2.cfg"
    cfg.write_text(f"[trace2]\n\teventTarget = {trace}\n")
    guard(hooked, f"GIT_CONFIG_GLOBAL={cfg} git push origin main")
    guard(hooked, f"HOME={tmp_path} GIT_CONFIG_GLOBAL={cfg} git fetch origin")
    assert not trace.exists()


@pytest.mark.parametrize(
    "command",
    [
        'git push -u origin "$(git branch --show-current)"',
        'git push origin "$(git rev-parse --abbrev-ref HEAD)"',
        'BR=$(git rev-parse --abbrev-ref HEAD); git push -u origin "$BR"',
        'GIT_DIR="$PWD/.git" git fetch origin',
        'HOME="$HOME" git log -1',
        "GIT_CONFIG_GLOBAL=$CFG git rev-parse HEAD",
        'GIT_DIR="$PWD/.git" git push origin main',
    ],
)
def test_common_variable_and_substitution_lines_pass(hooked, command):
    assert guard(hooked, command) == (None, ""), command


def test_phylax_s_git_never_runs_a_program_or_writes_a_file_the_command_names(hooked, tmp_path):
    evil = tmp_path / "evil"
    evil.mkdir()
    ran = tmp_path / "ran"
    (evil / "git").write_text(f'#!/bin/sh\necho ran >> {ran}\nexec /usr/bin/git "$@"\n')
    (evil / "git").chmod(0o755)
    trace = tmp_path / "perf.log"
    for command in (
        f"PATH={evil}:/usr/bin:/bin git --config-env=x.y=PATH push origin main",
        f"export GIT_TRACE_PERFORMANCE={trace}; git --config-env=x.y=GIT_TRACE_PERFORMANCE push",
        f"GIT_TRACE_PERFORMANCE={trace} git --config-env=x.y=GIT_TRACE_PERFORMANCE push",
    ):
        guard(hooked, command)
    assert not ran.exists() and not trace.exists()


@pytest.mark.parametrize(
    "alias",
    [
        "-c core.hooksPath=/dev/null push",
        "--config-env=core.hooksPath=H push",
        "-c core.hooksPath=/dev/null push --no-verify",
    ],
)
def test_options_inside_an_alias_are_checked(hooked, alias):
    decision, reason = guard(hooked, f"git -c alias.p='{alias}' p origin main", {"H": "/dev/null"})
    assert decision == "deny" and any(
        s in reason for s in ("techne's pre-push hook", "--no-verify", "/dev or /proc")
    )


@pytest.mark.parametrize(
    "command",
    [
        "export GIT_DIR=$(printf %s {repo}/.git); git push --no-verify origin main",
        'cd "$(printf %s {repo})" && git push --no-verify origin main',
        'git -C "$(printf %s {repo})" push --no-verify origin main',
        'D=$(printf %s {repo}); git -C "$D" push --no-verify origin main',
    ],
)
def test_a_push_into_a_repo_this_check_cannot_read_is_refused(repo, hooked, tmp_path, command):
    plain = tmp_path / "plain"
    _git(tmp_path, "init", "-q", str(plain))  # an unhooked repo to run from
    decision, _ = guard(plain, command.format(repo=hooked))
    assert decision == "deny", command


def test_the_current_top_folder_is_a_readable_target(hooked):
    command = 'cd "$(git rev-parse --show-toplevel)" && git push origin main'
    assert guard(hooked, command) == (None, "")


def test_send_pack_is_refused_in_a_hooked_repo(hooked, repo, tmp_path):
    decision, reason = guard(hooked, "git send-pack ../remote.git main")
    assert decision == "deny" and "git push" in reason
    plain = tmp_path / "plain2"
    _git(tmp_path, "init", "-q", str(plain))
    assert guard(plain, "git send-pack ../r.git main") == (None, "")


def test_an_absolute_cd_after_an_unreadable_one_is_known_again(hooked):
    command = f'cd "$(printf %s /tmp)"; cd {hooked} && git push origin main'
    assert guard(hooked, command) == (None, "")


@pytest.mark.parametrize("flag", ["--no-verify", "--no-verif", "--no-veri"])
def test_every_spelling_git_takes_for_no_verify_is_refused(hooked, flag):
    for command in (f"git push {flag} origin main", f"git -c alias.p='push {flag}' p origin main"):
        decision, reason = guard(hooked, command)
        assert decision == "deny" and "--no-verify skips" in reason, command
    assert guard(hooked, f"git push {flag} --verif origin main") == (None, "")


def test_git_itself_skips_the_hook_on_each_short_spelling(hooked, gh_stub):
    leak_on(hooked, "feature")
    for flag in ("--no-verif", "--no-veri"):
        sent = push(hooked, gh_stub, flag, "--dry-run", "origin", "feature")
        assert sent.returncode == 0, flag  # the hook did not run: phylax must refuse these


@pytest.mark.parametrize(
    "command",
    [
        "printf '[core]\\n\\thooks%s = /dev/null\\n' Path > {f} && GIT_CONFIG_GLOBAL={f} git push",
        "printf '[core]\\n\\thooks%s = /dev/null\\n' Path > {f} && git -c include.path={f} push",
        "echo '[alias] p = push --no-verify' > {f} && git -c include.path={f} p origin main",
    ],
)
def test_a_config_file_written_in_the_same_call_holds_the_push(hooked, tmp_path, command):
    decision, _ = guard(hooked, command.format(f=tmp_path / "f.cfg"))
    assert decision == "deny", command


def test_wrapper_folder_changes_are_read_like_cd(hooked, tmp_path):
    plain = tmp_path / "plain3"
    _git(tmp_path, "init", "-q", str(plain))
    for command in (
        f'env -C "$(printf %s {hooked})" git push --no-verify origin main',
        f'env --chdir="$(printf %s {hooked})" git push --no-verify origin main',
    ):
        assert guard(plain, command)[0] == "deny", command


def test_unset_is_followed(hooked, tmp_path):
    plain = tmp_path / "plain4"
    _git(tmp_path, "init", "-q", str(plain))
    command = (
        f"export GIT_DIR={plain}/.git GIT_WORK_TREE={plain}; unset GIT_DIR GIT_WORK_TREE; "
        "git push --no-verify origin main"
    )
    assert guard(hooked, command)[0] == "deny"


@pytest.mark.parametrize(
    "command",
    [
        "env -C{repo} git push --no-verify origin main",
        "env --chd={repo} git push --no-verify origin main",
        "env -iC {repo} git push --no-verify origin main",
    ],
)
def test_env_folder_options_are_followed_in_every_spelling(hooked, tmp_path, command):
    plain = tmp_path / "plain5"
    _git(tmp_path, "init", "-q", str(plain))
    decision, reason = guard(plain, command.format(repo=hooked))
    assert decision == "deny" and "--no-verify skips" in reason, command


def test_a_failed_lookup_with_only_config_options_refuses(hooked):
    decision, reason = guard(hooked, "git -c nosection push origin main")
    assert decision == "deny" and "could not read" in reason


@pytest.mark.parametrize(
    "command",
    [
        "GH_TOKEN=x git push origin main",
        "GITHUB_TOKEN=x git push origin main",
        'export PATH="$HOME/.local/bin:$PATH"; git push origin main',
        "env -u GIT_DIR git push origin main",
        "env -i HOME=/x git push origin main",
        "git config user.email && git push origin main",
    ],
)
def test_ordinary_variables_and_env_pass_in_a_repo_without_the_scan(repo, tmp_path, command):
    published(repo, tmp_path)
    assert guard(repo, command) == (None, ""), command


def test_git_config_reading_one_key_does_not_hold_the_push(hooked):
    assert guard(hooked, "git config user.email && git push origin main") == (None, "")


@pytest.mark.parametrize(
    "command",
    [
        "git push origin $(git branch --show-current) --no-verify",
        "git push origin $(git branch --show-current) --no-veri",
        "git push origin $(git rev-parse --abbrev-ref HEAD) --no-verify",
        "git push origin $(echo --no-verify)",
    ],
)
def test_words_after_an_unquoted_substitution_are_not_hidden(hooked, command):
    assert guard(hooked, command)[0] == "deny", command


def test_a_config_file_git_itself_writes_first_holds_the_push(hooked, tmp_path):
    cfg = tmp_path / "evil.cfg"
    command = f"git show HEAD:README.md > {cfg} && GIT_CONFIG_GLOBAL={cfg} git push origin main"
    assert guard(hooked, command)[0] == "deny"
    command = f"git checkout main -- README.md && GIT_CONFIG_GLOBAL={cfg} git push origin main"
    assert guard(hooked, command)[0] == "deny"


def test_the_hook_refuses_a_push_when_gh_cannot_list_the_private_repos(repo, gh_stub, tmp_path):
    ship_scanner(repo)
    published(repo, tmp_path)
    assert install(repo).returncode == 0
    leak_on(repo, "feature")
    signed_out = [{"match": ["repo", "view"], "exit": 4, "stderr": "not logged in"}]
    gh_stub.rules(signed_out)
    env = {**gh_stub.env, "PATH": f"{pathlib.Path(HOOK_PYTHON).parent}:{gh_stub.env['PATH']}"}
    refused = subprocess.run(
        ["git", "push", "origin", "feature"], cwd=repo, capture_output=True, text=True, env=env
    )
    assert refused.returncode != 0 and "refused unscanned" in refused.stderr
    plain = run(repo, gh_stub, signed_out)  # the default scan still skips, as in CI
    assert plain.returncode == 0 and "SKIP" in plain.stderr


@pytest.mark.parametrize(
    ("url", "owner"),
    [
        ("https://github.com/acme/r.git", "acme"),
        ("git@github.com:acme/r.git", "acme"),
        ("ssh://git@github.com/acme-co/r", "acme-co"),
        ("/srv/git/r.git", ""),
        ("https://gitlab.com/acme/r.git", ""),
    ],
)
def test_the_owner_comes_from_the_push_url(url, owner):
    sys.path.insert(0, str(SCRIPT.parent))
    try:
        import check_private_names as cpn  # ty: ignore[import-not-found]
    finally:
        sys.path.remove(str(SCRIPT.parent))
    assert cpn.url_owner(url) == owner


def test_the_hook_scans_for_the_push_url_s_owner_whatever_gh_repo_view_says(
    repo, gh_stub, tmp_path
):
    published(repo, tmp_path)
    leak_on(repo, "feature")
    sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "feature"], capture_output=True, text=True
    ).stdout.strip()
    rules = [
        {"match": ["repo", "view"], "stdout": "other\n"},  # as GH_REPO=other/x would say
        {"match": ["repo", "list", "acme"], "stdout": json.dumps([{"name": n} for n in PRIVATE])},
        {"match": ["repo", "list", "other"], "stdout": "[]"},
        {"match": ["api", "user"], "stdout": "acme\n"},
    ]
    line = f"refs/heads/feature {sha} refs/heads/feature {'0' * 40}\n"
    args = ("--pre-push", "origin", "https://github.com/acme/r.git")
    result = run(repo, gh_stub, rules, args=args, stdin=line)
    assert result.returncode == 1 and "secret-proj" in result.stdout


@pytest.mark.parametrize(
    "command",
    [
        "git -c include.path=/dev/fd/3 push origin main 3< prior.cfg",
        "GIT_CONFIG_GLOBAL=/dev/fd/3 git push origin main 3< prior.cfg",
        "git -c include.path=/dev/stdin push origin main <<< '[core]'",
        "git push origin main < /dev/null",
    ],
)
def test_a_push_that_reads_input_is_refused_in_a_hooked_repo(hooked, command):
    decision, reason = guard(hooked, command)
    assert decision == "deny" and "reads input" in reason, command


def test_the_hook_keeps_its_ref_lines_from_a_config_that_reads_stdin(repo, gh_stub, tmp_path):
    ship_scanner(repo)
    published(repo, tmp_path)
    assert install(repo).returncode == 0
    leak_on(repo, "feature")
    _git(repo, "config", "include.path", "/dev/stdin")  # set in an earlier call
    refused = push(repo, gh_stub, "origin", "feature")
    assert refused.returncode != 0  # refused, never sent unscanned


@pytest.mark.parametrize(
    "command",
    [
        "git push -u origin $(git branch --show-current) 2>&1 | tail -5",
        "git push -u origin $(git branch --show-current) >/dev/null",
    ],
)
def test_redirections_and_later_commands_after_a_branch_substitution_pass(hooked, command):
    assert guard(hooked, command) == (None, ""), command


@pytest.mark.parametrize(
    ("url", "owner"),
    [
        ("ssh://git@ssh.github.com:443/acme/r.git", "acme"),
        ("https://www.github.com/acme/r", "acme"),
        ("git@github.com:/acme/r.git", "acme"),
    ],
)
def test_more_url_forms_give_their_owner(url, owner):
    sys.path.insert(0, str(SCRIPT.parent))
    try:
        import check_private_names as cpn  # ty: ignore[import-not-found]
    finally:
        sys.path.remove(str(SCRIPT.parent))
    assert cpn.url_owner(url) == owner


def test_a_push_to_another_account_still_scans_this_owner_s_names(repo, gh_stub, tmp_path):
    published(repo, tmp_path)
    leak_on(repo, "feature")
    sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "feature"], capture_output=True, text=True
    ).stdout.strip()
    rules = [
        {"match": ["repo", "view"], "stdout": "acme\n"},
        {"match": ["repo", "list", "acme"], "stdout": json.dumps([{"name": n} for n in PRIVATE])},
        {"match": ["repo", "list", "someoneelse"], "stdout": "[]"},
        {"match": ["api", "user"], "stdout": "acme\n"},
    ]
    line = f"refs/heads/feature {sha} refs/heads/feature {'0' * 40}\n"
    args = ("--pre-push", "x", "https://github.com/someoneelse/x.git")
    result = run(repo, gh_stub, rules, args=args, stdin=line)
    assert result.returncode == 1 and "secret-proj" in result.stdout


@pytest.mark.parametrize(
    ("setup", "command"),
    [
        (("config", "alias.p", "push"), "git p origin $(git branch --show-current) --no-verify"),
        (None, "git -c alias.p=push p origin $(git branch --show-current) --no-verify"),
    ],
)
def test_an_alias_cannot_hide_words_after_a_branch_substitution(hooked, setup, command):
    if setup:
        _git(hooked, *setup)
    assert guard(hooked, command)[0] == "deny", command


def test_config_from_dev_stdin_is_refused_without_a_redirection(hooked):
    decision, reason = guard(hooked, "printf x | git -c include.path=/dev/stdin push origin main")
    assert decision == "deny" and "reads input" in reason


def test_the_hook_refuses_when_gh_sees_no_private_repo_as_another_account(repo, gh_stub, tmp_path):
    published(repo, tmp_path)
    leak_on(repo, "feature")
    sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "feature"], capture_output=True, text=True
    ).stdout.strip()
    line = f"refs/heads/feature {sha} refs/heads/feature {'0' * 40}\n"
    base = [
        {"match": ["repo", "view"], "stdout": "acme\n"},
        {"match": ["repo", "list", "acme"], "stdout": "[]"},
    ]
    args = ("--pre-push", "origin", "https://github.com/acme/r.git")
    other = run(
        repo,
        gh_stub,
        [*base, {"match": ["api", "user"], "stdout": "acme-work\n"}],
        args=args,
        stdin=line,
    )
    assert other.returncode == 2 and "signed in as acme-work" in other.stderr
    owner = run(
        repo,
        gh_stub,
        [*base, {"match": ["api", "user"], "stdout": "acme\n"}],
        args=args,
        stdin=line,
    )
    assert owner.returncode == 0 and "SKIP" in owner.stderr


def test_the_hook_message_says_how_to_get_gh(repo, gh_stub, tmp_path):
    published(repo, tmp_path)
    env = {**gh_stub.env, "PATH": "/nonexistent"}
    result = subprocess.run(
        [HOOK_PYTHON, str(SCRIPT), "--pre-push", "o", "u"],
        cwd=repo,
        env=env,
        input="",
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2 and "Install gh" in result.stderr


# The everyday commit with a heredoc message, then a push.
HEREDOC_COMMIT = (
    "git commit -m \"$(cat <<'EOF'\nfix: it's (really) done\nEOF\n)\" && git push origin main"
)
SUBSTITUTIONS = [
    "$(git branch --show-current)",
    '"$(git branch --show-current)"',
    "''$(git branch --show-current)",
    "$(git branch --show-current)''",
    '$(git branch --show-current)""',
    "$(git 'branch' --show-current)",
    "$(git branch \\--show-current)",
    "\"$(git branch --show-current)\"''",
    "$(git rev-parse --abbrev-ref HEAD)",
    '""$(git branch --show-current)""',
    '"x"$(git branch --show-current)',
    '$(git branch --show-current)"":main',
]
SUFFIXES = [
    "",
    " &>/dev/null",
    " &>>{log}",
    " >|{log}",
    " 2>&1",
    " >{log}",
    " >/dev/null 2>&1",
    "#",
    " >&2",
    " 2> >(cat >&2)",
    " > >(tee {log})",
    " >()",
    " <(true)",
]
# --no-verify spelled with the escapes $'...' decodes, and the prefixes git takes.
FLAGS = [
    "--no-verify",
    "$'\\x2d-no-verify'",
    "$'\\055-no-verify'",
    "$'\\u002d-no-verify'",
    "--no-verif$'\\171'",
    "--no-verif",
    "--no-veri",
]
PUSHES = ["git push origin ", "git -c alias.p=push p origin "]


def test_no_branch_substitution_shape_carries_no_verify_past_phylax(hooked, tmp_path):
    # Differential: bash decides which words reach git; phylax must refuse every line where
    # --no-verify is one of them.
    out, log = tmp_path / "args", tmp_path / "log"
    stand_in = (
        'git() { printf "%s\\n" "$@" >> "$OUT"; '
        'case "$1" in branch|rev-parse) echo main;; esac; }; '
    )
    missed, reached = [], 0
    for push_ in PUSHES:
        for sub in SUBSTITUTIONS:
            for suffix in SUFFIXES:
                command = push_ + sub + suffix.format(log=log) + " --no-verify"
                out.write_text("")
                subprocess.run(
                    ["bash", "-c", stand_in + command],
                    env={"OUT": str(out), "PATH": os.environ["PATH"]},
                    cwd=tmp_path,
                    capture_output=True,
                    timeout=10,
                )
                if "--no-verify" in out.read_text().split("\n"):
                    reached += 1
                    if guard(hooked, command)[0] != "deny":
                        missed.append(command)
    for push_ in PUSHES:
        for flag in FLAGS:
            command = push_ + "main " + flag
            out.write_text("")
            subprocess.run(
                ["bash", "-c", stand_in + command],
                env={"OUT": str(out), "PATH": os.environ["PATH"]},
                cwd=tmp_path,
                capture_output=True,
                timeout=10,
            )
            if set(out.read_text().split("\n")) & {"--no-verify", "--no-verif", "--no-veri"}:
                reached += 1
                if guard(hooked, command)[0] != "deny":
                    missed.append(command)
    assert missed == []
    assert reached >= len(PUSHES) * (len(SUBSTITUTIONS) + len(FLAGS))  # bash passed the flag


def test_the_hook_refuses_a_partial_list_seen_from_another_account(repo, gh_stub, tmp_path):
    published(repo, tmp_path)
    leak_on(repo, "feature")
    sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "feature"], capture_output=True, text=True
    ).stdout.strip()
    rules = [
        {"match": ["repo", "view"], "stdout": "acme\n"},
        {"match": ["repo", "list", "acme"], "stdout": json.dumps([{"name": "widgets"}])},
        {"match": ["api", "user"], "stdout": "acme-work\n"},
    ]
    line = f"refs/heads/feature {sha} refs/heads/feature {'0' * 40}\n"
    args = ("--pre-push", "origin", "https://github.com/acme/r.git")
    result = run(repo, gh_stub, rules, args=args, stdin=line)
    assert result.returncode == 2 and "signed in as acme-work" in result.stderr


@pytest.mark.parametrize(
    ("text", "unreadable"),
    [
        ("git push origin $(git branch --show-current)", False),
        ('git push -u origin "$(git branch --show-current)"', False),
        ("git push origin $(git branch --show-current) 2>&1 | tail -5", False),
        ("git push origin $(git branch --show-current) >/dev/null; ls", False),
        ("git push origin $(git branch --show-current) >&2", False),
        ('BR=$(git rev-parse --abbrev-ref HEAD); git push -u origin "$BR"', False),
        ('cd "$(git rev-parse --show-toplevel)" && git push origin main', False),
        ('git commit -m "fix #3" && git push origin main # done', False),
        ('git push origin ""$(git branch --show-current)"" --no-verify', True),
        ("git push origin $(git branch --show-current)# --no-verify", True),
        ("git push origin main $'\\x2d-no-verify'", True),
        ("git push origin $(git branch --show-current) &>/dev/null --no-verify", True),
        ("git push origin $(git branch --show-current) 2>&1 --no-verify", True),
        ("git push origin $(git branch --show-current) >&2 --no-verify", True),
        ("git push origin $(git 'branch' --show-current)", True),
        ('git push origin "$(echo "a")"', True),
        ("git push origin `git branch --show-current`", True),
        ("git push origin $(git branch --show-current", True),
        ('git push origin "main', True),
        ('git push origin a#b "$(git rev-parse --show-toplevel)"', False),
        ('git push origin "$(git branch --show-current)"x', True),
        ("git push origin main 2> >(cat >&2) --no-verify", True),
        ("git push --repo >(true) --no-verify origin main", True),
        ("(cd sub && git push origin main)", True),
        ("git commit -m 'mention `make test`' && git push origin main", False),
        ("git commit -m '$(foo)' && git push origin main", False),
        ("git push origin main # it's done", False),
        (
            HEREDOC_COMMIT,
            False,
        ),
        ("git push && gh pr create --body \"$(cat <<'EOF'\nbody's text\nEOF\n)\"", False),
        ("cat <<'EOF'\n" + '"$(' * 600 + "\nEOF\ngit push origin main", False),
        ('"$(' * 5000, True),
    ],
)
def test_the_shell_lexer_reads_each_substitution_as_bash_does(monkeypatch, text, unreadable):
    (git_checks,) = load_phylax_hooks(monkeypatch, "git_checks")
    assert git_checks.unreadable_substitution(text) is unreadable, text


def test_the_heredoc_commit_and_push_lines_pass_in_a_hooked_repo(hooked):
    for command in (
        HEREDOC_COMMIT,
        "git push origin main && gh pr create --body \"$(cat <<'EOF'\nbody's text\nEOF\n)\"",
    ):
        assert guard(hooked, command)[0] is None, command


def test_a_push_check_that_fails_refuses_the_push(monkeypatch, tmp_path):
    (git_checks,) = load_phylax_hooks(monkeypatch, "git_checks")

    def boom(self, cmd, env):
        raise RecursionError

    monkeypatch.setattr(git_checks.Guards, "_check_push_hook", boom)
    guards = git_checks.Guards([], "")
    guards.check_push_hook(None, {})
    assert "check failed (RecursionError)" in guards.verdict.reason()


def test_a_lexer_that_fails_reads_as_unreadable(monkeypatch):
    (git_checks,) = load_phylax_hooks(monkeypatch, "git_checks")

    def boom(text):
        raise RecursionError

    monkeypatch.setattr(git_checks, "shell_tokens", boom)
    assert git_checks.unreadable_substitution("git push origin main") is True


HIDDEN_SKIPS = [
    'x="main --no-verify"; git push origin $x',
    'ARGS="-u origin main --no-verify"; git push $ARGS',
    "IFS=:; x=main:--no-verify; git push origin $x",
    "cat <<EOF\n$(git push --no-verify origin main)\nEOF",
    "cat <<EOF\n`git push --no-verify origin main`\nEOF",
    "echo `echo #`; git push --no-verify origin main",
    'echo "${y:-" #"}"; git push --no-verify origin main',
    "echo ${y:-<<EOF}\ngit push --no-verify origin main",
    'cat <<EOF; echo "\n"\nEOF\ngit push --no-verify origin main\n#"',
    "cat <<EOF\n$(git push --no-ve''rify origin main)\nEOF",
    "cat <<EOF\n$(git p''ush --no-verify origin main)\nEOF",
    "cat <<EOF\n$(git p\\ush --no-verify origin main)\nEOF",
    "IFS+=:; x=main:--no-verify; git push origin $x",
    "read -r IFS <<< :; x=main:--no-verify; git push origin $x",
    "printf -v IFS :; x=main:--no-verify; git push origin $x",
    "echo \"$(git p''ush --no-verify origin main)\"",
    "x=$(git p''ush --no-verify origin main)",
    'echo "${y:-"$(git p\'\'ush --no-verify origin main)"}"',
    "echo ${x:+ #}; git push origin main 2> >(cat) --no-verify",
    "l='a # b'; echo ${l%% #*}; git push origin main 2> >(cat) --no-verify",
    "echo ${x:+ #} push\necho `echo #`; git push --no-verify origin main",
    "cat <<'EOF' $(\ngit push --no-verify origin main\n)\nEOF\n# )",
    "cat <<'EOF' `\ngit push --no-verify origin main\n`\nEOF\n# `",
    "cat <<EOF $(\ngit push --no-verify origin main\n)\nEOF\n# )",
    "git commit -F - <<'EOF' && echo $(\ngit push --no-verify origin main\n)\nfix: msg\nEOF\n# )",
    "cat <<EOF | (cat\nEOF\n)\ngit push --no-verify origin main\nEOF",
    "cat <<'EOF' | (cat\nEOF\n)\ngit push --no-verify origin main\nEOF",
    'echo "$((git push --no-verify origin main) )"',
    'out="$((cd . && git push --no-verify origin main) 2>&1)"',
    "cat <<EOF | ((cat) # it's\nEOF\n)\ngit push --no-verify origin main\nEOF",
    'cat <<EOF | ((echo \\") ; true\nEOF\n)\ngit push --no-verify origin main\nEOF',
    'out="$((cd . && git push --no-verify origin main; : ' + "x" * 2100 + ') 2>&1)"',
    "cat <<EOF | ((cat) ; : " + "x" * 2100 + "\nEOF\n)\ngit push --no-verify origin main\nEOF",
    "cat <<EOF; (( 1 )); echo $(\ngit push --no-verify origin main\n)\nEOF",
    "cat <<EOF $( (true)\ngit push --no-verify origin main\n)\nEOF",
]


@pytest.mark.parametrize("command", HIDDEN_SKIPS)
def test_a_skip_hidden_from_the_parser_is_still_refused(hooked, tmp_path, command):
    out = tmp_path / "args"
    out.write_text("")
    stand_in = 'git() { printf "%s\\n" "$@" >> "$OUT"; }; '
    subprocess.run(
        ["bash", "-c", stand_in + command],
        env={"OUT": str(out), "PATH": os.environ["PATH"]},
        cwd=tmp_path,
        capture_output=True,
        timeout=10,
    )
    assert "--no-verify" in out.read_text().split("\n"), "bash hands git the flag"
    assert guard(hooked, command)[0] == "deny", command


@pytest.mark.parametrize(
    "command",
    [
        'git commit -am "fix \\`foo\\` call" && git push origin main',
        "BR=main; git push origin $BR",
        "echo $((1+2)); git push origin main",
        'git commit -m "fix(phylax): read --no-verify as git does; hold a pushed config"',
        "gh pr create --body \"$(cat <<'EOF'\nWhy: git push --no-verify skipped the hook\nEOF\n)\"",
        "git commit -F - <<'EOF'\nfix: a push with --no-verify is refused\nEOF",
        "gh issue comment 1 --body-file - <<'EOF'\npush --no-verify, core.hooksPath\nEOF",
        "git commit -F - <<'EOF'\ndocs: never run $(git push --no-verify)\nEOF",
        'git push -u origin "$(git branch --show-current)"',
    ],
)
def test_routine_lines_with_escapes_and_plain_variables_pass(hooked, command):
    assert guard(hooked, command)[0] is None, command


def test_a_plain_repo_keeps_its_no_verify(repo, tmp_path):
    published(repo, tmp_path)  # no scanner, no hook: nothing to skip
    assert guard(repo, "git push --no-verify origin main")[0] is None
    assert guard(repo, "cat <<EOF\n$(git push --no-verify origin main)\nEOF")[0] is None


def test_many_heredocs_on_one_line_stay_linear(monkeypatch):
    (git_checks,) = load_phylax_hooks(monkeypatch, "git_checks")

    def took(k):
        text = "cat " + "<<E " * k + "\nE\n" * k
        start = time.process_time()
        git_checks.strip_heredocs(text)
        return time.process_time() - start

    small, large = took(2000), took(8000)
    assert large < 0.05 or large / max(small, 1e-6) < 9, (small, large)


def test_an_alias_push_does_not_use_up_a_hidden_one(hooked):
    _git(hooked, "config", "alias.p", "push")
    command = "git p origin main; cat <<EOF\n$(git push --no-verify origin main)\nEOF"
    assert guard(hooked, command)[0] == "deny"


def test_a_call_that_does_not_parse_as_bash_reads_as_hiding_a_push(monkeypatch):
    (git_checks,) = load_phylax_hooks(monkeypatch, "git_checks")
    assert git_checks.names_a_hook_skip('echo "open; git push --no-verify', []) is True


def test_the_lexer_nests_quotes_inside_a_quoted_brace_expansion(monkeypatch):
    # bash: "${y:-" #"}" is one word; the # is inside it, not a comment.
    (git_checks,) = load_phylax_hooks(monkeypatch, "git_checks")
    tokens = git_checks.shell_tokens('echo "${y:-" #"}"; git push origin main')
    words = [raw for kind, raw, _ in tokens if kind == "word"]
    assert words == ["echo", '"${y:-" #"}"', "git", "push", "origin", "main"]


def test_process_substitution_text_refuses_whatever_the_lexer_reads(monkeypatch):
    (git_checks,) = load_phylax_hooks(monkeypatch, "git_checks")
    monkeypatch.setattr(git_checks, "shell_tokens", lambda text: [])
    assert git_checks.unreadable_substitution("git push origin main 2> >(cat) --no-verify")


@pytest.mark.parametrize(
    ("text", "words"),
    [
        # a comment inside $( ... ) runs to the line's end: its ) closes nothing
        ("echo $(echo a # )\nb) x", ["echo", "$(echo a # )\nb)", "x"]),
        # a bare ${...} is one word, the # in it text
        (
            "echo ${x:+ #}; git push origin main",
            ["echo", "${x:+ #}", "git", "push", "origin", "main"],
        ),
    ],
)
def test_the_lexer_reads_comments_and_braces_as_bash_does(monkeypatch, text, words):
    (git_checks,) = load_phylax_hooks(monkeypatch, "git_checks")
    tokens = git_checks.shell_tokens(text)
    assert [raw for kind, raw, _ in tokens if kind == "word"] == words


def test_a_comment_inside_backticks_ends_at_the_closing_one(monkeypatch):
    (git_checks,) = load_phylax_hooks(monkeypatch, "git_checks")
    stripped, _ = git_checks.strip_heredocs("echo `echo #`; git push origin main")
    assert "git push origin main" in stripped


def test_a_subshell_does_not_hold_back_a_heredoc_body(monkeypatch):
    # bash starts the body at the first newline inside ( or {, but waits for $( to close.
    (git_checks,) = load_phylax_hooks(monkeypatch, "git_checks")
    stripped, bodies = git_checks.strip_heredocs("cat <<EOF | (cat\nEOF\n)\ngit push origin main")
    assert "git push origin main" in stripped and bodies[0][1] == ""
    stripped, bodies = git_checks.strip_heredocs(
        "cat <<EOF $(\nx\n)\nbody\nEOF\ngit push origin main"
    )
    assert bodies[0][1] == "body" and "git push origin main" in stripped
    stripped, bodies = git_checks.strip_heredocs(
        "cat <<EOF <(cat\nx\n)\nbody\nEOF\ngit push origin main"
    )
    assert bodies[0][1] == "body" and "git push origin main" in stripped  # <( is waited on


def test_comments_in_an_open_backtick_stay_linear(monkeypatch):
    (git_checks,) = load_phylax_hooks(monkeypatch, "git_checks")

    def took(k):
        start = time.process_time()
        git_checks.strip_heredocs("echo `" + " #\n" * k)
        return time.process_time() - start

    small, large = took(20000), took(80000)
    assert large < 0.05 or large / max(small, 1e-6) < 9, (small, large)


def test_a_paren_inside_a_brace_expansion_is_text(monkeypatch):
    (git_checks,) = load_phylax_hooks(monkeypatch, "git_checks")
    tokens = git_checks.shell_tokens("echo ${x:-(} b")
    assert [raw for kind, raw, _ in tokens if kind == "word"] == ["echo", "${x:-(}", "b"]


def test_a_backtick_comment_ends_at_its_line_and_the_backtick_goes_on(monkeypatch):
    # bash: in `echo x # c<newline>git push`, the comment ends at the newline and the push runs.
    (git_checks,) = load_phylax_hooks(monkeypatch, "git_checks")
    stripped, _ = git_checks.strip_heredocs("echo `echo x # c\ngit push origin main`; true")
    assert "git push origin main" in stripped


def test_quotes_nest_inside_a_quoted_brace_expansion_for_every_guard(monkeypatch):
    # strip_heredocs, which every guard reads: "${y:-" #"}" is one word, so no comment starts.
    (git_checks,) = load_phylax_hooks(monkeypatch, "git_checks")
    stripped, _ = git_checks.strip_heredocs('echo "${y:-" #"}"; git push origin main')
    assert "git push origin main" in stripped


@pytest.mark.parametrize(
    ("text", "reading"),
    [
        ("((1+1))", True),
        ("((a*(b+c)))", True),
        ("((cd a); (cd b))", False),
        ("((cat) # it's\nx)", False),
        ('((echo \\") ; true)', False),
        ("((echo 'open", None),
        ("((" + "1+" * 2000 + "1))", None),
    ],
)
def test_arith_reading_says_when_it_cannot_tell(monkeypatch, text, reading):
    (git_checks,) = load_phylax_hooks(monkeypatch, "git_checks")
    assert git_checks.arith_reading(text, 0) is reading
    assert git_checks.is_arith(text, 0) is (reading is not False)


@pytest.mark.parametrize(
    "text",
    [
        # arithmetic turns a subshell's ( into a frame bash waits on: the body starts after $(
        "cat <<EOF; (( 1 )); echo $(\nx\n)\nbody\nEOF",
        # a subshell's ( that closes inside $( leaves only $( to wait on
        "cat <<EOF $( (true)\nx\n)\nbody\nEOF",
    ],
)
def test_the_frame_count_follows_arithmetic_and_closing_subshells(monkeypatch, text):
    (git_checks,) = load_phylax_hooks(monkeypatch, "git_checks")
    assert git_checks.strip_heredocs(text)[1][0][1] == "body"


def test_a_quoted_open_paren_pair_in_a_commit_message_passes(hooked):
    assert guard(hooked, 'git commit -m "note ((it\'s open" && git push origin main')[0] is None


@pytest.mark.parametrize(
    "command",
    [
        "git config alias.p 'push --no-verify' && git p origin main",
        "git config alias.p 'push --no-verify'; git p origin main",
        "git config alias.p 'push --no-verify'\ngit p origin main",
        "git config --global alias.p 'push --no-verify' && git p origin main",
        "git config alias.p '-c core.hooksPath=/dev/null push' && git p origin main",
    ],
)
def test_an_alias_defined_earlier_in_the_call_is_refused(hooked, command):
    # guard() only reads the command: the --global form writes nothing
    decision, reason = guard(hooked, command)
    assert decision == "deny" and "changes git's config" in reason, (command, reason)


def test_a_plain_repo_keeps_its_config_then_alias(repo, tmp_path):
    published(repo, tmp_path)
    assert guard(repo, "git config alias.st status && git st")[0] is None


@pytest.mark.parametrize(
    "command",
    [
        # a short alias that already names a built-in, redefined in the same call
        "git config alias.co 'push --no-verify' && git co origin main",
        "git config alias.st 'push --no-verify' && git st origin main",
        # config written as a file, not through git config
        "printf '[alias]\\n p = push --no-verify\\n' >> .git/config && git p origin main",
        "echo '[alias]' >> .git/config\n"
        "echo ' p = push --no-verify' >> .git/config\ngit p origin main",
        "sed -i '$a [alias]\\n p = push --no-verify' .git/config && git p origin main",
    ],
)
def test_an_alias_redefined_or_written_earlier_in_the_call_is_refused(hooked, command):
    _git(hooked, "config", "alias.co", "checkout")
    _git(hooked, "config", "alias.st", "status")
    decision, reason = guard(hooked, command)
    assert decision == "deny", (command, reason)


def test_an_alias_after_a_home_gitconfig_write_is_refused(hooked, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    command = "printf '[alias]\\n p = push --no-verify\\n' >> ~/.gitconfig && git p origin main"
    assert guard(hooked, command, {"HOME": str(home)})[0] == "deny"


@pytest.mark.parametrize(
    "command",
    [
        "git config user.name x && git commit --allow-empty -m y",
        "echo notes > notes.txt && git co main",
        "git config alias.st status && git st",
    ],
)
def test_routine_config_then_git_lines_pass_in_a_plain_repo(repo, tmp_path, command):
    published(repo, tmp_path)
    _git(repo, "config", "alias.co", "checkout")
    assert guard(repo, command)[0] is None, command


def test_an_alias_after_writing_an_ordinary_file_passes_in_a_hooked_repo(hooked):
    _git(hooked, "config", "alias.co", "checkout")
    assert guard(hooked, "echo notes > notes.txt && git co main")[0] is None


@pytest.mark.parametrize(
    ("include", "command"),
    [
        (
            "../.gitconfig.local",
            "printf '[alias]\\n p = push --no-verify\\n' > .gitconfig.local && git p origin main",
        ),
        (
            "../../inc.cfg",
            "printf '[alias]\\n p = push --no-verify\\n' > ../inc.cfg && git p origin main",
        ),
        ("../.gitconfig.local", "cp ../stash.cfg .gitconfig.local && git push origin main"),
        (
            "~/inc.cfg",
            "printf '[alias]\\n p = push --no-verify\\n' > ~/inc.cfg && git p origin main",
        ),
    ],
)
def test_a_file_the_config_includes_written_in_the_call_is_seen(hooked, tmp_path, include, command):
    home = tmp_path / "home"
    home.mkdir()
    (hooked.parent / "stash.cfg").write_text("[core]\n hooksPath = /dev/null\n")
    _git(hooked, "config", "include.path", include)
    decision, reason = guard(hooked, command, {"HOME": str(home)})
    assert decision == "deny" and "changes git's config" in reason, (command, reason)


def test_a_write_beside_an_include_still_passes(hooked):
    _git(hooked, "config", "include.path", "../.gitconfig.local")
    assert guard(hooked, "echo notes > notes.txt && git push origin main")[0] is None


def test_the_alias_refusal_names_what_was_typed(hooked):
    _git(hooked, "config", "alias.st", "status")
    reason = guard(hooked, "git config alias.st 'push --no-verify' && git st origin main")[1]
    assert "`git st` runs after" in reason, reason
