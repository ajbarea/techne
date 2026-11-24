"""Advertised means enforced: each guard the docs' Guards table lists is probed through the real
hooks.json handlers, as Claude Code runs them, and must refuse (or, for the one warning, warn).

A new row in docs/configuration.md without a probe here fails, and so does a probe whose guard
no longer fires, so the docs and the hooks cannot drift apart.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import secrets
import shutil
import string
import subprocess

import pytest
from conftest import (
    HOOK_PYTHON,
    ROOT,
    hook_env,
    hook_handlers,
    load_phylax_hooks,
    run_hook_handler,
)

DOCS = ROOT / "docs" / "configuration.md"
MANIFEST = ROOT / "plugins" / "phylax" / ".claude-plugin" / "plugin.json"
HOOKS_JSON = ROOT / "plugins" / "phylax" / "hooks" / "hooks.json"
TRAILER = "Co-Authored-By: Claude <noreply@anthropic.com>"


def table_options() -> list[str]:
    """The options the Guards section's table lists, in order."""
    text = DOCS.read_text()
    section = text.split("\n## Guards\n", 1)[1].split("\n## ", 1)[0]
    return re.findall(r"^\| `([a-z_]+)` \|", section, re.MULTILINE)


def _git(repo: pathlib.Path, *args: str) -> None:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, env=env)


def new_repo(tmp: pathlib.Path) -> pathlib.Path:
    repo = tmp / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "a.txt").write_text("a\n")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-qm", "init")
    return repo


def bash(command: str, cwd: pathlib.Path, **tool_input) -> tuple[str, dict, pathlib.Path]:
    return "Bash", {"command": command, **tool_input}, cwd


def probe_attribution(tmp):
    return bash(f"git commit --allow-empty -m 'feat: x\n\n{TRAILER}'", new_repo(tmp))


def probe_commits_md(tmp):
    repo = new_repo(tmp)
    (repo / "COMMITS.md").write_text("plan\n")
    return bash("git add COMMITS.md", repo)


def probe_main_checkout(tmp):
    repo = new_repo(tmp)
    _git(repo, "worktree", "add", "-q", str(tmp / "wt"))
    return bash("git commit --allow-empty -m 'feat: x'", repo)


def probe_long_bodies(tmp):
    body = " ".join(["word"] * 400)
    return bash(f"gh pr create --title t --body '{body}'", tmp)


def probe_gh_implicit_repo(tmp):
    repo = new_repo(tmp)
    _git(repo, "remote", "add", "origin", "https://github.com/me/tool.git")
    _git(repo, "remote", "add", "upstream", "https://github.com/parent/tool.git")
    return bash("gh pr create --title t --body b", repo)


def probe_secrets(tmp):
    repo = new_repo(tmp)
    alphabet = string.ascii_letters + string.digits
    value = "ghp_" + "".join(secrets.choice(alphabet) for _ in range(36))
    (repo / "cfg.py").write_text(f'token = "{value}"\n')
    return bash("git add cfg.py && git commit -m x", repo)


def probe_background_loops(tmp):
    return bash("until gh pr checks 3; do sleep 30; done", tmp, run_in_background=True)


def probe_pkill_full(tmp):
    return bash("pkill -f marker", tmp)


def probe_subagent_model(tmp):
    tool_input = {"prompt": "p", "description": "d", "subagent_type": "general-purpose"}
    return "Agent", tool_input, tmp


def probe_email_greeting(tmp):
    tool_input = {"to": ["a@example.com"], "subject": "s", "body": "Hi Ben,\n\nText."}
    return "mcp__plugin_epistole_epistole__create_draft", tool_input, tmp


# Each guard: how to trip it, and what it must do.
PROBES = {
    "block_attribution_trailers": (probe_attribution, "deny"),
    "block_commits_md": (probe_commits_md, "deny"),
    "warn_main_checkout_commit": (probe_main_checkout, "warn"),
    "block_long_bodies": (probe_long_bodies, "deny"),
    "block_gh_implicit_repo": (probe_gh_implicit_repo, "deny"),
    "block_secrets": (probe_secrets, "deny"),
    "block_background_loops": (probe_background_loops, "deny"),
    "block_pkill_full": (probe_pkill_full, "deny"),
    "require_subagent_model": (probe_subagent_model, "deny"),
    "email_greeting": (probe_email_greeting, "deny"),
}


