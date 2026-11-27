"""Tests for git_guards.py, the opt-in git guards the phylax mod runs on each git or gh command.

Each case feeds the guard the PreToolUse JSON the mod sends on stdin and reads the decision
from stdout, against a real throwaway repo. Every guard has a trip case, a clean
case, a case with its option off, and a case with the per-repo override set.
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import time

import pytest
from conftest import (
    HOOK_PYTHON,
    _load,
    hook_env,
    hook_handlers,
    hook_shell,
    load_phylax_hooks,
    run_hook_handler,
)

ROOT = pathlib.Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "plugins" / "phylax"
GUARDS = PLUGIN / "hooks" / "git_guards.py"
HOOKS_JSON = PLUGIN / "hooks" / "hooks.json"
MANIFEST = PLUGIN / ".claude-plugin" / "plugin.json"

ATTRIBUTION = "block_attribution_trailers"
COMMITS_MD = "block_commits_md"
FAIL_CLOSED = "phylax: the git guard could not finish its check, so this command was not run."
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
    payload = json.dumps({"cwd": str(cwd), "tool_input": {"command": command}})
    proc = subprocess.run(
        [HOOK_PYTHON, str(GUARDS)],
        input=payload,
        capture_output=True,
        text=True,
        env=hook_env(on),
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout) if proc.stdout.strip() else None


# Claude Code ignores hook JSON that fails its schema, deny included: a top-level `decision` of
# "deny" or "allow" fails it. So a verdict for Claude Code carries no other top-level field.
CLAUDE_DENY_KEYS = {"hookSpecificOutput"}
CLAUDE_WARN_KEYS = {"systemMessage", "hookSpecificOutput"}


def denied(out: dict | None) -> str | None:
    if out and out["hookSpecificOutput"].get("permissionDecision") == "deny":
        assert set(out) == CLAUDE_DENY_KEYS, out
        return out["hookSpecificOutput"]["permissionDecisionReason"]
    return None


def warned(out: dict | None) -> str | None:
    if out and "permissionDecision" not in out["hookSpecificOutput"]:
        assert set(out) == CLAUDE_WARN_KEYS, out
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
    return hook_handlers("phylax", "PreToolUse", "Bash")


def run_handler(handler: dict, command: str, cwd: pathlib.Path, *, on, env_extra=None, **fields):
    """Run the hooks.json fallback through sh, as Claude Code does for a shell-form hook."""
    env = hook_env(on, drop=("PHYLAX_",), **(env_extra or {}))
    payload = json.dumps({"cwd": str(cwd), "tool_input": {"command": command}, **fields})
    proc = run_hook_handler("phylax", handler, payload, env)
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
    shell = hook_shell("phylax", handler, python=None)
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
    env = hook_env(on, drop=("PHYLAX_",))
    if path_prefix:
        env["PATH"] = f"{path_prefix}:{env['PATH']}"
    payload = json.dumps({"cwd": str(cwd), "tool_input": {"command": command}})
    return subprocess.run(
        [HOOK_PYTHON, str(GUARDS)],
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
    assert only_warn.returncode == 0


def test_manifest_options_match_the_guard_and_default_off():
    options = json.loads(MANIFEST.read_text())["userConfig"]
    # restart_on_update belongs to stale_restart.py, tested in test_stale_restart.py;
    # require_subagent_model to model_guard.py, tested in test_model_guard.py; email_* to
    # email_greeting.py, tested in test_email_greeting.py; budget_* to budget.py, tested in
    # test_budget.py.
    # block_background_loops and block_pkill_full to command_shapes.py, tested in
    # test_command_shapes.py.
    others = {
        "restart_on_update",
        "require_subagent_model",
        "email_greeting",
        "block_background_loops",
        "block_pkill_full",
    }
    guards = {k for k in options if k not in others and not k.startswith(("budget_", "email_"))}
    # block_secrets, block_long_bodies and block_gh_implicit_repo live in git_checks.py too,
    # tested in test_secret_guard.py, test_body_gate.py and test_gh_target.py.
    assert guards == {*ALL, "block_secrets", "block_long_bodies", "block_gh_implicit_repo"}
    assert options["email_timezone"] == {
        **options["email_timezone"],
        "type": "string",
        "default": "",
    }
    for key in guards | others:
        assert options[key]["type"] == "boolean"
        assert options[key]["default"] is False


# --- parser edge cases ---------------------------------------------------------


def test_deeply_nested_parentheses_stay_linear(scratch):
    """is_arith looks a bounded way ahead, so thousands of nested `(` cost little."""
    import time

    command = "(" * 6000 + "true" + ")" * 6000 + "; git add COMMITS.md"
    start = time.perf_counter()
    assert denied(run_hook(command, scratch))
    assert time.perf_counter() - start < 10


@pytest.mark.parametrize(
    "command",
    [
        # `((` is arithmetic only when its inner paren closes right before the outer one
        "((cd .); git add COMMITS.md)",
        "((cd .); cat <<EOF\nx\nEOF\n); git add COMMITS.md",
        "(( x = 1 << 2 )); git add COMMITS.md",
        "echo $((1<<2)); git add COMMITS.md",
        "(( x = 1 )); git add -F - <<'EOF'\nbody\nEOF\ngit add COMMITS.md",
        # a parenthesised sub-expression or a very long expression in arithmetic: still a shift
        "y=$(( (a<<b) ))\ngit add COMMITS.md\nb",
        "(( x = (1<<2) ))\ngit add COMMITS.md\n2",
        "(( x = " + " + ".join(["1"] * 900) + " << 2 ))\ngit add COMMITS.md\n2",
        # a shift by a name, and `#` inside ${...}, are no heredoc and no comment
        "(( m = 1 << n ))\ngit add COMMITS.md",
        "echo $((1<<n)); git add COMMITS.md",
        "echo ${x:- #}; git add COMMITS.md",
        "echo ${x:-((}; git add COMMITS.md",
        # a heredoc after a closed ${...} is still one
        f"echo ${{x}}; git commit -F - <<'EOF'\nfeat: x\n\n{TRAILER}\nEOF",
        f"(( m = 1 << n ))\ngit commit -F - <<'EOF'\nfeat: x\n\n{TRAILER}\nEOF",
        f"echo ${{x:- #}}\ngit commit -F - <<'EOF'\nfeat: x\n\n{TRAILER}\nEOF",
    ],
)
def test_parentheses_and_arithmetic_do_not_hide_what_follows(scratch, command):
    assert denied(run_hook(command, scratch))


@pytest.mark.parametrize(
    "command",
    [
        "/usr/bin/sudo -n git add COMMITS.md",
        "/usr/bin/env A=1 git add COMMITS.md",
        "setsid git add COMMITS.md",
        "stdbuf -o L git add COMMITS.md",
        "timeout --kill-after 5 10 git add COMMITS.md",
    ],
)
def test_wrappers_by_path_and_long_options_are_looked_through(scratch, command):
    assert denied(run_hook(command, scratch))


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


def _in_process(monkeypatch):
    """The entry and the checks module it imports, loaded fresh in this process."""
    return load_phylax_hooks(monkeypatch, "git_guards", "git_checks")


def test_crash_in_one_check_keeps_earlier_denies(repo, monkeypatch, capsys):
    entry, checks = _in_process(monkeypatch)

    def boom(self, cmd):
        raise RuntimeError("boom")

    monkeypatch.setattr(checks.Guards, "check_main_checkout", boom)
    for key in ALL:
        monkeypatch.setenv(f"CLAUDE_PLUGIN_OPTION_{key.upper()}", "true")
    payload = json.dumps(
        {"cwd": str(repo), "tool_input": {"command": f"git commit -m '{TRAILER}'"}}
    )
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO(payload))
    monkeypatch.setattr(sys, "argv", ["git_guards.py"])
    assert entry.main() == 0
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
    entry, checks = _in_process(monkeypatch)

    def boom(self, cmd):
        raise RuntimeError("boom")

    monkeypatch.setattr(checks.Guards, "check_main_checkout", boom)
    for key in ALL:
        monkeypatch.setenv(f"CLAUDE_PLUGIN_OPTION_{key.upper()}", "true")
    command = "git commit -m x && git add COMMITS.md"
    payload = json.dumps({"cwd": str(scratch), "tool_input": {"command": command}})
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO(payload))
    monkeypatch.setattr(sys, "argv", ["git_guards.py"])
    assert entry.main() == 0
    out = capsys.readouterr()
    assert "COMMITS.md" in (denied(json.loads(out.out)) or "") and "boom" in out.err


# --- the entry's triage, before it loads git_checks.py --------------------------------


@pytest.mark.parametrize(
    ("payload", "skips"),
    [
        ('{"tool_input": {"command": "ls -la"}}', True),
        ('{"tool_input": {"command": "git status"}}', False),
        ('{"tool_input": {"command": "gh pr view 3"}}', False),
        ('{"tool_input": {"command": "\\u0067it add ."}}', False),
        ('{"tool_input": {"command": "ls"}, "cwd": "/srv/github"}', False),
        ("", True),
    ],
)
def test_triage_skips_only_input_that_cannot_name_git(payload, skips, monkeypatch):
    entry, _ = _in_process(monkeypatch)
    assert entry.cannot_name_git(payload) is skips


def test_a_command_naming_neither_tool_never_loads_the_checks(tmp_path):
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    for name in ("git_guards.py", "git_options.py"):
        shutil.copy(GUARDS.parent / name, hooks)
    (hooks / "git_checks.py").write_text("raise SystemExit('checks loaded')\n")

    def run(command: str) -> subprocess.CompletedProcess:
        payload = json.dumps({"cwd": str(tmp_path), "tool_input": {"command": command}})
        return subprocess.run(
            [HOOK_PYTHON, str(hooks / "git_guards.py")],
            input=payload,
            capture_output=True,
            text=True,
            env=hook_env(ALL),
            check=False,
        )

    for command in ("ls -la", "echo digit > high.txt"):
        quiet = run(command)
        assert (quiet.returncode, quiet.stdout, quiet.stderr) == (0, "", ""), command
    assert "checks loaded" in run("git status").stderr


@pytest.mark.parametrize("broken", ["git_options.py", "git_checks.py", "hook_output.py"])
def test_a_module_that_cannot_load_fails_closed(tmp_path, broken):
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    for name in ("git_guards.py", "git_options.py", "git_checks.py", "hook_output.py"):
        shutil.copy(GUARDS.parent / name, hooks)
    (hooks / broken).write_text("raise ImportError('broken install')\n")
    payload = json.dumps({"cwd": str(tmp_path), "tool_input": {"command": "git commit -m x"}})
    proc = subprocess.run(
        [HOOK_PYTHON, str(hooks / "git_guards.py")],
        input=payload,
        capture_output=True,
        text=True,
        env=hook_env([ATTRIBUTION], drop=("PHYLAX_",)),
        check=False,
    )
    assert proc.returncode == 2 and "broken install" in proc.stderr


def test_an_escaped_letter_does_not_hide_a_git_command(scratch):
    (handler,) = _handlers()
    payload = json.dumps({"cwd": str(scratch), "tool_input": {"command": "git add -A"}})
    payload = payload.replace('"git add -A"', '"\\u0067it add -A"')
    assert '"\\u0067it' in payload
    proc = run_hook_handler("phylax", handler, payload, hook_env([COMMITS_MD], drop=("PHYLAX_",)))
    assert proc.returncode == 0, proc.stderr
    assert denied(json.loads(proc.stdout))


def test_a_gh_command_in_a_folder_without_git_in_its_name_is_checked(tmp_path_factory):
    (handler,) = _handlers()
    folder = tmp_path_factory.mktemp("plain")
    command = f"gh pr create -t x -b '{TRAILER}'"
    payload = json.dumps({"cwd": str(folder), "tool_input": {"command": command}})
    if "git" in payload.replace(TRAILER, ""):
        pytest.skip("the temporary folder's path names git")
    proc = run_hook_handler("phylax", handler, payload, hook_env([ATTRIBUTION], drop=("PHYLAX_",)))
    assert proc.returncode == 0, proc.stderr
    assert denied(json.loads(proc.stdout))


@pytest.mark.parametrize(
    ("payload", "code"),
    [('{"tool_input": {"command": "git status"', 2), ('{"tool_input": {"command": "ls"', 0)],
)
def test_input_that_is_not_json_fails_closed_only_when_it_could_name_git(payload, code):
    (handler,) = _handlers()
    proc = run_hook_handler("phylax", handler, payload, hook_env(ALL, drop=("PHYLAX_",)))
    assert proc.returncode == code, proc.stderr


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


# --- a session folder that is gone (a removed worktree) --------------------------


def test_a_guarded_command_in_a_gone_folder_is_refused_with_the_reason(tmp_path):
    gone = tmp_path / "removed-worktree"
    reason = denied(run_hook("git commit -m x", gone))
    assert reason and f"runs in {gone}, which is not an existing folder" in reason
    assert "cd to an existing folder" in reason


@pytest.mark.parametrize(
    "command",
    [
        "cd {repo} && git commit -m 'feat: x'",
        "cd ../repo && git commit -m 'feat: x'",
        "git -C {repo} add a.txt",
        "cd {tmp}/git-mirror",
        "git log --oneline -1",
        "gh pr view 1",
        "gh pr create -R o/r -t 'feat: x' -b 'body'",
    ],
)
def test_a_gone_session_folder_still_checks_where_the_command_runs(tmp_path, repo, command):
    gone = tmp_path / "removed-worktree"
    (tmp_path / "git-mirror").mkdir()
    out = run_hook(command.format(repo=repo, tmp=tmp_path), gone)
    assert denied(out) is None


def test_a_gh_pr_body_is_still_scanned_in_a_gone_folder(tmp_path):
    gone = tmp_path / "removed-worktree"
    out = run_hook(f"gh pr create -R o/r -t x -b 'body\n\n{TRAILER}'", gone)
    reason = denied(out)
    assert reason and "attribution" in reason.lower()


def test_a_guard_that_does_not_check_the_command_ignores_a_gone_folder(tmp_path):
    out = run_hook("git add a.txt", tmp_path / "removed-worktree", on=[ATTRIBUTION])
    assert out is None


def test_a_folder_path_through_a_file_is_named(tmp_path):
    (tmp_path / "f").write_text("")
    reason = denied(run_hook(f"git -C {tmp_path}/f/sub commit -m x", tmp_path))
    assert reason and "is not an existing folder" in reason


@pytest.mark.parametrize(
    ("key", "code"),
    [
        (ATTRIBUTION, 2),
        (COMMITS_MD, 2),
        ("block_secrets", 2),
        ("block_long_bodies", 2),
        ("block_gh_implicit_repo", 2),
        (MAIN_CHECKOUT, 0),
    ],
)
def test_input_with_no_folder_fails_closed_for_each_blocking_guard(key, code):
    # Each blocking guard alone makes a check that cannot finish refuse the command (exit 2);
    # the warning alone lets it run (exit 0, since onFailure "block" refuses on exit 1).
    env = hook_env([key], drop=("PHYLAX_",))
    payload = json.dumps({"tool_input": {"command": "git commit -m x"}})
    proc = subprocess.run(
        [HOOK_PYTHON, str(GUARDS)], input=payload, capture_output=True, text=True, env=env
    )
    lines = ["phylax git guard error: the hook input names no folder"]
    if code == 2:
        lines.append(
            f"{FAIL_CLOSED} To switch it off, turn off the phylax option {key} in /config, "
            "or run /phylax:setup."
        )
        assert (proc.returncode, proc.stderr.splitlines(), proc.stdout) == (code, lines, "")
    else:  # the warning alone: the reason also reaches Claude, as a warning
        assert (proc.returncode, proc.stderr.splitlines()) == (code, lines)
        assert "names no folder" in (warned(json.loads(proc.stdout)) or "")


def test_a_gone_folder_with_only_the_warning_on_runs_and_says_why(tmp_path):
    env = hook_env([MAIN_CHECKOUT])
    payload = json.dumps(
        {"cwd": str(tmp_path / "gone"), "tool_input": {"command": "git commit -m x"}}
    )
    proc = subprocess.run(
        [HOOK_PYTHON, str(GUARDS)], input=payload, capture_output=True, text=True, env=env
    )
    # exit 0 drops stderr, so the reason also reaches Claude as a warning
    assert proc.returncode == 0 and "not an existing folder" in proc.stderr
    warning = warned(json.loads(proc.stdout)) or ""
    assert "not an existing folder" in warning and "ran unchecked" in warning


def test_agy_payload_attribution_denied(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "commit", "--allow-empty", "-m", "init")
    env = hook_env([ATTRIBUTION])
    payload = json.dumps(
        {
            "hookEventName": "PreToolUse",
            "conversationId": "test-agy-conv",
            "workspacePaths": [str(repo)],
            "toolCall": {
                "name": "run_command",
                "args": {
                    "CommandLine": "git commit -m 'feat: test\n\nCo-Authored-By: Claude'",
                },
            },
        }
    )
    proc = subprocess.run(
        [HOOK_PYTHON, str(GUARDS)], input=payload, capture_output=True, text=True, env=env
    )
    assert proc.returncode == 0
    decision = json.loads(proc.stdout)
    assert set(decision) == {"decision", "reason"}, decision
    assert decision["decision"] == "deny"
    assert "attribution" in decision["reason"].lower()


def test_agy_payload_clean_allowed(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "commit", "--allow-empty", "-m", "init")
    env = hook_env([ATTRIBUTION])
    payload = json.dumps(
        {
            "hookEventName": "PreToolUse",
            "conversationId": "test-agy-conv",
            "workspacePaths": [str(repo)],
            "toolCall": {
                "name": "run_command",
                "args": {
                    "CommandLine": "git commit -m 'feat: clean commit'",
                },
            },
        }
    )
    proc = subprocess.run(
        [HOOK_PYTHON, str(GUARDS)], input=payload, capture_output=True, text=True, env=env
    )
    assert proc.returncode == 0
    assert proc.stdout == "" or "deny" not in proc.stdout


def test_agy_payload_warning_is_an_allow_with_its_reason(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "commit", "--allow-empty", "-m", "init")
    _git(repo, "worktree", "add", "-q", str(tmp_path / "wt"), "-b", "side")
    payload = json.dumps(
        {
            "hookEventName": "PreToolUse",
            "workspacePaths": [str(repo)],
            "toolCall": {"name": "run_command", "args": {"CommandLine": "git commit -m 'feat: x'"}},
        }
    )
    proc = subprocess.run(
        [HOOK_PYTHON, str(GUARDS)],
        input=payload,
        capture_output=True,
        text=True,
        env=hook_env([MAIN_CHECKOUT]),
    )
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert set(out) == {"decision", "reason"}, out
    assert out["decision"] == "allow" and "main checkout" in out["reason"]


def test_only_a_toolcall_payload_without_tool_name_reads_as_agy():
    out = _load("hook_output", GUARDS.parent / "hook_output.py")
    assert out.from_agy({"toolCall": {"name": "run_command"}})
    assert not out.from_agy({"tool_name": "Bash", "toolCall": {"name": "run_command"}})
    assert not out.from_agy({"tool_name": "Bash", "tool_input": {"command": "git status"}})
    assert not out.from_agy({"toolCall": "run_command"})
    assert not out.from_agy([])


@pytest.mark.parametrize("agy", [False, True])
def test_a_verdict_joins_its_denies_once_each_and_its_warnings_in_order(monkeypatch, capsys, agy):
    (checks,) = load_phylax_hooks(monkeypatch, "git_checks")
    v = checks.Verdict(agy=agy)
    v.denies += ["first", "second", "first"]
    v.warnings.append("ignored while a deny stands")
    v.emit()
    out = json.loads(capsys.readouterr().out)
    reason = out["reason"] if agy else out["hookSpecificOutput"]["permissionDecisionReason"]
    assert reason == "first\nsecond"
    w = checks.Verdict(agy=agy)
    w.warnings += ["one", "two"]
    w.emit()
    out = json.loads(capsys.readouterr().out)
    text = out["reason"] if agy else out["hookSpecificOutput"]["additionalContext"]
    assert text == "one\ntwo"
    assert agy or out["systemMessage"] == "one\ntwo"
    checks.Verdict(agy=agy).emit()
    assert capsys.readouterr().out == ""


def test_agy_runs_the_checks_in_the_folder_run_command_names(tmp_path):
    # Only the folder Cwd names has a linked worktree, so only a check run there warns.
    work = tmp_path / "work"
    other = tmp_path / "other"
    for repo in (work, other):
        repo.mkdir()
        _git(repo, "init", "-b", "main")
        _git(repo, "commit", "--allow-empty", "-m", "init")
    _git(other, "worktree", "add", "-q", str(tmp_path / "wt"), "-b", "side")
    payload = json.dumps(
        {
            "hookEventName": "PreToolUse",
            "workspacePaths": [str(work)],
            "toolCall": {
                "name": "run_command",
                "args": {"CommandLine": "git commit -m 'feat: x'", "Cwd": str(other)},
            },
        }
    )
    proc = subprocess.run(
        [HOOK_PYTHON, str(GUARDS)],
        input=payload,
        capture_output=True,
        text=True,
        env=hook_env([MAIN_CHECKOUT]),
    )
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["decision"] == "allow" and str(other) in out["reason"]


def test_a_claude_payload_never_takes_its_folder_from_a_toolcall_cwd(tmp_path):
    here = tmp_path / "here"
    elsewhere = tmp_path / "elsewhere"
    for repo in (here, elsewhere):
        repo.mkdir()
        _git(repo, "init", "-b", "main")
        _git(repo, "commit", "--allow-empty", "-m", "init")
    _git(elsewhere, "worktree", "add", "-q", str(tmp_path / "wt"), "-b", "side")
    payload = json.dumps(
        {
            "tool_name": "Bash",
            "cwd": str(here),
            "tool_input": {"command": "git commit -m 'feat: x'"},
            "toolCall": {"args": {"Cwd": str(elsewhere)}},
        }
    )
    proc = subprocess.run(
        [HOOK_PYTHON, str(GUARDS)],
        input=payload,
        capture_output=True,
        text=True,
        env=hook_env([MAIN_CHECKOUT]),
    )
    assert proc.returncode == 0, proc.stderr
    assert not proc.stdout.strip()  # here has no linked worktree; elsewhere would warn


def test_an_agy_payload_with_its_own_cwd_keeps_it_over_the_workspace(tmp_path):
    named = tmp_path / "named"
    workspace = tmp_path / "workspace"
    for repo in (named, workspace):
        repo.mkdir()
        _git(repo, "init", "-b", "main")
        _git(repo, "commit", "--allow-empty", "-m", "init")
    _git(named, "worktree", "add", "-q", str(tmp_path / "wt"), "-b", "side")
    payload = json.dumps(
        {
            "hookEventName": "PreToolUse",
            "cwd": str(named),
            "workspacePaths": [str(workspace)],
            "toolCall": {"name": "run_command", "args": {"CommandLine": "git commit -m 'feat: x'"}},
        }
    )
    proc = subprocess.run(
        [HOOK_PYTHON, str(GUARDS)],
        input=payload,
        capture_output=True,
        text=True,
        env=hook_env([MAIN_CHECKOUT]),
    )
    assert proc.returncode == 0, proc.stderr
    assert str(named) in json.loads(proc.stdout)["reason"]


# --- units the mutation job found no test for ------------------------------------------


@pytest.fixture
def gc(monkeypatch):
    (mod,) = load_phylax_hooks(monkeypatch, "git_checks")
    return mod


@pytest.mark.parametrize(
    ("text", "start", "want"),
    [
        ("((1+1))", 0, True),
        ("((a*(b+c)))", 0, True),
        ("(( m = (1<<2) + 1 ))", 0, True),
        ("((cd a); (cd b))", 0, False),
        ("((cd a); (cd b); (cd c))", 0, False),
        ("xx((1+1))", 2, True),
        ("a) ((cd a); (cd b))", 3, False),
        ("(( m = ')' + 1 << n ))", 0, True),
        ('(( m = ")" + ")" ))', 0, True),
        ("((echo ')'); (echo b))", 0, False),
        ('((echo ")"); (echo "b"))', 0, False),
        ("((X); (cd b))", 0, False),  # a letter that is no quote is no reason to skip ahead
        ("((echo ''); (echo b))", 0, False),  # an empty quote closes at once
        ("((x", 0, True),  # never closed: arithmetic, the safe reading
        ("(( m = 'a ))", 0, True),  # an unclosed quote
        ("(( x = " + " + ".join(["1"] * 900) + " ))", 0, True),  # past the scan
        ("((" + "(cd a);" * 400 + "))", 0, True),  # a long subshell past the scan: also True
    ],
)
def test_is_arith(gc, text, start, want):
    assert gc.is_arith(text, start) is want


def test_arithmetic_closes_both_its_frames_so_the_quote_around_it_still_closes(gc):
    """`$((1))` inside double quotes pops both frames; a frame left behind would hide the
    closing quote, and the heredoc after it would read as quoted text."""
    for text in ('echo "$((1))"', 'echo "$(( (1) ))"', "echo $( echo $((1)) )"):
        stripped, bodies = gc.strip_heredocs(f"{text}; cat <<EOF\nbody\nEOF\n")
        assert "body" not in stripped and len(bodies) == 1, text


def test_a_comment_starts_only_after_a_separator(gc):
    stripped, _ = gc.strip_heredocs("echo hi # it's\necho z")
    assert "'" not in stripped and stripped.endswith("echo z")
    assert gc.strip_heredocs("echo hi #it's\necho z")[0].count("'") == 0  # `#i` after a space
    assert gc.strip_heredocs("echo a#b 'q'")[0] == "echo a#b 'q'"  # `a#b` is no comment
    assert gc.strip_heredocs("echo a;#it's\necho z")[0].count("'") == 0
    assert gc.strip_heredocs("(#it's\n)")[0].count("'") == 0
    # the character before a `#` decides, not the one after it or two before it
    assert gc.strip_heredocs("echo ab#c 'it'")[0] == "echo ab#c 'it'"
    assert gc.strip_heredocs("echo X#c 'q'")[0] == "echo X#c 'q'"  # only a separator starts one


def test_a_closed_dollar_brace_ends_its_frame(gc):
    """`#` is no comment inside ${...} (it is `${#x}` or text), but is again after the `}`."""
    assert "'" not in gc.strip_heredocs("echo ${x:-1} # it's\necho z")[0]
    assert "'" not in gc.strip_heredocs("echo ${x:-(} # it's\necho z")[0]
    # a `(` inside ${...} pushes no frame, so this `)` closes nothing
    assert "'" not in gc.strip_heredocs("echo ${x:-(}\necho a ) # it's\necho z")[0]
    assert gc.strip_heredocs("echo ${x:- # it's }\necho z")[0].count("'") == 1


@pytest.mark.parametrize(
    ("text", "bodies"),
    [
        ("(( m = 1 << n ))\ncat <<EOF\nx\nEOF", 1),  # a shift, then a real heredoc
        ("echo $((1<<n))\ncat <<EOF\nx\nEOF", 1),
        ("echo $(( (a<<b) ))\ncat <<EOF\nx\nEOF", 1),
        ("echo $(( 1 + $(cat <<EOF\n2\nEOF\n) ))", 1),  # `$(` in arithmetic runs commands
        ("((cat <<EOF\nx\nEOF\n) )", 1),  # `((` closing early: two subshells
        ("(( x )); cat <<EOF\nx\nEOF", 1),
        ("(cat <<EOF\nx\nEOF\n)", 1),
        ("( (a<<b) )\nfoo\nb", 1),  # plain parens, not arithmetic: `<<` is a heredoc
        ("x=$((1<<2)) $((2<<1))\n", 0),
        ("echo $((a*(b+c))) ; cat <<EOF\nx\nEOF", 1),  # the arithmetic closes: a heredoc follows
        ("echo $(( (a) ))\ncat <<EOF\nx\nEOF", 1),
        ("(((cd a); cat <<EOF\nx\nEOF\n))", 0),  # `((` at the start: arithmetic, `<<` a shift
        ("a(((cd a); cat <<EOF\nx\nEOF\n))", 0),
        # the character before the `((` is a `)`: is_arith must start at the `((` itself
        ("()((a<<b))\nfoo\nb", 0),
        ("(x)((a<<b))\nfoo\nb", 0),
        ("echo $(( 1 + $( (( 2 )) ) )) ; cat <<EOF\nx\nEOF", 1),
        ("( (( x )) ) ; cat <<EOF\nx\nEOF", 1),
        ("echo $((1<<2)) )\ncat <<EOF\nx\nEOF", 1),  # `))` closes the arithmetic
        # a closed `((` must leave no frame behind that blocks the next `((` from being arithmetic
        ("$( (( x )) ) ; (( m = 1 << n ))\nfoo\nn", 0),
        ("( (( x )) ) ; (( m = 1 << n ))\nfoo\nn", 0),
        ("((a<<b)) ) (\nfoo\nb", 0),  # `))` once, so the `<<` was inside arithmetic
    ],
)
def test_arithmetic_frames_decide_whether_a_double_angle_is_a_heredoc(gc, text, bodies):
    assert len(gc.strip_heredocs(text)[1]) == bodies, text


def test_off_switch_names_each_given_option_that_is_on_in_order(monkeypatch):
    from conftest import load_phylax_hooks

    (options,) = load_phylax_hooks(monkeypatch, "git_options")
    every = (*options.OPTIONS, *options.SHAPES)
    for key in every:
        monkeypatch.delenv(f"CLAUDE_PLUGIN_OPTION_{key.upper()}", raising=False)
    assert options.off_switch(every) == (
        "To switch it off, turn off the phylax option its option in /config, or run /phylax:setup."
    )
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_BLOCK_SECRETS", "true")
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_BLOCK_PKILL_FULL", "true")
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_BLOCK_COMMITS_MD", "false")
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_WARN_MAIN_CHECKOUT_COMMIT", "true")
    assert options.off_switch(every) == (
        "To switch it off, turn off the phylax option warn_main_checkout_commit, block_secrets, "
        "block_pkill_full in /config, or run /phylax:setup."
    )
    # only the options that could have refused are named: the warning and the shapes are not
    assert options.off_switch(options.BLOCKING) == (
        "To switch it off, turn off the phylax option block_secrets in /config, "
        "or run /phylax:setup."
    )


def test_the_checks_share_one_time_budget(monkeypatch, tmp_path):
    """Past the budget a git run fails the check with phylax's text, before the hook's own
    timeout, which names no guard; a run inside it gets at most what is left."""
    from conftest import load_phylax_hooks

    gc, options, scan = load_phylax_hooks(monkeypatch, "git_checks", "git_options", "secret_scan")
    assert options.BUDGET < 55  # register.ts's GUARD_TIMEOUT_MS, the shorter of the two
    monkeypatch.setattr(options, "_START", options._START - options.BUDGET)
    with pytest.raises(gc.GitUnavailable, match="budget"):
        gc.run_git(tmp_path, [], "status")
    with pytest.raises(scan.ScanError, match="budget"):
        scan._run(["true"], tmp_path, {})
    monkeypatch.setattr(options, "_START", options.time.monotonic() - options.BUDGET + 3)
    assert 2 < options.time_left(20) <= 3
    assert options.time_left(1) == 1


def _options_off(monkeypatch, options):
    for key in (*options.OPTIONS, *options.SHAPES):
        monkeypatch.delenv(f"CLAUDE_PLUGIN_OPTION_{key.upper()}", raising=False)


class _Clock:
    """A stand-in for git_options' `time` module whose monotonic() reads `now`."""

    def __init__(self, now: float):
        self.now = now

    def monotonic(self) -> float:
        return self.now


