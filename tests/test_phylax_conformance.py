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
import string
import subprocess

import pytest
from conftest import ROOT, hook_env, hook_handlers, run_hook_handler

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