def handlers_for(tool: str) -> list[dict]:
    """The PreToolUse handlers whose matcher Claude Code would match against TOOL."""
    groups = json.loads(HOOKS_JSON.read_text())["hooks"]["PreToolUse"]
    names = [g["matcher"] for g in groups if re.fullmatch(g["matcher"], tool)]
    return [h for m in names for h in hook_handlers("phylax", "PreToolUse", m)]


def outcome(proc: subprocess.CompletedProcess) -> str | None:
    if proc.returncode == 2:
        return "deny"
    assert proc.returncode == 0, proc.stderr
    if not proc.stdout.strip():
        return None
    spec = json.loads(proc.stdout).get("hookSpecificOutput", {})
    if spec.get("permissionDecision") == "deny":
        return "deny"
    return "warn" if spec.get("additionalContext") else None


def test_every_listed_guard_has_a_probe():
    listed = table_options()
    assert listed, "the Guards table was not found"
    assert set(listed) == set(PROBES)


def test_every_listed_guard_is_a_plugin_option():
    options = json.loads(MANIFEST.read_text())["userConfig"]
    assert all(options.get(o, {}).get("type") == "boolean" for o in table_options())


@pytest.mark.parametrize("option", table_options())
def test_each_listed_guard_fires_through_hooks_json(tmp_path, option):
    probe, want = PROBES[option]
    tool, tool_input, cwd = probe(tmp_path)
    stdin = json.dumps({"tool_name": tool, "tool_input": tool_input, "cwd": str(cwd)})
    env = hook_env(
        [option],
        drop=("CLAUDE_CODE_SUBAGENT_MODEL", "CLAUDE_CODE_COORDINATOR", "PHYLAX_GUARD_CHECKED"),
        HOME=str(tmp_path / "home"),
        XDG_STATE_HOME=str(tmp_path / "state"),
    )
    handlers = handlers_for(tool)
    assert handlers, tool
    got = {outcome(run_hook_handler("phylax", h, stdin, env, cwd=tmp_path)) for h in handlers}
    assert want in got, (option, got)
    off = hook_env([], HOME=str(tmp_path / "home"), XDG_STATE_HOME=str(tmp_path / "state"))
    got_off = {outcome(run_hook_handler("phylax", h, stdin, off, cwd=tmp_path)) for h in handlers}
    assert got_off == {None}, (option, got_off)


# --- fail closed (techne#378) ------------------------------------------------------------
# Claude Code lets a tool call through when a PreToolUse command hook crashes, exits 1, cannot
# start or times out, unless the hook sets onFailure "block" (v2.1.295+). A guard without it
# stops nothing on its worst day.

# PreToolUse hooks that never refuse: budget.py only rewrites an Agent call's model.
NEVER_REFUSES = {"budget.py"}


def pre_tool_use_handlers() -> list[tuple[str, str, dict]]:
    """(plugin, matcher, handler) for every PreToolUse command hook in every plugin."""
    found = []
    for path in sorted((ROOT / "plugins").glob("*/hooks/hooks.json")):
        groups = json.loads(path.read_text())["hooks"].get("PreToolUse", [])
        for group in groups:
            for handler in group["hooks"]:
                found.append((path.parent.parent.name, group.get("matcher", ""), handler))
    return found


def can_refuse(handler: dict) -> bool:
    return not any(script in handler.get("command", "") for script in NEVER_REFUSES)


def test_the_never_refuses_exceptions_are_real_hooks():
    commands = " ".join(h["command"] for _, _, h in pre_tool_use_handlers())
    for script in NEVER_REFUSES:
        assert script in commands
        assert (ROOT / "plugins" / "phylax" / "hooks" / script).is_file()


def test_phylax_registers_the_refusing_pre_tool_use_hooks():
    matchers = {m for p, m, h in pre_tool_use_handlers() if p == "phylax" and can_refuse(h)}
    assert {"Bash", "run_command", "Agent|Task"} <= matchers
    assert any("epistole" in m for m in matchers)


@pytest.mark.parametrize(
    ("plugin", "matcher", "handler"),
    [
        pytest.param(*t, id=f"{t[0]}:{t[1][:24]}:{t[2]['command'][-30:]}")
        for t in pre_tool_use_handlers()
        if can_refuse(t[2])
    ],
)
def test_a_refusing_pre_tool_use_hook_fails_closed(plugin, matcher, handler):
    assert handler.get("type") == "command"  # onFailure covers command and http hooks only
    assert handler.get("onFailure") == "block", (
        f"{plugin} PreToolUse {matcher!r} can refuse but lets the call through when it "
        'crashes or times out; set "onFailure": "block"'
    )
    assert not handler.get("async") and not handler.get("asyncRewake")  # no effect there


