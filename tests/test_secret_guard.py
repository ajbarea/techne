"""Tests for phylax's block_secrets guard (git_guards.py + secret_scan.py).

Each case feeds the guard the PreToolUse JSON on stdin against a throwaway repo with a bare
remote. The secret is a GitHub token made at runtime, so no credential sits in this file.
The real gitleaks runs where it is installed (CI installs it); fake scanners cover ggshield
and a scanner that gives no verdict.
"""

from __future__ import annotations

import json
import os
import pathlib
import secrets
import shutil
import string
import subprocess

import pytest
from conftest import HOOK_PYTHON, hook_env

ROOT = pathlib.Path(__file__).resolve().parent.parent
GUARDS = ROOT / "plugins" / "phylax" / "hooks" / "git_guards.py"
SECRETS = "block_secrets"
needs_gitleaks = pytest.mark.skipif(
    shutil.which("gitleaks") is None and not os.environ.get("CI"),
    reason="gitleaks is not installed (CI installs it, so CI never skips)",
)


def token() -> str:
    alphabet = string.ascii_letters + string.digits
    return "ghp_" + "".join(secrets.choice(alphabet) for _ in range(36))


def _git(repo: pathlib.Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True, env=env
    ).stdout


@pytest.fixture
def repo(tmp_path):
    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "-q", "--bare", str(remote))
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "remote", "add", "origin", str(remote))
    (r / "a.txt").write_text("a\n")
    _git(r, "add", "a.txt")
    _git(r, "commit", "-qm", "init")
    _git(r, "push", "-q", "origin", "HEAD:main")
    _git(r, "fetch", "-q", "origin")
    return r


@pytest.fixture
def state(tmp_path):
    return tmp_path / "state"


def run_guard(command, cwd, state, *, on=(SECRETS,), extra_env=None):
    env = {**hook_env(on), "XDG_STATE_HOME": str(state), **(extra_env or {})}
    payload = json.dumps(
        {"cwd": str(cwd), "tool_input": {"command": command}, "agent_type": "Explore"}
    )
    proc = subprocess.run(
        [HOOK_PYTHON, str(GUARDS)],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=90,
    )
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout) if proc.stdout.strip() else None
    if out and out["hookSpecificOutput"].get("permissionDecision") == "deny":
        return out["hookSpecificOutput"]["permissionDecisionReason"]
    return None


def catches(state) -> list[dict]:
    log = state / "phylax" / "secret-gate.jsonl"
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def leak(repo: pathlib.Path, name: str = "cfg.py") -> str:
    value = token()
    (repo / name).write_text(f'token = "{value}"\n')
    return value


@needs_gitleaks
def test_add_then_commit_in_one_command_is_refused_and_the_index_is_untouched(repo, state):
    value = leak(repo)
    why = run_guard("git add cfg.py && git commit -m x", repo, state)
    assert why and "cfg.py:1" in why and "github-pat" in why and value not in why
    assert _git(repo, "status", "--porcelain") == "?? cfg.py\n"
    [event] = catches(state)
    assert event["outcome"] == "blocked" and event["kind"] == "commit"
    assert event["agent"] == "Explore" and event["findings"][0]["file"] == "cfg.py"
    assert value not in (state / "phylax" / "secret-gate.jsonl").read_text()


@needs_gitleaks
@pytest.mark.parametrize(
    "setup,command",
    [
        ("stage", "git commit -m x"),
        ("tracked", "git commit -am x"),
        ("none", "git commit -m x cfg.py"),
        ("none", "git commit -m x -- cfg.py"),
        ("none", "git add . ; git commit -m x"),
        ("none", "git add -p cfg.py && git commit -m x"),
        ("none", "git -C . add -A && git commit -m x"),
    ],
)
def test_each_way_a_secret_reaches_a_commit_is_refused(repo, state, setup, command):
    if setup == "tracked":
        _git(repo, "add", "a.txt")
        (repo / "a.txt").write_text(f'a\ntoken = "{token()}"\n')
    else:
        leak(repo)
        if setup == "stage":
            _git(repo, "add", "cfg.py")
    assert run_guard(command, repo, state)


