"""Tests for the opt-in PreToolUse guards in plugins/techne/hooks/.

Each case feeds the hook the JSON Claude Code sends on stdin and reads the decision
from stdout, against a real throwaway repo. Every guard has a trip case, a clean
case, a case with its option off, and a case with the per-repo override set.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "plugins" / "techne"
GUARDS = PLUGIN / "hooks" / "git_guards.py"
HOOKS_JSON = PLUGIN / "hooks" / "hooks.json"
MANIFEST = PLUGIN / ".claude-plugin" / "plugin.json"

# The hook runs on the user's system python3; `make test-hooks-oldest` sets this to 3.9.
GUARD_PYTHON = os.environ.get("TECHNE_GUARD_PYTHON", sys.executable)

ATTRIBUTION = "block_attribution_trailers"
COMMITS_MD = "block_commits_md"
MAIN_CHECKOUT = "warn_main_checkout_commit"
ALL = (ATTRIBUTION, COMMITS_MD, MAIN_CHECKOUT)


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
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q")
    (r / "a.txt").write_text("a\n")
    _git(r, "add", "a.txt")
    _git(r, "commit", "-qm", "init")
    return r


def run_hook(command: str, cwd: pathlib.Path, *, on=ALL) -> dict | None:
    """Run the guard as Claude Code would; return its JSON output, or None when silent."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_PLUGIN_OPTION_")}
    for key in on:
        env[f"CLAUDE_PLUGIN_OPTION_{key.upper()}"] = "true"
    payload = json.dumps({"cwd": str(cwd), "tool_input": {"command": command}})
    proc = subprocess.run(
        [GUARD_PYTHON, str(GUARDS)],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout) if proc.stdout.strip() else None


def denied(out: dict | None) -> str | None:
    if out and out["hookSpecificOutput"].get("permissionDecision") == "deny":
        return out["hookSpecificOutput"]["permissionDecisionReason"]
    return None


def warned(out: dict | None) -> str | None:
    if out and "permissionDecision" not in out["hookSpecificOutput"]:
        assert out["systemMessage"] == out["hookSpecificOutput"]["additionalContext"]
        return out["systemMessage"]
    return None


# --- attribution ---------------------------------------------------------------

TRAILER = "Co-Authored-By: Claude <noreply@anthropic.com>"
HEREDOC_COMMIT = (
    "git commit -m \"$(cat <<'EOF'\nfeat: x\n\ndon't stop\n\n"
    '🤖 Generated with [Claude Code](https://claude.com/claude-code)\nEOF\n)"'
)


@pytest.mark.parametrize(
    "command",
    [
        f"git commit -m 'feat: x' -m '{TRAILER}'",
        f"git commit -am 'feat: x\n\n{TRAILER}'",
        f"git commit '-mfeat: x\n\n{TRAILER}'",
        f"git commit --message='{TRAILER}'",
        f"git commit -m 'feat: x' --trailer '{TRAILER}'",
        "git commit -m 'feat: x\n\nClaude-Session: https://claude.ai/code/session_01abc'",
        HEREDOC_COMMIT,
        f"git commit -F - <<'EOF'\nfeat: x\n\n{TRAILER}\nEOF",
        f"cat > msg.txt <<'EOF'\nfeat: x\n\n{TRAILER}\nEOF\ngit commit -F msg.txt",
        f"git add a.txt && FOO=1 git -C . commit -m 'x' -m '{TRAILER}'",
        f"git commit \\\n  -m 'feat: x' \\\n  -m '{TRAILER}'",
        'git commit -m "$(cat <<\'EOF\'\nfeat: x\n\nSays "hi".\n\nClaude-Session: https://x\nEOF\n)"',
    ],
)
def test_attribution_trips_on_commit(repo, command):
    reason = denied(run_hook(command, repo, on=[ATTRIBUTION]))
    assert reason and "attribution line" in reason


def test_attribution_reads_message_file(repo, tmp_path):
    msg = tmp_path / "msg.txt"
    msg.write_text(f"feat: x\n\n{TRAILER}\n")
    assert denied(run_hook(f"git commit -F {msg}", repo, on=[ATTRIBUTION]))
    assert denied(run_hook(f"git commit --file={msg}", repo, on=[ATTRIBUTION]))
    msg.write_text("feat: x\n\nPlain body.\n")
    assert run_hook(f"git commit -F {msg}", repo, on=[ATTRIBUTION]) is None