def test_hooks_that_guard_nothing_are_left_alone():
    # Stop ignores the field, and the other events run no refusal.
    for path in (ROOT / "plugins").glob("*/hooks/hooks.json"):
        for event, groups in json.loads(path.read_text())["hooks"].items():
            if event == "PreToolUse":
                continue
            for group in groups:
                for handler in group["hooks"]:
                    assert "onFailure" not in handler, (path, event)


def test_every_blocking_hook_with_its_options_off_exits_0_without_output(tmp_path):
    """Fail closed must never refuse a user who switched the guard off."""
    env = hook_env()
    payloads = {
        "Bash": {"command": "git commit -m x"},
        "run_command": {"CommandLine": "git commit -m x"},
        "Agent|Task": {"description": "d", "prompt": "p"},
    }
    for plugin, matcher, handler in pre_tool_use_handlers():
        if plugin != "phylax" or not can_refuse(handler):
            continue
        tool = matcher if matcher in payloads else "mcp__plugin_epistole_epistole__create_draft"
        stdin = json.dumps(
            {
                "tool_name": tool.split("|")[0],
                "tool_input": payloads.get(matcher, {}),
                "cwd": str(tmp_path),
            }
        )
        proc = run_hook_handler("phylax", handler, stdin, env, cwd=tmp_path)
        assert (proc.returncode, proc.stdout, proc.stderr) == (0, "", ""), matcher


# --- a broken guard says how to switch it off (techne#378) ----------------------------------

HOOKS = ROOT / "plugins" / "phylax" / "hooks"
EMAIL_TOOL = "mcp__plugin_epistole_epistole__create_draft"
# option that arms each refusing matcher, and a call it would check
ARMED = {
    "Bash": ("block_secrets", {"command": "git commit -m x"}),
    "run_command": ("block_secrets", {"command": "git commit -m x"}),
    "Agent|Task": ("require_subagent_model", {"description": "d", "prompt": "p"}),
    EMAIL_TOOL: ("email_greeting", {"body": "x"}),
}


def refusing_phylax_handlers():
    for plugin, matcher, handler in pre_tool_use_handlers():
        if plugin != "phylax" or not can_refuse(handler):
            continue
        key = matcher if matcher in ARMED else EMAIL_TOOL
        yield pytest.param(key, handler, id=matcher[:20])


def run_without_python(tmp_path, handler, stdin, options):
    bin_dir = tmp_path / "bin"  # a PATH with cat and grep, as any machine has, and no python3
    bin_dir.mkdir(exist_ok=True)
    for tool in ("cat", "grep"):
        link = bin_dir / tool
        if not link.exists():
            link.symlink_to(shutil.which(tool) or f"/bin/{tool}")
    shell = handler["command"].replace("${CLAUDE_PLUGIN_ROOT}", str(ROOT / "plugins" / "phylax"))
    return subprocess.run(
        ["/bin/sh", "-c", shell],
        input=stdin,
        capture_output=True,
        text=True,
        env={**hook_env(options), "PATH": str(bin_dir)},
        check=False,
    )


@pytest.mark.parametrize(("key", "handler"), list(refusing_phylax_handlers()))
def test_a_missing_python3_refuses_a_checkable_call_and_names_the_way_out(tmp_path, key, handler):
    option, tool_input = ARMED[key]
    stdin = json.dumps({"tool_name": key.split("|")[0], "tool_input": tool_input})
    refused = run_without_python(tmp_path, handler, stdin, [option])
    assert refused.returncode == 2
    assert "python3 is not on PATH" in refused.stderr
    assert "/phylax:setup" in refused.stderr and "/config" in refused.stderr
    if key not in ("Bash", "run_command"):
        assert option in refused.stderr  # the Bash guards share one text for several options
    # a guard that is off never reaches python3
    off = run_without_python(tmp_path, handler, stdin, [])
    assert (off.returncode, off.stdout, off.stderr) == (0, "", "")


@pytest.mark.parametrize("key", ["Bash", "run_command"])
def test_a_bash_call_with_no_git_text_skips_python_even_when_a_guard_is_on(tmp_path, key):
    (handler,) = [h for _, m, h in pre_tool_use_handlers() if m == key]
    stdin = json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls -la"}})
    proc = run_without_python(tmp_path, handler, stdin, ["block_secrets"])
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, "", "")