def test_the_budget_is_spent_at_zero_and_caps_what_is_left_below_one_second(monkeypatch):
    from conftest import load_phylax_hooks

    (options,) = load_phylax_hooks(monkeypatch, "git_options")
    clock = _Clock(100.0)
    monkeypatch.setattr(options, "time", clock)
    monkeypatch.setattr(options, "_START", 100.0 - options.BUDGET)
    with pytest.raises(TimeoutError, match="budget"):
        options.time_left(20)
    clock.now -= 0.5
    assert options.time_left(20) == 0.5


def test_a_git_timeout_names_the_subcommand_and_the_limit(monkeypatch, tmp_path):
    from conftest import load_phylax_hooks

    gc, options = load_phylax_hooks(monkeypatch, "git_checks", "git_options")
    monkeypatch.setattr(options, "_START", options.time.monotonic())

    def slow(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", slow)
    with pytest.raises(gc.GitUnavailable) as named:
        gc.run_git(tmp_path, [], "status", timeout=7)
    assert str(named.value) == "git status timed out after 7s"
    with pytest.raises(gc.GitUnavailable) as bare:
        gc.run_git(tmp_path, [], timeout=7)
    assert str(bare.value) == "git  timed out after 7s"


def test_a_check_with_no_folder_warns_in_antigravitys_shape(monkeypatch, capsys):
    from conftest import load_phylax_hooks

    gc, options = load_phylax_hooks(monkeypatch, "git_checks", "git_options")
    _options_off(monkeypatch, options)
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_WARN_MAIN_CHECKOUT_COMMIT", "true")
    data = {"toolCall": {"args": {"CommandLine": "git commit -m x"}}}
    assert gc.check(data, "git commit -m x") == 0
    why = options.unchecked("the hook input names no folder")
    assert json.loads(capsys.readouterr().out) == {"decision": "allow", "reason": why}


def test_a_shape_check_that_crashes_names_the_error_and_the_shape_options(monkeypatch, capsys):
    from conftest import load_phylax_hooks

    gg, shapes, options = load_phylax_hooks(
        monkeypatch, "git_guards", "command_shapes", "git_options"
    )
    _options_off(monkeypatch, options)
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_BLOCK_PKILL_FULL", "true")

    def broken(*args):
        raise ValueError("boom")

    monkeypatch.setattr(shapes, "check", broken)
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "pkill zz"}})
    assert gg.check_shapes(payload, {"block_pkill_full"})[1] == 2
    assert capsys.readouterr().err == (
        "phylax shape guard error: ValueError: boom; the command was not run. To switch it off, "
        "turn off the phylax option block_pkill_full in /config, or run /phylax:setup.\n"
    )


def test_main_marks_the_shapes_checked_before_the_git_checks(monkeypatch, tmp_path):
    """The crash handler leaves the shape options out of the refusal once the shapes passed."""
    import io

    from conftest import load_phylax_hooks

    gg, gc, options = load_phylax_hooks(monkeypatch, "git_guards", "git_checks", "git_options")
    _options_off(monkeypatch, options)
    monkeypatch.delenv("PHYLAX_GUARD_CHECKED", raising=False)
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_BLOCK_PKILL_FULL", "true")
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_WARN_MAIN_CHECKOUT_COMMIT", "true")

    def broken(data, raw):
        raise RuntimeError("after the shapes")

    monkeypatch.setattr(gc, "check", broken)
    payload = {"tool_name": "Bash", "tool_input": {"command": "pkill zz; git status"}}
    payload["cwd"] = str(tmp_path)
    monkeypatch.setattr(sys, "argv", ["git_guards.py", "--shapes"])
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    assert gg.shapes_checked is False
    with pytest.raises(RuntimeError, match="after the shapes"):
        gg.main()
    assert gg.shapes_checked is True
    assert gg.last_input == json.dumps(payload)  # the crash handler's warning reads its shape