@pytest.mark.parametrize(
    "command",
    [
        "gh pr create --title x --body 'Body\n\nClaude-Session: https://claude.ai/code/session_1'",
        f"gh pr create -t x -b '{TRAILER}'",
        "gh pr create --title x --body-file - <<'EOF'\n🤖 Generated with Claude Code\nEOF",
        f"gh pr merge 7 --squash --body '{TRAILER}'",
        f"gh pr edit 7 --body='{TRAILER}'",
        f"gh pr create --title 'feat: x' \\\n  --body '{TRAILER}'",
    ],
)
def test_attribution_trips_on_gh_pr(repo, command):
    assert denied(run_hook(command, repo, on=[ATTRIBUTION]))


def test_attribution_reads_body_file(repo, tmp_path):
    body = tmp_path / "body.md"
    body.write_text(f"Summary\n\n{TRAILER}\n")
    assert denied(run_hook(f"gh pr create -t x -F {body}", repo, on=[ATTRIBUTION]))


@pytest.mark.parametrize(
    "command",
    [
        "git commit -m 'feat: plain message' -m 'Body with no trailer.'",
        "git commit -m \"$(cat <<'EOF'\nfeat: x\n\nPlain body.\nEOF\n)\"",
        "gh pr create --title x --body 'Plain body'",
        "gh pr view 7 --json body",
        f"git log --grep '{TRAILER}'",
        f"echo '{TRAILER}'",
    ],
)
def test_attribution_passes_clean(repo, command):
    assert run_hook(command, repo, on=[ATTRIBUTION]) is None


def test_attribution_off_by_default(repo):
    assert run_hook(f"git commit -m x -m '{TRAILER}'", repo, on=[]) is None
    assert run_hook(f"gh pr create -b '{TRAILER}'", repo, on=[]) is None


def test_attribution_repo_override(repo):
    _git(repo, "config", "techne.blockAttributionTrailers", "false")
    assert run_hook(f"git commit -m x -m '{TRAILER}'", repo, on=[ATTRIBUTION]) is None
    assert run_hook(f"gh pr create -b '{TRAILER}'", repo, on=[ATTRIBUTION]) is None


def test_compound_command_reports_each_tool(repo):
    command = f"git commit -m x -m '{TRAILER}' && gh pr create -b '{TRAILER}'"
    reason = denied(run_hook(command, repo, on=[ATTRIBUTION]))
    assert reason and "commit message" in reason and "gh pr create" in reason


# --- COMMITS.md ----------------------------------------------------------------


@pytest.fixture
def scratch(repo):
    (repo / "COMMITS.md").write_text("plan\n")
    (repo / "b.txt").write_text("b\n")
    return repo


@pytest.mark.parametrize(
    "command",
    [
        "git add .",
        "git add -A",
        "git add --all",
        "git add COMMITS.md",
        "git add ./COMMITS.md b.txt",
        "git add '*.md'",
    ],
)
def test_commits_md_trips_on_add(scratch, command):
    reason = denied(run_hook(command, scratch, on=[COMMITS_MD]))
    assert reason and "COMMITS.md" in reason


def test_commits_md_trips_across_line_continuation(scratch):
    assert denied(run_hook("git add \\\n  b.txt \\\n  COMMITS.md", scratch, on=[COMMITS_MD]))


def test_quoted_heredoc_marker_does_not_hide_later_commands(scratch):
    command = "git commit -m 'docs: the <<EOF idiom'\ngit add COMMITS.md"
    assert denied(run_hook(command, scratch, on=[COMMITS_MD]))


def test_commits_md_trips_through_cd(scratch, tmp_path):
    assert denied(run_hook(f"cd {scratch} && git add .", tmp_path, on=[COMMITS_MD]))
    assert denied(run_hook(f"git -C {scratch} add -A", tmp_path, on=[COMMITS_MD]))


def test_commits_md_trips_in_subdirectory(repo):
    (repo / "docs").mkdir()
    (repo / "docs" / "COMMITS.md").write_text("plan\n")
    assert denied(run_hook("git add docs", repo, on=[COMMITS_MD]))


@pytest.mark.parametrize(
    "command",
    [
        "git add b.txt",
        "git add . ':!COMMITS.md'",
        "git add -A -- . ':(exclude)COMMITS.md'",
        "git status",
    ],
)
def test_commits_md_passes_clean_add(scratch, command):
    assert run_hook(command, scratch, on=[COMMITS_MD]) is None


def test_commits_md_passes_when_gitignored(scratch):
    (scratch / ".gitignore").write_text("COMMITS.md\n")
    assert run_hook("git add .", scratch, on=[COMMITS_MD]) is None


def test_commits_md_trips_on_commit_of_staged_file(scratch):
    _git(scratch, "add", "COMMITS.md")
    reason = denied(run_hook("git commit -m 'feat: x'", scratch, on=[COMMITS_MD]))
    assert reason and "would include COMMITS.md" in reason


