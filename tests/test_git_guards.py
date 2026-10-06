"""Tests for git_guards.py, the opt-in git guards the phylax mod runs on each git or gh command.

Each case feeds the guard the PreToolUse JSON the mod sends on stdin and reads the decision
from stdout, against a real throwaway repo. Every guard has a trip case, a clean
case, a case with its option off, and a case with the per-repo override set.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import time

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "plugins" / "phylax"
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
    _git(repo, "config", "phylax.blockAttributionTrailers", "false")
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
    _git(scratch, "config", "phylax.blockCommitsMd", "false")
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
    _git(repo, "config", "phylax.warnMainCheckoutCommit", "false")
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
    _git(repo, "config", "phylax.blockAttributionTrailers", "false")
    assert run_hook(command, repo, on=[ATTRIBUTION]) is None


def _handlers() -> list[dict]:
    config = json.loads(HOOKS_JSON.read_text())
    return [h for group in config["hooks"]["PreToolUse"] for h in group["hooks"]]


def run_handler(handler: dict, command: str, cwd: pathlib.Path, *, on, env_extra=None, **fields):
    """Run the hooks.json fallback through sh, as Claude Code does for a shell-form hook."""
    shell = handler["command"].replace("${CLAUDE_PLUGIN_ROOT}", str(PLUGIN))
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("CLAUDE_PLUGIN_OPTION_", "PHYLAX_"))
    }
    env.update({f"CLAUDE_PLUGIN_OPTION_{key.upper()}": "true" for key in on})
    env.update(env_extra or {})
    payload = json.dumps({"cwd": str(cwd), "tool_input": {"command": command}, **fields})
    proc = subprocess.run(
        ["sh", "-c", shell], input=payload, capture_output=True, text=True, env=env, check=False
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout) if proc.stdout.strip() else None


def test_hooks_json_names_the_module_and_keeps_the_fallback():
    # register.ts checks the main thread; the PreToolUse hook covers subagents, and every call
    # when the module did not load (an older Claude Code, an organization's mod policy).
    config = json.loads(HOOKS_JSON.read_text())
    assert config["modules"] == ["./register.ts"]
    (handler,) = _handlers()
    assert "if" not in handler  # `Bash(git *)` would skip `time git ...`
    assert '"${CLAUDE_PLUGIN_ROOT}/hooks/git_guards.py"' in handler["command"]
    for key in ALL:
        assert f"$CLAUDE_PLUGIN_OPTION_{key.upper()}" in handler["command"]
    module = (PLUGIN / "hooks" / "register.ts").read_text()
    assert "hooks/git_guards.py" in module and "PHYLAX_GUARD_CHECKED" in module


@pytest.mark.parametrize("key", ALL)
def test_fallback_runs_the_guard_when_one_option_is_on(repo, key):
    (repo / "COMMITS.md").write_text("plan\n")
    (handler,) = _handlers()
    out = run_handler(handler, f"time git add . && git commit -m x -m '{TRAILER}'", repo, on=[key])
    if key == MAIN_CHECKOUT:
        assert out is None  # no linked worktree, so nothing to warn about
    else:
        assert denied(out)


def test_fallback_skips_python_when_all_off(tmp_path):
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


CHECKED = {"PHYLAX_GUARD_CHECKED": "toolu_1"}


def test_fallback_stands_down_for_the_call_the_mod_checked(repo):
    (handler,) = _handlers()
    command = f"git commit -m x -m '{TRAILER}'"
    out = run_handler(
        handler, command, repo, on=[ATTRIBUTION], env_extra=CHECKED, tool_use_id="toolu_1"
    )
    assert out is None


@pytest.mark.parametrize(
    "fields",
    [
        {"tool_use_id": "toolu_2"},  # another call, made while the checked one runs
        {"tool_use_id": "toolu_9", "agent_id": "agent-7"},  # a subagent's: the mod leaves it here
        {},
    ],
)
def test_fallback_checks_every_call_the_mod_did_not(repo, fields):
    (handler,) = _handlers()
    command = f"git commit -m x -m '{TRAILER}'"
    assert denied(
        run_handler(handler, command, repo, on=[ATTRIBUTION], env_extra=CHECKED, **fields)
    )


def run_raw(command: str, cwd: pathlib.Path, *, on, path_prefix: pathlib.Path | None = None):
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("CLAUDE_PLUGIN_OPTION_", "PHYLAX_"))
    }
    env.update({f"CLAUDE_PLUGIN_OPTION_{key.upper()}": "true" for key in on})
    if path_prefix:
        env["PATH"] = f"{path_prefix}:{env['PATH']}"
    payload = json.dumps({"cwd": str(cwd), "tool_input": {"command": command}})
    return subprocess.run(
        [GUARD_PYTHON, str(GUARDS)],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


@pytest.fixture
def hanging_status(tmp_path):
    """A `git` on PATH that hangs on `status` past the guard's per-call timeout."""
    real = subprocess.run(
        ["sh", "-c", "command -v git"], capture_output=True, text=True, check=True
    )
    shim = tmp_path / "shim"
    shim.mkdir()
    script = shim / "git"
    script.write_text(
        "#!/bin/sh\n"
        'for a in "$@"; do [ "$a" = status ] && exec sleep 30; done\n'
        f'exec {real.stdout.strip()} "$@"\n'
    )
    script.chmod(0o755)
    return shim