def test_a_crash_names_the_guard_the_error_and_the_option(capsys, monkeypatch):
    (hook_failure,) = load_phylax_hooks(monkeypatch, "hook_failure")

    def boom() -> int:
        raise KeyError("tool_input")

    with pytest.raises(SystemExit) as exit_info:
        hook_failure.run(boom, "email greeting guard", "email_greeting")
    err = capsys.readouterr().err
    assert exit_info.value.code == 2
    assert "email greeting guard" in err and "KeyError" in err and "tool_input" in err
    assert "email_greeting" in err and "/config" in err and "/phylax:setup" in err
    with pytest.raises(SystemExit) as ok:
        hook_failure.run(lambda: 0, "g", "o")
    assert ok.value.code == 0 and capsys.readouterr().err == ""


@pytest.mark.parametrize(
    ("script", "option"),
    [("model_guard.py", "require_subagent_model"), ("email_greeting.py", "email_greeting")],
)
def test_an_unhandled_crash_in_a_guard_script_exits_2_with_the_way_out(tmp_path, script, option):
    # json.load raises, so the crash path is the one under test. The cwd is not the hooks
    # folder, and run_path adds no folder to sys.path, so the script must find hook_failure
    # itself (as under PYTHONSAFEPATH).
    code = (
        "import runpy, sys;"
        f"sys.argv=[{script!r}];"
        "import json; json.load = lambda *a, **k: 1 / 0;"
        f"runpy.run_path({str(HOOKS / script)!r}, run_name='__main__')"
    )
    proc = subprocess.run(
        [HOOK_PYTHON, "-c", code],
        input="{}",
        capture_output=True,
        text=True,
        env=hook_env([option]),
        cwd=tmp_path,
        check=False,
    )
    assert proc.returncode == 2, proc.stderr
    assert "ZeroDivisionError" in proc.stderr and option in proc.stderr
    assert "/phylax:setup" in proc.stderr


BASH_HANDLERS = [
    pytest.param(h, id=m) for _, m, h in pre_tool_use_handlers() if m in ("Bash", "run_command")
]


@pytest.mark.parametrize("handler", BASH_HANDLERS)
def test_a_missing_python3_with_a_shape_option_on_still_checks_for_git(tmp_path, handler):
    stdin = json.dumps({"tool_input": {"command": "git commit -m x"}})
    proc = run_without_python(tmp_path, handler, stdin, ["block_secrets", "block_pkill_full"])
    assert proc.returncode == 2 and "git guards" in proc.stderr, proc.stderr
    assert "block_secrets" in proc.stderr and "block_pkill_full" not in proc.stderr


@pytest.mark.parametrize("handler", BASH_HANDLERS)
def test_a_missing_python3_with_only_the_warning_on_refuses_nothing(tmp_path, handler):
    stdin = json.dumps({"tool_input": {"command": "git commit -m x"}})
    proc = run_without_python(tmp_path, handler, stdin, ["warn_main_checkout_commit"])
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, "", "")


@pytest.mark.parametrize("handler", BASH_HANDLERS)
@pytest.mark.parametrize(
    ("command", "code"),
    [
        ("ls", 0),
        ("git push", 2),
        ('echo "a"\ngit push', 2),  # after an escaped quote and a newline
        ("\\u0067it push", 2),  # the replace below makes it a JSON escape
        ("pkill -f x", 2),
    ],
)
def test_a_missing_python3_checks_only_the_command_not_the_folder(tmp_path, handler, command, code):
    """The folder, the transcript path, a description and Antigravity's workspace may say
    github or hugh; only the command decides."""
    beside = "/home/hugh/github/until/x"
    claude = {
        "cwd": beside,
        "transcript_path": beside,
        "tool_input": {"command": command, "description": "git while pkill"},
    }
    agy = {
        "toolCall": {"args": {"CommandLine": command, "Cwd": beside}},
        "workspacePaths": [beside],
    }
    for payload in (claude, agy):
        stdin = json.dumps(payload, ensure_ascii=False).replace("\\\\u0067", "\\u0067")
        proc = run_without_python(tmp_path, handler, stdin, ["block_secrets", "block_pkill_full"])
        assert proc.returncode == code, (payload, proc.stderr)