def test_commits_md_trips_on_commit_all_of_tracked_file(scratch):
    _git(scratch, "add", "COMMITS.md")
    _git(scratch, "commit", "-qm", "track it")
    (scratch / "COMMITS.md").write_text("edited\n")
    assert run_hook("git commit -m x", scratch, on=[COMMITS_MD]) is None
    assert denied(run_hook("git commit -am x", scratch, on=[COMMITS_MD]))
    assert denied(run_hook("git commit -m x -- COMMITS.md", scratch, on=[COMMITS_MD]))
    assert denied(run_hook("git commit -m x .", scratch, on=[COMMITS_MD]))
    assert run_hook("git commit -m x -- a.txt", scratch, on=[COMMITS_MD]) is None


def test_commits_md_passes_clean_commit(scratch):
    _git(scratch, "add", "b.txt")
    assert run_hook("git commit -m x", scratch, on=[COMMITS_MD]) is None


def test_commits_md_off_by_default(scratch):
    assert run_hook("git add .", scratch, on=[]) is None
    _git(scratch, "add", "COMMITS.md")
    assert run_hook("git commit -m x", scratch, on=[]) is None


def test_commits_md_repo_override(scratch):
    _git(scratch, "config", "techne.blockCommitsMd", "false")
    assert run_hook("git add .", scratch, on=[COMMITS_MD]) is None


# --- main checkout -------------------------------------------------------------


@pytest.fixture
def linked(repo, tmp_path):
    wt = tmp_path / "wt"
    _git(repo, "worktree", "add", "-q", str(wt))
    return wt


def test_main_checkout_warns_with_linked_worktree(repo, linked):
    out = run_hook("git commit -m x", repo, on=[MAIN_CHECKOUT])
    message = warned(out)
    assert message and str(linked) in message


def test_main_checkout_passes_inside_worktree(repo, linked):
    assert run_hook("git commit -m x", linked, on=[MAIN_CHECKOUT]) is None


def test_main_checkout_passes_without_worktrees(repo):
    assert run_hook("git commit -m x", repo, on=[MAIN_CHECKOUT]) is None


def test_main_checkout_ignores_non_commit(repo, linked):
    assert run_hook("git status && git add a.txt", repo, on=[MAIN_CHECKOUT]) is None


def test_main_checkout_off_by_default(repo, linked):
    assert run_hook("git commit -m x", repo, on=[]) is None


def test_main_checkout_repo_override(repo, linked):
    _git(repo, "config", "techne.warnMainCheckoutCommit", "false")
    assert run_hook("git commit -m x", repo, on=[MAIN_CHECKOUT]) is None


def test_deny_outranks_warning(repo, linked):
    reason = denied(run_hook(f"git commit -m x -m '{TRAILER}'", repo))
    assert reason and "main checkout" not in reason


# --- parsing and wiring --------------------------------------------------------


def test_outside_a_repo_is_silent(tmp_path):
    assert run_hook("git add . && git commit -m x", tmp_path) is None


def test_unparseable_command_falls_back_to_raw_scan(repo):
    command = f"git commit -m 'unclosed {TRAILER}"
    assert denied(run_hook(command, repo, on=[ATTRIBUTION]))
    _git(repo, "config", "techne.blockAttributionTrailers", "false")
    assert run_hook(command, repo, on=[ATTRIBUTION]) is None


def _handlers() -> list[dict]:
    config = json.loads(HOOKS_JSON.read_text())
    return [h for group in config["hooks"]["PreToolUse"] for h in group["hooks"]]


def run_handler(handler: dict, command: str, cwd: pathlib.Path, *, on) -> dict | None:
    """Run a hooks.json command through sh, as Claude Code does for a shell-form hook."""
    shell = handler["command"].replace("${CLAUDE_PLUGIN_ROOT}", str(PLUGIN))
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_PLUGIN_OPTION_")}
    env.update({f"CLAUDE_PLUGIN_OPTION_{key.upper()}": "true" for key in on})
    payload = json.dumps({"cwd": str(cwd), "tool_input": {"command": command}})
    proc = subprocess.run(
        ["sh", "-c", shell], input=payload, capture_output=True, text=True, env=env, check=False
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout) if proc.stdout.strip() else None


def test_hooks_json_runs_one_unfiltered_handler():
    # No `if`: Claude Code's `Bash(git *)` filter skips `time git ...` and `sudo git ...`.
    (handler,) = _handlers()
    assert "if" not in handler
    assert '"${CLAUDE_PLUGIN_ROOT}/hooks/git_guards.py"' in handler["command"]
    for key in ALL:
        assert f"$CLAUDE_PLUGIN_OPTION_{key.upper()}" in handler["command"]