def test_a_git_that_hangs_fails_closed_while_a_blocking_guard_is_on(scratch, hanging_status):
    _git(scratch, "add", "COMMITS.md")
    proc = run_raw("git commit -m x", scratch, on=[COMMITS_MD], path_prefix=hanging_status)
    assert proc.returncode == 2
    assert "timed out" in proc.stderr
    assert not proc.stdout.strip()


def test_one_hung_git_costs_one_timeout(scratch, hanging_status):
    _git(scratch, "add", "COMMITS.md")
    command = "git commit -m a; git commit -m b; git commit -m c; git commit -m d"
    started = time.monotonic()
    proc = run_raw(command, scratch, on=[COMMITS_MD], path_prefix=hanging_status)
    assert proc.returncode == 2
    assert time.monotonic() - started < 15  # four commits would wait 20 s without the latch


def test_a_failed_check_beside_a_warning_still_fails(repo, linked):
    # One subcommand's check breaks (a NUL in its path); the next one warns. The warning must
    # not pass for success, or the broken check's command would run unchecked.
    command = f"git -C '\x00' commit -m x; git -C {repo} commit -m y"
    proc = run_raw(command, repo, on=[COMMITS_MD, MAIN_CHECKOUT])
    assert proc.returncode == 2
    assert warned(json.loads(proc.stdout))
    only_warn = run_raw(command, repo, on=[MAIN_CHECKOUT])
    assert only_warn.returncode == 1


def test_manifest_options_match_the_guard_and_default_off():
    options = json.loads(MANIFEST.read_text())["userConfig"]
    # restart_on_update belongs to stale_restart.py, tested in test_stale_restart.py.
    assert set(options) - {"restart_on_update"} == set(ALL)
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

    spec = importlib.util.spec_from_file_location("phylax_git_guards", GUARDS)
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

    spec = importlib.util.spec_from_file_location("phylax_git_guards_2", GUARDS)
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


# --- round-three edges ---------------------------------------------------------


def test_backslash_quoted_heredoc_delimiter(repo):
    command = f"git commit -F - <<\\EOF\nfix\n\n{TRAILER}\nEOF"
    assert denied(run_hook(command, repo, on=[ATTRIBUTION]))


def test_add_with_an_ignored_path_still_checks_the_rest(scratch):
    (scratch / ".gitignore").write_text("build/\n")
    (scratch / "build").mkdir()
    (scratch / "build" / "x").write_text("x\n")
    assert denied(run_hook("git add . build", scratch, on=[COMMITS_MD]))


def test_gh_pr_new_alias(repo):
    assert denied(run_hook(f"gh pr new --title x --body '{TRAILER}'", repo, on=[ATTRIBUTION]))


def test_variable_set_earlier_in_the_command(scratch, tmp_path):
    clean = tmp_path / "clean"
    clean.mkdir()
    _git(clean, "init", "-q")
    assert run_hook(f'W={clean}; git -C "$W" add -A', scratch, on=[COMMITS_MD]) is None
    assert denied(run_hook(f'W={scratch}; git -C "$W" add -A', clean, on=[COMMITS_MD]))
    assert denied(run_hook(f'export W={scratch} && cd "$W" && git add .', clean, on=[COMMITS_MD]))