@needs_gitleaks
def test_a_secret_only_in_the_old_history_or_untracked_files_does_not_block_a_clean_commit(
    repo, state
):
    leak(repo, "untracked.py")
    (repo / "b.txt").write_text("b\n")
    _git(repo, "add", "b.txt")
    assert run_guard("git commit -m b", repo, state) is None
    assert run_guard("git commit -am b", repo, state) is None
    assert catches(state) == []


@needs_gitleaks
def test_a_push_of_a_commit_with_a_secret_is_refused(repo, state):
    leak(repo)
    _git(repo, "add", "cfg.py")
    _git(repo, "commit", "-qm", "leak")
    for command in (
        "git push",
        "git push origin HEAD:main",
        "git push -u origin main",
        "git push --all",
    ):
        why = run_guard(command, repo, state)
        assert why and "this push" in why and "commit " in why, command
    assert catches(state)[-1]["kind"] == "push"


@needs_gitleaks
@pytest.mark.parametrize(
    "command",
    [
        "git push -n",
        "git push --dry-run origin",
        "git push origin --delete old",
        "git push origin :old",
    ],
)
def test_a_push_that_sends_no_commits_is_not_scanned(repo, state, command):
    leak(repo)
    _git(repo, "add", "cfg.py")
    _git(repo, "commit", "-qm", "leak")
    assert run_guard(command, repo, state) is None


@needs_gitleaks
def test_a_clean_push_passes(repo, state):
    (repo / "b.txt").write_text("b\n")
    _git(repo, "add", "b.txt")
    _git(repo, "commit", "-qm", "b")
    assert run_guard("git push origin HEAD:main", repo, state) is None


def test_the_guard_is_off_unless_switched_on_and_a_repo_can_turn_it_off(repo, state):
    leak(repo)
    _git(repo, "add", "cfg.py")
    assert run_guard("git commit -m x", repo, state, on=()) is None
    _git(repo, "config", "phylax.blockSecrets", "false")
    assert run_guard("git commit -m x", repo, state) is None


def fake(tmp_path: pathlib.Path, name: str, body: str) -> pathlib.Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    tool = bin_dir / name
    tool.write_text("#!/bin/sh\n" + body)
    tool.chmod(0o755)
    return bin_dir


def only(bin_dir: pathlib.Path) -> str:
    """A PATH with git and the shell but none of the real scanners."""
    git = pathlib.Path(shutil.which("git") or "/usr/bin/git").parent
    return os.pathsep.join([str(bin_dir), str(git), "/usr/bin", "/bin"])