@pytest.mark.parametrize("key", ALL)
def test_hooks_json_handler_runs_the_guard_when_one_option_is_on(repo, key):
    (repo / "COMMITS.md").write_text("plan\n")
    (handler,) = _handlers()
    out = run_handler(handler, f"time git add . && git commit -m x -m '{TRAILER}'", repo, on=[key])
    if key == MAIN_CHECKOUT:
        assert out is None  # no linked worktree, so nothing to warn about
    else:
        assert denied(out)


def test_hooks_json_handler_skips_python_when_all_off(repo, tmp_path):
    (handler,) = _handlers()
    shell = handler["command"].replace("${CLAUDE_PLUGIN_ROOT}", str(PLUGIN))
    empty = tmp_path / "bin"
    empty.mkdir()
    proc = subprocess.run(
        ["/bin/sh", "-c", shell],
        input="{}",
        capture_output=True,
        text=True,
        env={"PATH": str(empty)},
        check=False,
    )
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, "", "")


def test_manifest_options_match_the_guard_and_default_off():
    options = json.loads(MANIFEST.read_text())["userConfig"]
    assert set(options) == set(ALL)
    for spec in options.values():
        assert spec["type"] == "boolean"
        assert spec["default"] is False


# --- parser edge cases ---------------------------------------------------------


def test_comment_with_apostrophe_does_not_hide_add(scratch):
    command = "# don't forget\ngit add -A && git commit -F - <<'EOF'\nIt's done\nEOF"
    assert denied(run_hook(command, scratch, on=[COMMITS_MD]))


def test_hash_inside_a_word_is_not_a_comment(scratch):
    assert denied(run_hook("git add foo#bar COMMITS.md", scratch, on=[COMMITS_MD]))
    assert denied(
        run_hook(
            f"gh pr create -t x --body See#89 -b '{TRAILER}'",
            scratch,
            on=[ATTRIBUTION],
        )
    )


def test_ansi_c_quoted_message(repo):
    command = "git commit -m $'feat: x\\n\\nit\\'s\\nCo-Authored-By: Claude <x>'"
    assert denied(run_hook(command, repo, on=[ATTRIBUTION]))


def test_trailer_equals_form(repo):
    command = "git commit -m x --trailer 'Co-authored-by=Claude <noreply@anthropic.com>'"
    assert denied(run_hook(command, repo, on=[ATTRIBUTION]))


def test_message_file_rewritten_in_the_same_command(repo):
    (repo / "msg.txt").write_text("feat: clean\n")
    command = "printf 'feat: x\\n\\nCo-Authored-By: Claude\\n' > msg.txt && git commit -F msg.txt"
    assert denied(run_hook(command, repo, on=[ATTRIBUTION]))
    assert run_hook("git commit -F msg.txt", repo, on=[ATTRIBUTION]) is None


def test_unrelated_heredoc_does_not_block_a_plain_commit(repo):
    command = f"cat > notes.md <<'EOF'\nWe ban {TRAILER}\nEOF\ngit commit -m 'feat: x'"
    assert run_hook(command, repo, on=[ATTRIBUTION]) is None


def test_gh_global_repo_flag(repo):
    command = f"gh -R owner/repo pr create --title x --body '{TRAILER}'"
    assert denied(run_hook(command, repo, on=[ATTRIBUTION]))


def test_main_checkout_with_space_in_path(tmp_path):
    main = tmp_path / "sp ace"
    main.mkdir()
    _git(main, "init", "-q")
    _git(main, "commit", "-q", "--allow-empty", "-m", "init")
    _git(main, "worktree", "add", "-q", str(tmp_path / "wt"))
    assert warned(run_hook("git commit -m x", main, on=[MAIN_CHECKOUT]))


def test_non_ascii_path_to_commits_md(repo):
    (repo / "café").mkdir()
    (repo / "café" / "COMMITS.md").write_text("plan\n")
    assert denied(run_hook("git add .", repo, on=[COMMITS_MD]))
    _git(repo, "add", "-f", "café/COMMITS.md")
    assert denied(run_hook("git commit -m x", repo, on=[COMMITS_MD]))


def test_rough_split_still_runs_the_commits_md_check(scratch):
    command = "git add -A && echo 'unbalanced"
    assert denied(run_hook(command, scratch, on=[COMMITS_MD]))