def test_subshell_cd_does_not_leak(scratch):
    assert denied(run_hook("(cd /tmp && true); git add .", scratch, on=[COMMITS_MD]))


@pytest.mark.parametrize(
    "template",
    [
        "env -C {repo} git add .",
        "env --chdir={repo} git add .",
        "sudo -D {repo} git add .",
        "exec -a foo git -C {repo} add .",
    ],
)
def test_wrappers_that_change_directory(scratch, tmp_path, template):
    command = template.format(repo=scratch)
    assert denied(run_hook(command, tmp_path, on=[COMMITS_MD]))


def test_xargs_add_is_caught_at_commit(scratch):
    _git(scratch, "add", "COMMITS.md")  # what `echo COMMITS.md | xargs git add` would do
    assert denied(run_hook("git commit -m x", scratch, on=[COMMITS_MD]))


def test_process_substitution_message(repo):
    command = f"git commit -F <(printf 'fix\\n\\n{TRAILER}\\n')"
    assert denied(run_hook(command, repo, on=[ATTRIBUTION]))


def test_optional_value_short_flags_are_not_split(scratch):
    _git(scratch, "add", "COMMITS.md")
    _git(scratch, "commit", "-qm", "track it")
    (scratch / "COMMITS.md").write_text("edited\n")
    assert run_hook("git commit -uall -m x", scratch, on=[COMMITS_MD]) is None
    assert run_hook("git commit -SF00 -m x", scratch, on=[ATTRIBUTION, COMMITS_MD]) is None


# --- round-four edges ----------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "{ git add COMMITS.md; }",
        "if git diff --quiet; then :; else git add COMMITS.md; fi",
        "! git add COMMITS.md",
        "while false; do :; done; until true; do :; done; git add .",
    ],
)
def test_shell_keywords_before_a_command(scratch, command):
    assert denied(run_hook(command, scratch, on=[COMMITS_MD]))


def test_keyword_before_a_commit(repo):
    command = f"if true; then git commit -m x -m '{TRAILER}'; fi"
    assert denied(run_hook(command, repo, on=[ATTRIBUTION]))


@pytest.mark.parametrize(
    "command",
    [
        f"time -p git commit -m x -m '{TRAILER}'",
        f"sudo -n git commit -m x -m '{TRAILER}'",
        f"command -p git commit -m x -m '{TRAILER}'",
    ],
)
def test_wrapper_flags_without_values(repo, command):
    assert denied(run_hook(command, repo, on=[ATTRIBUTION]))


def test_xargs_prompt_flag(scratch):
    assert denied(run_hook("xargs -p git add COMMITS.md", scratch, on=[COMMITS_MD]))


@pytest.mark.parametrize("command", ["cd -P . && git add .", "cd -- . && git add ."])
def test_cd_flags(scratch, command):
    assert denied(run_hook(command, scratch, on=[COMMITS_MD]))