def test_no_scanner_installed_refuses_and_logs_it(repo, state, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    if shutil.which("gitleaks", path=only(empty)):
        pytest.skip("gitleaks sits in a system folder here")
    _git(repo, "add", "a.txt")
    why = run_guard("git commit -m x", repo, state, extra_env={"PATH": only(empty)})
    assert why and "no verdict" in why and "install gitleaks" in why
    assert catches(state)[0]["outcome"] == "no_verdict"


def test_a_scanner_that_errors_refuses_rather_than_passing(repo, state, tmp_path):
    bin_dir = fake(tmp_path, "gitleaks", "echo 'fatal: bad config' >&2\nexit 1\n")
    why = run_guard("git commit -m x", repo, state, extra_env={"PATH": only(bin_dir)})
    assert why and "gitleaks gave no verdict: fatal: bad config" in why


GGSHIELD_FOUND = {
    "entities_with_incidents": [
        {
            "filename": "cfg.py",
            "incidents": [{"type": "GitHub Token", "occurrences": [{"line_start": 3}]}],
        }
    ],
    "total_incidents": 1,
}


def test_ggshield_scans_commits_when_its_key_is_set(repo, state, tmp_path):
    body = f"cat <<'EOF'\n{json.dumps(GGSHIELD_FOUND)}\nEOF\nexit 1\n"
    bin_dir = fake(tmp_path, "ggshield", body)
    fake(tmp_path, "gitleaks", "exit 0\n")
    env = {"PATH": only(bin_dir), "GITGUARDIAN_API_KEY": "placeholder"}
    why = run_guard("git commit -m x", repo, state, extra_env=env)
    assert why and "(ggshield): cfg.py:3 (GitHub Token)" in why
    # Without the key, gitleaks (here a clean fake) decides.
    assert run_guard("git commit -m x", repo, state, extra_env={"PATH": only(bin_dir)}) is None
    # A push is always gitleaks: ggshield takes one range per call.
    assert run_guard("git push", repo, state, extra_env=env) is None


def test_ggshield_without_a_verdict_refuses(repo, state, tmp_path):
    bin_dir = fake(tmp_path, "ggshield", "echo 'Error: 401 Unauthorized' >&2\nexit 128\n")
    env = {"PATH": only(bin_dir), "GITGUARDIAN_API_KEY": "placeholder"}
    why = run_guard("git commit -m x", repo, state, extra_env=env)
    assert why and "ggshield gave no verdict: Error: 401 Unauthorized" in why


def commit_leak(repo: pathlib.Path, name: str = "cfg.py") -> None:
    leak(repo, name)
    _git(repo, "add", name)
    _git(repo, "commit", "-qm", "leak")


@needs_gitleaks
def test_a_branch_named_like_a_folder_is_still_scanned(repo, state):
    (repo / "docs").mkdir()
    (repo / "docs" / "x.md").write_text("x\n")
    _git(repo, "add", "docs")
    _git(repo, "commit", "-qm", "docs")
    _git(repo, "checkout", "-qb", "docs")
    commit_leak(repo)
    why = run_guard("git push origin docs", repo, state)
    assert why and "would add a secret" in why, why


@needs_gitleaks
@pytest.mark.parametrize(
    "key,value",
    [("remote.origin.push", "refs/heads/*:refs/heads/*"), ("push.default", "matching")],
)
def test_a_bare_push_that_config_widens_scans_every_branch(repo, state, key, value):
    _git(repo, "checkout", "-qb", "feat2")
    commit_leak(repo)
    _git(repo, "checkout", "-q", "main")
    assert run_guard("git push origin", repo, state) is None
    _git(repo, "config", key, value)
    assert run_guard("git push origin", repo, state)
    assert run_guard("git push", repo, state)


@needs_gitleaks
def test_a_first_push_to_a_new_remote_skips_what_another_remote_holds(repo, state, tmp_path):
    # An old secret already on origin is not this push's doing; a new one still is.
    commit_leak(repo, "old.py")
    _git(repo, "push", "-q", "origin", "HEAD:main")
    _git(repo, "fetch", "-q", "origin")
    _git(tmp_path, "init", "-q", "--bare", str(tmp_path / "backup.git"))
    _git(repo, "remote", "add", "backup", str(tmp_path / "backup.git"))
    assert run_guard("git push backup main", repo, state) is None
    commit_leak(repo)
    assert run_guard("git push backup main", repo, state)


@needs_gitleaks
def test_a_mirror_push_scans_refs_beyond_branches(repo, state):
    _git(repo, "checkout", "-qb", "side")
    commit_leak(repo)
    _git(repo, "tag", "t1")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "branch", "-qD", "side")
    assert run_guard("git push --mirror origin", repo, state)