def test_crash_in_one_check_keeps_earlier_denies(repo, monkeypatch, capsys):
    import importlib.util

    spec = importlib.util.spec_from_file_location("techne_git_guards", GUARDS)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    def boom(self, cmd):
        raise RuntimeError("boom")

    monkeypatch.setattr(mod.Guards, "check_main_checkout", boom)
    for key in ALL:
        monkeypatch.setenv(f"CLAUDE_PLUGIN_OPTION_{key.upper()}", "true")
    payload = json.dumps(
        {"cwd": str(repo), "tool_input": {"command": f"git commit -m '{TRAILER}'"}}
    )
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO(payload))
    monkeypatch.setattr(sys, "argv", ["git_guards.py"])
    assert mod.main() == 0
    out = capsys.readouterr()
    assert denied(json.loads(out.out)) and "boom" in out.err


# --- round-two edges -----------------------------------------------------------


def test_cd_and_dash_c_targets_expand_variables(scratch, tmp_path, monkeypatch):
    monkeypatch.setenv("TECHNE_TEST_REPO", str(scratch))
    assert denied(run_hook('cd "$TECHNE_TEST_REPO" && git add .', tmp_path, on=[COMMITS_MD]))
    assert denied(run_hook('git -C "$TECHNE_TEST_REPO" add .', tmp_path, on=[COMMITS_MD]))


def test_unexpandable_cd_target_keeps_the_current_repo(scratch):
    command = 'cd "$(git rev-parse --show-toplevel)" && git add .'
    assert denied(run_hook(command, scratch, on=[COMMITS_MD]))


def test_short_message_file_name_is_matched_as_a_word(repo):
    (repo / "m").write_text("hello\n")
    command = f"echo 'ma: {TRAILER} is banned' >> notes.txt; git commit -F m"
    assert run_hook(command, repo, on=[ATTRIBUTION]) is None


def test_strip_step_before_commit_is_not_blocked(repo):
    (repo / "msg.txt").write_text(f"feat: x\n\n{TRAILER}\n")
    command = f"grep -v '{TRAILER}' msg.txt > clean.txt && git commit -F clean.txt"
    assert run_hook(command, repo, on=[ATTRIBUTION]) is None


def test_message_piped_from_echo_on_stdin(repo):
    command = f"echo 'feat: x\n\n{TRAILER}' | git commit -F -"
    assert denied(run_hook(command, repo, on=[ATTRIBUTION]))


def test_pathspec_commit_in_a_repo_without_commits(tmp_path):
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    _git(fresh, "init", "-q")
    (fresh / "COMMITS.md").write_text("plan\n")
    (fresh / "b").write_text("b\n")
    _git(fresh, "add", "-f", "COMMITS.md", "b")
    assert denied(run_hook("git commit -m init .", fresh, on=[COMMITS_MD]))


def test_pathspec_from_file_commit(scratch):
    _git(scratch, "add", "COMMITS.md")
    _git(scratch, "commit", "-qm", "track it")
    (scratch / "COMMITS.md").write_text("edited\n")
    (scratch / "list").write_text("COMMITS.md\n")
    assert denied(run_hook("git commit --pathspec-from-file=list -m x", scratch, on=[COMMITS_MD]))


@pytest.mark.parametrize(
    "command",
    [
        "time git add .",
        "sudo -u me git add .",
        "nice -n 5 git add .",
        "timeout 30 git add .",
        "git stage .",
    ],
)
def test_wrappers_and_stage_alias(scratch, command):
    assert denied(run_hook(command, scratch, on=[COMMITS_MD]))


def test_abbreviated_long_option(repo):
    assert denied(run_hook(f"git commit --mess '{TRAILER}'", repo, on=[ATTRIBUTION]))


def test_gh_repo_flag_after_pr(repo):
    command = f"gh pr --repo o/r create -t x -b '{TRAILER}'"
    assert denied(run_hook(command, repo, on=[ATTRIBUTION]))


def test_crash_in_one_subcommand_still_checks_the_next(scratch, monkeypatch, capsys):
    import importlib.util

    spec = importlib.util.spec_from_file_location("techne_git_guards_2", GUARDS)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    def boom(self, cmd):
        raise RuntimeError("boom")

    monkeypatch.setattr(mod.Guards, "check_main_checkout", boom)
    for key in ALL:
        monkeypatch.setenv(f"CLAUDE_PLUGIN_OPTION_{key.upper()}", "true")
    command = "git commit -m x && git add COMMITS.md"
    payload = json.dumps({"cwd": str(scratch), "tool_input": {"command": command}})
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO(payload))
    monkeypatch.setattr(sys, "argv", ["git_guards.py"])
    assert mod.main() == 0
    out = capsys.readouterr()
    assert "COMMITS.md" in (denied(json.loads(out.out)) or "") and "boom" in out.err