def test_cd_dash_and_pushd_popd(scratch, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    assert denied(run_hook(f"cd {other} && cd - && git add .", scratch, on=[COMMITS_MD]))
    assert denied(run_hook(f"pushd {scratch} && git add .", tmp_path, on=[COMMITS_MD]))
    command = f"pushd {other} && popd && git add ."
    assert denied(run_hook(command, scratch, on=[COMMITS_MD]))


@pytest.mark.parametrize("form", ["$(cat body.md)", "$(< body.md)"])
def test_message_read_through_cat_substitution(repo, form):
    (repo / "body.md").write_text("Summary\n\n🤖 Generated with Claude Code\n")
    command = f'gh pr create --title x --body "{form}"'
    assert denied(run_hook(command, repo, on=[ATTRIBUTION]))
    (repo / "msg.txt").write_text(f"feat: x\n\n{TRAILER}\n")
    assert denied(run_hook('git commit -m "$(cat msg.txt)"', repo, on=[ATTRIBUTION]))


def test_heredoc_to_an_unrelated_file_does_not_block(repo):
    (repo / "body2.md").write_text("feat: clean\n")
    command = "cat > /tmp/notes <<EOF\nnever add Claude-Session lines\nEOF\ngit commit -F body2.md"
    assert run_hook(command, repo, on=[ATTRIBUTION]) is None


def test_heredoc_to_the_message_file_is_scanned(repo):
    command = f"cat > m.txt <<'EOF'\nfeat: x\n\n{TRAILER}\nEOF\ngit commit -F m.txt"
    assert denied(run_hook(command, repo, on=[ATTRIBUTION]))


def test_lowercase_commits_md_doc_page_is_allowed(repo):
    (repo / "docs").mkdir()
    (repo / "docs" / "commits.md").write_text("# Commit conventions\n")
    assert run_hook("git add .", repo, on=[COMMITS_MD]) is None
    _git(repo, "add", "docs/commits.md")
    assert run_hook("git commit -m docs", repo, on=[COMMITS_MD]) is None


def test_staged_rename_into_commits_md(scratch):
    _git(scratch, "add", "b.txt")
    _git(scratch, "commit", "-qm", "b")
    _git(scratch, "mv", "-f", "b.txt", "COMMITS.md")
    assert denied(run_hook("git commit -m x", scratch, on=[COMMITS_MD]))


# --- round-five edges ----------------------------------------------------------


def test_heredoc_on_a_continued_line(repo):
    commit = f"git commit \\\n  -m \"$(cat <<'EOF'\nfeat\n\n{TRAILER}\nEOF\n)\""
    pr = f"gh pr create --title x \\\n  --body \"$(cat <<'EOF'\nSummary\n\n{TRAILER}\nEOF\n)\""
    assert denied(run_hook(commit, repo, on=[ATTRIBUTION]))
    assert denied(run_hook(pr, repo, on=[ATTRIBUTION]))


def test_message_through_a_variable(repo):
    assert denied(run_hook(f"MSG='{TRAILER}'; git commit -m \"$MSG\"", repo, on=[ATTRIBUTION]))
    command = f"MSG=$(cat <<'EOF'\nfeat\n\n{TRAILER}\nEOF\n)\ngit commit -m \"$MSG\""
    assert denied(run_hook(command, repo, on=[ATTRIBUTION]))


def test_nested_quotes_inside_substitution(repo):
    command = (
        'git commit -m "$(printf \\"%s\\\\n\\\\n%s\\" \\"feat\\" \\"Co-Authored-By: Claude\\")"'
    )
    assert denied(run_hook(command, repo, on=[ATTRIBUTION]))


def test_removing_a_tracked_commits_md_passes(scratch):
    _git(scratch, "add", "COMMITS.md")
    _git(scratch, "commit", "-qm", "oops")
    _git(scratch, "rm", "-q", "--cached", "COMMITS.md")
    assert run_hook("git commit -m 'chore: untrack'", scratch, on=[COMMITS_MD]) is None
    _git(scratch, "reset", "-q")
    (scratch / "COMMITS.md").unlink()
    assert run_hook("git commit -am 'chore: drop'", scratch, on=[COMMITS_MD]) is None


def test_heredoc_commit_idiom_is_not_a_message_file(repo):
    command = (
        "printf 'see Claude-Session docs\\n' > notes.md && "
        "git commit -m \"$(cat <<'EOF'\nfeat: x\nEOF\n)\""
    )
    assert run_hook(command, repo, on=[ATTRIBUTION]) is None


@pytest.mark.parametrize(
    "command",
    [
        f"cat > ./msg.txt <<'EOF'\nfeat\n\n{TRAILER}\nEOF\ngit commit -F msg.txt",
        f"cat > ./b.md <<'EOF'\nSummary\n\n{TRAILER}\nEOF\ngh pr create -t x -F b.md",
    ],
)
def test_message_file_paths_are_normalized(repo, command):
    assert denied(run_hook(command, repo, on=[ATTRIBUTION]))


@pytest.mark.parametrize(
    "command",
    [
        "echo x > COMMITS.md && git add -A && git commit -m x",
        "touch COMMITS.md && git add .",
    ],
)
def test_commits_md_created_in_the_same_call(repo, command):
    assert denied(run_hook(command, repo, on=[COMMITS_MD]))


def test_created_file_with_an_explicit_add_passes(repo):
    (repo / "b.txt").write_text("b\n")
    assert run_hook("echo x > COMMITS.md && git add b.txt", repo, on=[COMMITS_MD]) is None