@needs_gitleaks
def test_a_slow_clean_filter_does_not_refuse_the_commit(repo, state):
    (repo / ".gitattributes").write_text("*.bin filter=slow\n")
    _git(repo, "config", "filter.slow.clean", "sleep 6; cat")
    _git(repo, "add", ".gitattributes")
    _git(repo, "commit", "-qm", "attrs")
    (repo / "big.bin").write_text("data\n")
    assert run_guard("git add big.bin && git commit -m data", repo, state) is None


def test_a_scanner_that_exits_0_with_an_error_refuses(repo, state, tmp_path):
    bin_dir = fake(tmp_path, "gitleaks", "echo 'ERR [git] fatal: bad revision' >&2\nexit 0\n")
    why = run_guard("git push", repo, state, extra_env={"PATH": only(bin_dir)})
    assert why and "gitleaks reported an error: ERR [git] fatal: bad revision" in why


def test_the_refusal_never_tells_the_agent_to_silence_the_scanner(repo, state, tmp_path):
    found = '[{"File": "cfg.py", "StartLine": 1, "RuleID": "github-pat"}]'
    body = f"""for a; do
  case "$prev" in --report-path) printf '%s' '{found}' > "$a";; esac; prev=$a
done
exit 1
"""
    bin_dir = fake(tmp_path, "gitleaks", body)
    why = run_guard("git commit -m x", repo, state, extra_env={"PATH": only(bin_dir)})
    assert why and "cfg.py:1 (github-pat)" in why
    assert "gitleaksignore" not in why and "git config" not in why and "ask the user" in why


@needs_gitleaks
def test_a_new_branch_committed_and_pushed_in_one_command_passes_when_clean(repo, state):
    (repo / "b.txt").write_text("b\n")
    command = "git checkout -b feat && git add b.txt && git commit -m b && git push -u origin feat"
    assert run_guard(command, repo, state) is None


@needs_gitleaks
@pytest.mark.parametrize(
    "command",
    [
        "git checkout feat && git push -u origin HEAD",
        "git merge feat && git push origin main",
        "git switch feat; git push",
    ],
)
def test_a_push_after_a_ref_move_in_the_same_command_scans_every_local_branch(repo, state, command):
    _git(repo, "checkout", "-qb", "feat")
    commit_leak(repo)
    _git(repo, "checkout", "-q", "main")
    why = run_guard(command, repo, state)
    assert why and "would add a secret" in why, why


@needs_gitleaks
def test_a_mirror_remote_from_config_scans_every_ref(repo, state, tmp_path):
    _git(repo, "checkout", "-qb", "side")
    commit_leak(repo)
    _git(repo, "checkout", "-q", "main")
    _git(tmp_path, "init", "-q", "--bare", str(tmp_path / "m.git"))
    _git(repo, "remote", "add", "--mirror=push", "backup", str(tmp_path / "m.git"))
    assert run_guard("git push backup", repo, state)


@needs_gitleaks
def test_a_negative_refspec_does_not_hide_a_commit_from_the_scan(repo, state):
    commit_leak(repo)
    _git(repo, "branch", "wip")
    assert run_guard("git push origin 'refs/heads/*' '^refs/heads/wip'", repo, state)


@needs_gitleaks
def test_a_tag_glob_scans_commits_only_tags_reach(repo, state):
    _git(repo, "checkout", "-qb", "tmp")
    commit_leak(repo)
    _git(repo, "tag", "v1")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "branch", "-qD", "tmp")
    assert run_guard("git push origin 'refs/tags/*'", repo, state)


@needs_gitleaks
def test_a_push_of_a_branch_that_does_not_exist_is_left_to_git(repo, state):
    # git refuses the whole push, so it sends nothing: no scan, and no blame on an unrelated
    # unpushed branch's secret.
    _git(repo, "checkout", "-qb", "old")
    commit_leak(repo)
    _git(repo, "checkout", "-q", "main")
    assert run_guard("git push origin no-such-branch", repo, state) is None