@pytest.mark.parametrize(
    ("stdin", "code"),
    [
        # stdin that is not UTF-8 crashes the read, before the shape check: the shapes went
        # unchecked, so a shape option refuses
        (b"\xff\xfe pkill -f x", 2),
        # JSON that does not parse crashes after the shape check passed (no shape word): only a
        # blocking git guard would refuse
        (b'{"tool_input": {"command": "git commit"', 0),
    ],
)
def test_a_crash_counts_the_shape_options_only_before_the_shape_check(stdin, code):
    proc = subprocess.run(
        [HOOK_PYTHON, str(HOOKS / "git_guards.py"), "--shapes"],
        input=stdin,
        capture_output=True,
        env={
            **hook_env(["block_pkill_full", "warn_main_checkout_commit"]),
            "PYTHONIOENCODING": "utf-8:strict",
        },
        check=False,
    )
    assert proc.returncode == code, proc.stderr
    assert b"phylax git guard error" in proc.stderr
    assert (b"block_pkill_full" in proc.stderr) is (code == 2)


@pytest.mark.parametrize("handler", BASH_HANDLERS)
@pytest.mark.parametrize(
    ("command", "code"),
    [
        ("echo digit highlight ghost", 0),
        ("ls; git status", 2),
        ("/usr/bin/git push", 2),
        ("echo a\tgit push", 2),  # JSON writes the tab as \t before the word
        ("gh pr create", 2),
    ],
)
def test_a_missing_python3_reads_git_and_gh_as_words(tmp_path, handler, command, code):
    stdin = json.dumps({"tool_input": {"command": command}})
    proc = run_without_python(tmp_path, handler, stdin, ["block_secrets"])
    assert proc.returncode == code, (command, proc.stderr)


def stub_python(tmp_path, body: str) -> pathlib.Path:
    """A PATH whose python3 is a stub (macOS's, before its tools are installed, exits 1)."""
    bin_dir = tmp_path / "stub"
    bin_dir.mkdir(exist_ok=True)
    for tool in ("cat", "grep"):
        if not (bin_dir / tool).exists():
            (bin_dir / tool).symlink_to(shutil.which(tool) or f"/bin/{tool}")
    (bin_dir / "python3").write_text(f"#!/bin/sh\n{body}\n")
    (bin_dir / "python3").chmod(0o755)
    return bin_dir


def run_on(handler, stdin, options, path) -> subprocess.CompletedProcess:
    shell = handler["command"].replace("${CLAUDE_PLUGIN_ROOT}", str(HOOKS.parent))
    return subprocess.run(
        ["/bin/sh", "-c", shell],
        input=stdin,
        capture_output=True,
        text=True,
        env={**hook_env(options), "PATH": str(path)},
        check=False,
    )


@pytest.mark.parametrize("handler", BASH_HANDLERS)
@pytest.mark.parametrize(
    ("reads", "options", "command", "code"),
    [
        # the stub exits before it reads: the command decides, as when python3 is missing
        (False, ["warn_main_checkout_commit"], "git commit -m x", 0),
        (False, ["block_secrets"], "ls", 0),
        (False, ["block_secrets"], "git commit -m x", 2),
        (False, ["block_pkill_full"], "pkill -f x", 2),
        # it read the input first: nothing is left to check, so a refusing guard refuses
        (True, ["block_secrets"], "ls", 2),
        (True, ["block_pkill_full"], "ls", 2),
        (True, ["warn_main_checkout_commit"], "git commit -m x", 0),
    ],
)
def test_a_python3_that_fails_is_read_like_a_missing_one(
    tmp_path, handler, reads, options, command, code
):
    path = stub_python(tmp_path, ("cat >/dev/null; " if reads else "") + "exit 1")
    stdin = json.dumps({"cwd": "/home/u/github/x", "tool_input": {"command": command}})
    proc = run_on(handler, stdin, options, path)
    assert proc.returncode == code, proc.stderr
    if code == 2:
        assert "python3 failed (exit 1)" in proc.stderr and options[0] in proc.stderr
    else:
        assert proc.stderr == ""


@pytest.mark.parametrize(("key", "handler"), list(refusing_phylax_handlers()))
@pytest.mark.parametrize("rc", [0, 2])
def test_the_guard_s_own_exit_passes_through(tmp_path, key, handler, rc):
    option, tool_input = ARMED[key]
    path = stub_python(tmp_path, f"cat >/dev/null; echo out; exit {rc}")
    stdin = json.dumps({"tool_name": key.split("|")[0], "tool_input": tool_input})
    proc = run_on(handler, stdin, [option], path)
    assert (proc.returncode, proc.stdout, proc.stderr) == (rc, "out\n", "")