@needs_gitleaks
def test_a_widened_scan_still_covers_a_detached_head(repo, state):
    _git(repo, "checkout", "-q", "--detach")
    commit_leak(repo)
    command = "git commit --allow-empty -m y && git push origin HEAD:refs/heads/feat"
    why = run_guard(command, repo, state)
    assert why and "scanned wide" in why and "command of its own" in why, why


@needs_gitleaks
def test_commits_another_remote_holds_are_never_blamed(repo, state, tmp_path):
    # A fork: main tracks upstream, whose history carries a flagged fixture.
    _git(tmp_path, "init", "-q", "--bare", str(tmp_path / "up.git"))
    _git(repo, "remote", "add", "upstream", str(tmp_path / "up.git"))
    commit_leak(repo, "fixture.py")
    _git(repo, "push", "-q", "upstream", "HEAD:main")
    _git(repo, "fetch", "-q", "upstream")
    assert run_guard("git push origin main:refs/heads/feat", repo, state) is None
    assert run_guard("git checkout -b feat2 && git push -u origin feat2", repo, state) is None


@needs_gitleaks
def test_a_mover_in_another_repo_or_a_fetch_does_not_widen(repo, state, tmp_path):
    _git(repo, "checkout", "-qb", "old")
    commit_leak(repo)
    _git(repo, "checkout", "-q", "main")
    other = tmp_path / "other"
    other.mkdir()
    _git(other, "init", "-q", "-b", "main")
    assert run_guard(f"git -C {other} checkout -qb x && git push origin main", repo, state) is None
    assert run_guard("git fetch -q origin && git push origin main", repo, state) is None
    assert run_guard("git checkout -q main && git push origin main", repo, state)


@needs_gitleaks
def test_an_alias_for_commit_is_scanned(repo, state):
    _git(repo, "config", "alias.ci", "commit")
    leak(repo, "s.py")
    why = run_guard("git add s.py && git ci -m s", repo, state)
    assert why and "this commit would add a secret" in why, why


@needs_gitleaks
def test_a_chained_alias_is_followed_and_one_shadowing_a_git_command_is_ignored(repo, state):
    _git(repo, "config", "alias.ci", "commit")
    _git(repo, "config", "alias.c", "ci")
    _git(repo, "config", "alias.checkout", "commit")
    leak(repo, "s.py")
    _git(repo, "add", "s.py")
    assert run_guard("git c -m s", repo, state)
    assert run_guard("git checkout -q -b feat", repo, state) is None


@needs_gitleaks
def test_aliases_deep_with_a_pager_flag_or_shadowing_a_non_builtin_command(repo, state):
    chain = ["a1", "a2", "a3", "a4", "a5", "a6", "a7"]
    for name, target in zip(chain, [*chain[1:], "commit"], strict=True):
        _git(repo, "config", f"alias.{name}", target)
    _git(repo, "config", "alias.pc", "-p commit")
    _git(repo, "config", "alias.cc", "-c user.name=x commit")
    _git(repo, "config", "alias.ce", "--config-env user.name=HOME commit")
    _git(repo, "config", "alias.ce2", "--config-env=user.name=HOME commit")
    _git(repo, "config", "alias.bad", "-C /tmp commit")
    _git(repo, "config", "alias.filter-branch", "commit")
    leak(repo, "s.py")
    _git(repo, "add", "s.py")
    assert run_guard("git a1 -m s", repo, state), "a chain deeper than five is followed"
    assert run_guard("git pc -m s", repo, state), "a leading -p is skipped"
    assert run_guard("git cc -m s", repo, state), "a leading -c k=v is skipped"
    assert run_guard("git ce -m s", repo, state), "--config-env and its value are skipped"
    assert run_guard("git ce2 -m s", repo, state), "--config-env=... is skipped"
    assert run_guard("git bad -m s", repo, state) is None, (
        "git refuses -C before an alias's command"
    )
    assert run_guard("git filter-branch --help", repo, state) is None, "git runs its own command"