@pytest.mark.parametrize(
    ("key", "handler"),
    [p for p in refusing_phylax_handlers() if p.values[0] not in ("Bash", "run_command")],
)
def test_a_failing_python3_refuses_the_model_and_greeting_guards_with_the_way_out(
    tmp_path, key, handler
):
    option, tool_input = ARMED[key]
    stdin = json.dumps({"tool_name": key.split("|")[0], "tool_input": tool_input})
    proc = run_on(handler, stdin, [option], stub_python(tmp_path, "exit 1"))
    assert proc.returncode == 2
    assert "python3 failed (exit 1)" in proc.stderr and option in proc.stderr
    assert "/phylax:setup" in proc.stderr


@pytest.mark.parametrize("handler", BASH_HANDLERS)
@pytest.mark.parametrize("option", ["block_secrets", "block_pkill_full"])
def test_a_missing_python3_refuses_a_unicode_escape_for_each_guard(tmp_path, handler, option):
    """JSON may spell git or pkill with \\u escapes, which the shell cannot decode."""
    word = "\\u0067it push" if option == "block_secrets" else "\\u0070kill -f x"
    stdin = '{"tool_input": {"command": "' + word + '"}}'
    proc = run_without_python(tmp_path, handler, stdin, [option])
    assert proc.returncode == 2 and option in proc.stderr, proc.stderr


@pytest.mark.parametrize(
    ("payload", "agy"),
    [
        ({"tool_name": "Bash", "tool_input": {"command": "git status"}, "cwd": "/tmp"}, False),
        ({"toolCall": {"args": {"CommandLine": "git status", "Cwd": "/tmp"}}}, True),
    ],
)
def test_a_crash_with_only_the_warning_on_warns_in_the_callers_shape(payload, agy):
    """Exit 0 drops stderr, so a crash the warning guard cannot refuse still says so."""
    code = (
        f"import runpy, sys; sys.path.insert(0, {str(HOOKS)!r});"
        "import git_checks; git_checks.check = lambda data, raw: 1 / 0;"
        "sys.argv = ['git_guards.py'];"
        f"runpy.run_path({str(HOOKS / 'git_guards.py')!r}, run_name='__main__')"
    )
    proc = subprocess.run(
        [HOOK_PYTHON, "-c", code],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=hook_env(["warn_main_checkout_commit"]),
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    text = out["reason"] if agy else out["systemMessage"]
    assert ("decision" in out) is agy
    assert "ZeroDivisionError" in text and "ran unchecked" in text


def test_a_crash_on_input_too_deep_to_parse_still_only_warns():
    """The crash handler reads the input again for its warning's shape; input it cannot parse
    either (here a RecursionError, whatever this Python's json nesting limit) still only warns."""

    code = (
        "import json, runpy;"
        "json.loads = lambda *a, **k: (_ for _ in ()).throw(RecursionError('too deep'));"
        f"runpy.run_path({str(HOOKS / 'git_guards.py')!r}, run_name='__main__')"
    )
    proc = subprocess.run(
        [HOOK_PYTHON, "-c", code],
        input='[[["git"]]]',
        capture_output=True,
        text=True,
        env=hook_env(["warn_main_checkout_commit"]),
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "RecursionError" in json.loads(proc.stdout)["systemMessage"]


@pytest.mark.parametrize("handler", BASH_HANDLERS)
@pytest.mark.parametrize("shell", ["/bin/bash", "/bin/sh"])
@pytest.mark.parametrize(
    "option", ["block_attribution_trailers", "block_secrets", "block_pkill_full"]
)
def test_a_missing_fallback_script_refuses_in_every_shell(tmp_path, handler, shell, option):
    """bash's `.` of a missing file only prints an error and goes on, so the hook must refuse
    there itself; dash stops the shell, which refuses too."""
    plugin = tmp_path / "phylax"
    shutil.copytree(ROOT / "plugins" / "phylax" / "hooks", plugin / "hooks")
    (plugin / "hooks" / "no_python3.sh").unlink()
    bin_dir = tmp_path / "bin"  # cat and grep, no python3
    bin_dir.mkdir()
    for tool in ("cat", "grep"):
        (bin_dir / tool).symlink_to(shutil.which(tool) or f"/bin/{tool}")
    proc = subprocess.run(
        [shell, "-c", handler["command"].replace("${CLAUDE_PLUGIN_ROOT}", str(plugin))],
        input=json.dumps({"tool_input": {"command": "git push; pkill -f x"}}),
        capture_output=True,
        text=True,
        env={**hook_env([option]), "PATH": str(bin_dir)},
        check=False,
    )
    assert proc.returncode == 2, proc.stderr
    assert "no_python3.sh" in proc.stderr
