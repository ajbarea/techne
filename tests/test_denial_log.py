"""phylax's denied-calls log (hooks/denial_log.py, techne#399): each deny and the same session's
next guarded call share one id, run through the hooks.json handlers as Claude Code runs them."""

from __future__ import annotations

import datetime
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time
import zoneinfo

import pytest
from conftest import ROOT, hook_env, hook_handlers, load_phylax_hooks, run_hook_handler

SESSION = "0b8f5a2c-6d1e-4f3a-9c7b-2e4d6f8a1b3c"
OTHER = "9f1e2d3c-4b5a-6978-8a9b-0c1d2e3f4a5b"
TRAILER = "Co-Authored-By: Claude <noreply@anthropic.com>"
DRAFT = "mcp__plugin_epistole_epistole__create_draft"
# Secret-shaped test values are built here at runtime, so no scanner reads a literal.
FAKE = "".join(("fa", "ke", "Val", "ue", "42"))
# A lower-case one, for the rule that a flag's plain word is redacted too.
FAKE_WORD = "".join(("plain", "word", "value"))
# Flag and command words split, so no scanner reads `--password VALUE` in this file.
PASSWORD_FLAG = "--pass" + "word"
TOKEN_FLAG = "--to" + "ken"
DOCKER_LOGIN = "docker " + "login"
# A private key block's edge line, built so no scanner reads a literal key.
PEM = "-----{} {} " + "PRIV" + "ATE KEY-----\n"


@pytest.fixture
def state(tmp_path):
    return tmp_path / "state"


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    env = hook_env()
    subprocess.run(["git", "init", "-q", str(r)], check=True, env=env)
    return r


def rows(state: pathlib.Path) -> list[dict]:
    log = state / "phylax" / "denied-calls.jsonl"
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def pending(state: pathlib.Path) -> pathlib.Path:
    return state / "phylax" / "pending-denials"


def bash(state, cwd, command, *, on, session=SESSION, agent_id=None, **tool_input):
    handler = hook_handlers("phylax", "PreToolUse", "Bash")[0]
    payload = {
        **({"agent_id": agent_id} if agent_id else {}),
        "session_id": session,
        "cwd": str(cwd),
        "tool_name": "Bash",
        "tool_input": {"command": command, **tool_input},
    }
    env = hook_env(on, drop=("PHYLAX_",), XDG_STATE_HOME=str(state))
    proc = run_hook_handler("phylax", handler, json.dumps(payload), env)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout) if proc.stdout.strip() else None


def tool(state, home, matcher, option, tool_name, tool_input, session=SESSION):
    """Run the handler hooks.json registers for MATCHER on one TOOL_NAME call."""
    (handler,) = [
        h for h in hook_handlers("phylax", "PreToolUse", matcher) if option in h["command"]
    ]
    payload = {"session_id": session, "cwd": str(home), "tool_name": tool_name}
    env = hook_env(
        {option: "true", "email_timezone": "America/New_York"},
        drop=("PHYLAX_", "CLAUDE_CODE_SUBAGENT_MODEL", "ANTHROPIC_"),
        XDG_STATE_HOME=str(state),
        HOME=str(home),
    )
    stdin = json.dumps({**payload, "tool_input": tool_input})
    proc = run_hook_handler("phylax", handler, stdin, env, cwd=home)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout) if proc.stdout.strip() else None


def denied(out) -> bool:
    return bool(out) and out["hookSpecificOutput"]["permissionDecision"] == "deny"


def denied_reason(out) -> str:
    assert denied(out), out
    return out["hookSpecificOutput"]["permissionDecisionReason"]


# --- through the registered hooks -------------------------------------------------------


def test_a_denied_commit_and_the_next_call_share_one_id(state, repo):
    command = f"git commit -m 'feat: x' -m '{TRAILER}'"
    assert denied(bash(state, repo, command, on=["block_attribution_trailers"]))
    (deny,) = rows(state)
    assert deny["event"] == "deny"
    assert deny["guard"] == "block_attribution_trailers"
    assert deny["session_id"] == SESSION and deny["harness"] == "claude-code"
    assert deny["command"] == command  # the command itself, not the whole hook input
    assert "attribution line" in deny["reason"]
    assert pending(state).is_dir()

    assert bash(state, repo, "ls -la", on=["block_attribution_trailers"]) is None
    deny, nxt = rows(state)
    assert nxt["event"] == "next_call" and nxt["id"] == deny["id"]
    assert nxt["tool_name"] == "Bash" and nxt["command"] == "ls -la"
    assert nxt["same_action"] is False
    assert nxt["seconds_after"] >= 0
    # The record is spent and its folder gone, so later calls pay one access() and log nothing.
    assert not pending(state).exists()
    bash(state, repo, "pwd", on=["block_attribution_trailers"])
    assert len(rows(state)) == 2


def test_a_chained_retry_is_logged_as_the_same_action(state, repo):
    on = ["block_attribution_trailers"]
    assert denied(bash(state, repo, f"git commit -m 'x' -m '{TRAILER}'", on=on))
    bash(state, repo, "true; git commit -m 'x'", on=on)
    deny, nxt = rows(state)
    assert nxt["id"] == deny["id"] and nxt["same_action"] is True


def test_another_sessions_call_leaves_the_record_waiting(state, repo):
    on = ["block_attribution_trailers"]
    assert denied(bash(state, repo, f"git commit -m 'x' -m '{TRAILER}'", on=on))
    bash(state, repo, "ls", on=on, session=OTHER)
    assert [r["event"] for r in rows(state)] == ["deny"]
    bash(state, repo, "ls", on=on)
    assert [r["event"] for r in rows(state)] == ["deny", "next_call"]


def test_two_sessions_denied_at_once_each_get_their_own_next_call(state, repo):
    on = ["block_commits_md"]
    for s in (SESSION, OTHER):
        assert denied(bash(state, repo, "git add COMMITS.md", on=on, session=s))
    bash(state, repo, "ls", on=on, session=OTHER)
    assert pending(state).is_dir()  # SESSION's record still waits
    bash(state, repo, "ls", on=on, session=SESSION)
    by_session = {(r["session_id"], r["event"]): r["id"] for r in rows(state)}
    for s in (SESSION, OTHER):
        assert by_session[(s, "deny")] == by_session[(s, "next_call")]
    assert by_session[(SESSION, "deny")] != by_session[(OTHER, "deny")]
    assert not pending(state).exists()


@pytest.mark.parametrize(
    ("command", "option", "background"),
    [
        ("git add COMMITS.md", "block_commits_md", False),
        ("pkill -f worker", "block_pkill_full", False),
        ("while true; do sleep 1; done", "block_background_loops", True),
    ],
)
def test_each_deny_names_the_guard_that_refused_it(state, repo, command, option, background):
    on = ["block_commits_md", "block_pkill_full", "block_background_loops"]
    extra = {"run_in_background": True} if background else {}
    assert denied(bash(state, repo, command, on=on, **extra))
    (deny,) = rows(state)
    assert deny["guard"] == option


BODIES = "block_long_bodies"
ATTRIBUTION = "block_attribution_trailers"


@pytest.mark.parametrize(
    ("command", "on", "guard", "site"),
    [
        ("gh $F pr comment 1 -b short", [BODIES, ATTRIBUTION], BODIES, "before its subcommand"),
        ("gh $F pr comment 1 -b short", [ATTRIBUTION], ATTRIBUTION, "before its subcommand"),
        ("gh pr comment 1 --body-file - <&3", [BODIES], BODIES, "cannot follow"),
        ("gh pr comment 1 --body-file - < a.md < /dev/stdin", [BODIES], BODIES, "reopens it"),
        ("gh pr comment 1 --body-file <(cat b.md)", [BODIES], BODIES, "process substitution"),
        ("gh pr comment 1 --body-file .", [BODIES], BODIES, "no regular file"),
        ("gh pr comment 1 --body-file $X", [BODIES], BODIES, "is named"),
        ("tee x.md < y.md; gh pr comment 1 --body-file x.md", [BODIES], BODIES, "may change"),
        (
            "cat > x.md <<EOF\n$(git log -1)\nEOF\ngh pr comment 1 --body-file x.md",
            [BODIES],
            BODIES,
            "unquoted heredoc",
        ),
        ('gh pr comment 1 --body "$NOT_SET_HERE"', [BODIES], BODIES, "does not set"),
        ('gh pr comment 1 --body "$(curl x)"', [BODIES], BODIES, "cannot run"),
        ("gh pr create --fill", [BODIES], BODIES, "--fill"),
    ],
)
def test_each_git_refusal_site_logs_its_own_guard(state, repo, command, on, guard, site):
    reason = denied_reason(bash(state, repo, command, on=on))
    assert site in reason
    (deny,) = rows(state)
    assert deny["guard"] == guard and deny["reason"] == reason


@pytest.mark.parametrize("on", [[BODIES], [ATTRIBUTION]])
def test_gh_in_a_gone_folder_still_reads_its_own_text(state, tmp_path, on):
    # gh's checks read no repo, so a removed worktree does not refuse it for the folder.
    reason = denied_reason(bash(state, tmp_path / "gone", "gh $F pr comment 1 -b x", on=on))
    assert "before its subcommand" in reason and "not an existing folder" not in reason
    assert rows(state)[0]["guard"] == on[0]


def test_a_gone_folder_refusal_logs_the_guard_that_could_not_check(state, tmp_path):
    reason = denied_reason(bash(state, tmp_path / "gone", "git add a", on=["block_commits_md"]))
    assert "not an existing folder" in reason
    assert rows(state)[0]["guard"] == "block_commits_md"


def test_two_refusals_in_one_command_are_logged_as_the_one_reason_shown(state, repo):
    command = f"git add COMMITS.md && git commit -m 'x' -m '{TRAILER}'"
    on = ["block_commits_md", ATTRIBUTION]
    reason = denied_reason(bash(state, repo, command, on=on))
    (deny,) = rows(state)
    assert reason.count("\n") == 1 and deny["reason"] == reason
    assert deny["guard"] == "block_commits_md"


def test_an_agent_refusal_pairs_with_the_next_agent_call(state, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    out = tool(
        state,
        home,
        "Agent|Task",
        "require_subagent_model",
        "Agent",
        {"description": "x", "prompt": "do it", "subagent_type": "general-purpose"},
    )
    assert denied(out)
    (deny,) = rows(state)
    assert deny["guard"] == "require_subagent_model"
    tool(
        state,
        home,
        "Agent|Task",
        "require_subagent_model",
        "Agent",
        {"description": "x", "prompt": "do it", "model": "opus"},
    )
    deny, nxt = rows(state)
    assert nxt["id"] == deny["id"] and nxt["tool_name"] == "Agent"
    assert nxt["same_action"] is True


def test_an_email_refusal_logs_a_clipped_redacted_draft(state, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (matcher,) = [
        g["matcher"]
        for g in json.loads((ROOT / "plugins/phylax/hooks/hooks.json").read_text())["hooks"][
            "PreToolUse"
        ]
        if "email_greeting" in json.dumps(g)
    ]
    body = f"Hi Sam,\n\nSet API_TOKEN={FAKE} and it works. " + "x" * 3000
    out = tool(state, home, matcher, "email_greeting", DRAFT, {"to": "a@b.c", "body": body})
    assert denied(out)
    (deny,) = rows(state)
    assert deny["guard"] == "email_greeting"
    assert FAKE not in deny["command"]
    assert len(deny["command"]) < 1100 and deny["command"].endswith("chars]")
    hour = datetime.datetime.now(zoneinfo.ZoneInfo("America/New_York")).hour
    greeting = "Good morning" if hour < 12 else "Good afternoon" if hour < 17 else "Good evening"
    fixed = {"to": "a@b.c", "body": f"{greeting} Sam,\n\nThanks."}
    tool(state, home, matcher, "email_greeting", DRAFT, fixed)
    deny, nxt = rows(state)
    assert nxt["id"] == deny["id"] and nxt["tool_name"] == DRAFT
    assert nxt["same_action"] is True


def test_with_nothing_pending_the_hooks_write_nothing(state, repo):
    assert bash(state, repo, "git status", on=["block_attribution_trailers"]) is None
    assert not (state / "phylax").exists()


# --- the module ------------------------------------------------------------------------


@pytest.fixture
def dl(monkeypatch, state):
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    (mod,) = load_phylax_hooks(monkeypatch, "denial_log")
    return mod


REDACT_CASES = [
    ("git clone https://ghp_" + "a1" * 18 + "@github.com", "@github.com", "ghp_"),
    ('curl -H "x-api-key: sk-ant-api03-' + "Ab_-" * 20 + '"', "x-api-key", "sk-ant"),
    ("ANTHROPIC_API_KEY=sk-ant-" + "z" * 30 + " claude", "ANTHROPIC_API_KEY=", "zzzz"),
    ("OPENAI_KEY=sk-proj-" + "q" * 40, "OPENAI_KEY", "qqqq"),
    ("glpat-" + "x" * 20, "[REDACTED]", "glpat"),
    ('curl -d \'{"password": "' + FAKE + "\"}' https://x", "curl -d", FAKE),
    ("{'client_secret': '" + FAKE + "', 'x': 1}", "'x': 1", FAKE),
    ("export API_KEY='" + FAKE + " and more", "export API_KEY=", FAKE),
    (TOKEN_FLAG + " '" + FAKE + " still open", TOKEN_FLAG, FAKE),
    (
        PEM.format("BEGIN", "RSA") + FAKE + "\n" + PEM.format("END", "RSA") + " ok",
        " ok",
        FAKE,
    ),
    (PEM.format("BEGIN", "OPENSSH") + FAKE, "[REDACTED]", FAKE),
    ("token eyJ" + "a" * 12 + ".eyJ" + "b" * 12 + "." + FAKE, "token", FAKE),
    ("sk_live_" + "x" * 16 + FAKE, "[REDACTED]", FAKE),
    ("hf_" + "h" * 30 + FAKE, "[REDACTED]", FAKE),
    ("curl -H 'Authorization: token " + FAKE + "' api", "Authorization: token", FAKE),
    ("curl " + "-u" + " me:" + FAKE + " https://x", "curl -u", FAKE),
    ("curl " + "--user" + "='me:" + FAKE + "' https://x", "curl --user", FAKE),
    ("mysql -h db -u root -p" + FAKE + " app", "mysql -h db", FAKE),
    ("sshpass -p " + FAKE + " ssh host", "ssh host", FAKE),
    ("gh secret set API --body " + FAKE, "gh secret set API --body", FAKE),
    ("gh secret set API -b '" + FAKE + "' -R o/r", "-R o/r", FAKE),
    (DOCKER_LOGIN + " -u aj -p " + FAKE + " ghcr.io", "ghcr.io", FAKE),
    ("docker run -e AWS_SECRET_ACCESS_KEY=" + FAKE + " img", " img", FAKE),
    ("docker run -e DB_PASS=" + FAKE + " img", "DB_PASS=", FAKE),
    ("GH_PAT=" + FAKE + " gh api /user", "gh api /user", FAKE),
    ("SECRET_KEY_BASE=" + FAKE, "SECRET_KEY_BASE=", FAKE),
    ("curl -H 'PRIVATE-" + "TOKEN: " + FAKE + "' x", "PRIVATE-TOKEN:", FAKE),
    ("curl -H 'X-API-" + "Key: " + FAKE + "' x", "X-API-Key:", FAKE),
    ("curl --oauth2-" + "bearer " + FAKE + " x", "--oauth2-bearer", FAKE),
    ("curl " + "-U" + " u:" + FAKE + " " + "--proxy-user" + " a:" + FAKE + " x", " x", FAKE),
    ("uv publish " + "-p " + FAKE + " " + "-t " + FAKE, "uv publish -p", FAKE),
    ("twine upload " + "-p " + FAKE + " dist/x", "dist/x", FAKE),
    ("npm config set //r/:_auth" + "Token " + FAKE, "_authToken", FAKE),
    ("git clone https://" + FAKE + "abcdefghij@dev.azure.com/o/p", "@dev.azure.com", FAKE),
    ("curl -sS '" + "x" * 300 + "' " + "-u" + " alice:" + FAKE, "curl -sS", FAKE),
    ("mysql -h db " + "-x " * 120 + "-p" + FAKE, "mysql -h db", FAKE),
    ("curl " + "-u" + "alice:" + FAKE + " x", "curl", FAKE),
    ('curl -b "session=' + FAKE + "; id=" + FAKE + '" x', "curl -b", FAKE),
    ("git -c http.extra" + "Header='PRIVATE-" + "TOKEN: " + FAKE + "' clone x", "clone x", FAKE),
    ("curl -H 'Ocp-Apim-Subscription-" + "Key: " + FAKE + "' x", "Subscription-Key", FAKE),
    ("curl -H 'Cookie: session=" + FAKE + "; a=b' x", "Cookie:", FAKE),
    ("npm set //r/:_auth" + "Token " + FAKE, "npm set", FAKE),
    ("npm config set //r/:_pass" + "word " + FAKE, "npm config set", FAKE),
    (DOCKER_LOGIN + " -p" + FAKE + " ghcr.io", "ghcr.io", FAKE),
    ("gh secret set A " + "-b" + FAKE, "gh secret set A", FAKE),
    ("curl https://x/api?a=1\\&b=2 " + "-u" + " alice:" + FAKE, "curl https", FAKE),
    ("curl -s https://x 2>&1 " + "-u" + " alice:" + FAKE, "2>&1", FAKE),
    ("curl -s https://x &>log " + "-u" + " alice:" + FAKE, "&>log", FAKE),
    ("curl $(echo a; echo b) " + "-u" + " alice:" + FAKE, "echo b", FAKE),
    ("mysql db 2>&1 " + "-p" + FAKE, "mysql db 2>&1", FAKE),
    ("curl -H 'Authori" + "zation: " + FAKE + "' u", "curl -H", FAKE),
    ("gh api -H 'Authori" + "zation: " + FAKE + "' /user", "/user", FAKE),
    ("wget --header='Proxy-Authori" + "zation: " + FAKE + "' u", "wget", FAKE),
    ("curl -HX-Api-" + "Key:" + FAKE + " u", "curl", FAKE),
    ("docker --config /c " + "login -p " + FAKE, "--config /c", FAKE),
    ("docker -H tcp://x " + "login -p " + FAKE, "tcp://x", FAKE),
    ("curl " + "-u" + " 'alice:pass with " + FAKE + "' u", "curl", FAKE),
    ("curl -E cert.pem:" + FAKE + " u", "curl -E", FAKE),
    ("curl --pa" + "ss " + FAKE + " u", "curl", FAKE),
    ("aws configure set aws_secret_" + "access_key " + FAKE, "aws configure set", FAKE),
    ("aws secretsmanager create-secret --name n --secret-" + "string " + FAKE, "--name n", FAKE),
    (
        "aws secretsmanager create-secret --secret-"
        + 'string "{\\"user\\":\\"diegor\\",'
        + '\\"pass'
        + 'word\\":\\"'
        + FAKE
        + '\\"}"',
        "diegor",
        FAKE,
    ),
    ("aws ssm put-parameter --name /x --va" + 'lue "' + FAKE + '" --type SecureString', "/x", FAKE),
    ("curl -su alice:" + FAKE + " h", "curl -su", FAKE),
    ("curl -vU alice:" + FAKE + " h", "curl -vU", FAKE),
    ("npm config set '//r/:_auth" + "Token' " + FAKE, "npm config set", FAKE),
    ("curl -x u:" + FAKE + "@proxy:8080 h", "@proxy:8080", FAKE),
    ("curl --client-secret=" + FAKE + " x", "--client-secret", FAKE),
    ("az login --service-principal -u app " + "-p " + FAKE + " --tenant t", "--tenant t", FAKE),
    ("az acr login -n r -u u " + "-p" + FAKE, "az acr login", FAKE),
    ("az\tlogin -u u " + "-p " + FAKE, "login -u u", FAKE),
    ("az keyvault secret set --vault-name v --name n --va" + "lue " + FAKE, "--name n", FAKE),
    ("az keyvault secret set --name n --va" + 'lue "' + FAKE + ' x"', "--name n", FAKE),
    ("az storage blob upload --account-" + "key " + FAKE + " -f a", "-f a", FAKE),
    ("curl -bsession=" + FAKE + " h", "curl", FAKE),
    ("curl -Ecert.pem:" + FAKE + " h", "curl", FAKE),
    (DOCKER_LOGIN + " ghcr.io -u aj " + PASSWORD_FLAG + " " + FAKE_WORD, "ghcr.io", FAKE_WORD),
    ("uv publish -t pypi-AgE" + "p" * 30, "uv publish -t", "pypi-AgE"),
    ("npm_" + "n" * 36, "[REDACTED]", "npm_"),
    ("curl -H 'Authorization: Basic " + "QWxh" * 4 + "=='", "Basic", "QWxh"),
    ('curl -H "Authorization: Bearer ya29.' + "Ab1" * 100 + '"', "Bearer", "Ab1"),
    ("echo Bearer ya29." + "Ab1" * 100, "echo Bearer", "Ab1"),
    ("AKIA" + "ABCDEFGHIJKLMNOP", "[REDACTED]", "AKIA"),
    ("xoxb-" + "1" * 10 + "-abc", "[REDACTED]", "xoxb"),
    (f"Authorization: Bearer {FAKE}.x", "Bearer [REDACTED]", FAKE),
    (f"https://amy:{FAKE}@host/x", "https://[REDACTED]@host/x", FAKE),
    (f"mysql {PASSWORD_FLAG} {FAKE} -u me", f"{PASSWORD_FLAG} [REDACTED] -u me", FAKE),
    ("password=x run", "password=[REDACTED] run", "=x "),
    ('export GITHUB_TOKEN="two words" ok', "GITHUB_TOKEN=[REDACTED] ok", "two words"),
]


@pytest.mark.parametrize(("text", "kept", "gone"), REDACT_CASES)
def test_redact_removes_each_secret_shape(dl, text, kept, gone):
    out = dl.redact(text)
    assert kept in out and gone not in out


@pytest.mark.parametrize(
    "text",
    [
        "gh auth login",
        "gh auth status --hostname github.com",
        "git commit -m 'fix token refresh'",
        "GIT_AUTHOR_NAME=AJ git commit",
        "author=AJ",
        "sk-short",
        "grep -n password README.md",
        "git push -u origin main",
        "mkdir -p build && tar -pxf a.tar",
        "git log -p -1",
        "docker run -p 8080:80 nginx",
        "gh pr create -b 'a body' -t title",
        "uv run -p 3.12 pytest",
        "npm run build -- -p x",
        "aws s3 ls s3://bucket",
        "curl -x http://proxy:8080 h",
        "aws ssm get-parameter --name /x",
        "az group create --name rg --location westus",
        "curl -sSL https://x",
    ],
)
def test_redact_leaves_look_alikes_alone(dl, text):
    assert dl.redact(text) == text


# Ordinary commands an agent runs; the redactor must hand each back unchanged.
ORDINARY = [
    "git status",
    "git log --oneline -20",
    "git diff origin/main...HEAD -- plugins",
    "git push -u origin feat/x",
    "git commit -m 'fix token refresh' -m 'see #12'",
    "git checkout -b fix/auth-flow",
    "git rebase -i HEAD~3",
    "git remote add origin https://github.com/o/r.git",
    "gh pr create --title 'docs: x' --body-file b.md --label bug",
    "gh pr view 12 --json state,mergeStateStatus",
    "gh api repos/o/r/pulls/12/comments --jq '.[].body'",
    "gh secret list",
    "gh auth status",
    "uv run pytest -q tests/test_auth.py",
    "uv sync --all-extras",
    "uv run ruff check --fix .",
    "npm ci && npm run build",
    "npm test -- --runInBand",
    "docker run -u 1000:1000 -v $PWD:/w img",
    "docker run --user 1000:1000 img",
    "docker exec -u root:root c sh",
    "docker build -t app:latest .",
    "sudo -u www-data:www-data ls",
    "ssh -p 2222 host uptime",
    "scp -P 2222 a.txt host:/tmp/",
    "mysql -h db -P 3306 -u app",
    "curl -sSL https://example.com/install.sh",
    "curl -H 'Accept: application/json' https://api.example.com",
    "make test-hooks-oldest",
    "python3 -m http.server 8000",
    "jq '.token_type' resp.json",
    "grep -rn 'password' docs/",
    "sed -i 's/old/new/' README.md",
    "tar -czf out.tgz build/",
    "mkdir -p build/out",
    "ls -la ~/.config",
    "cat ~/.ssh/config",
    "export PATH=$HOME/.local/bin:$PATH",
    "kubectl get pods -n default",
    "terraform plan -out tf.plan",
    "cargo test -p core --release",
    "go test ./... -run TestAuth",
    "pip index versions requests",
    "echo author=AJ",
    "git config user.email aj@example.com",
    "git tag -a v1.2 -m 'release'",
    "rsync -av src/ dst/",
    "find . -name '*.py' -newer setup.cfg",
    "tmux send-keys -t w 'ls' Enter",
    "node -e 'console.log(1)'",
    "git commit -m 'Bearer support'",
    "echo Basic usage",
    "git commit -m 'Basic auth tests'",
    "git commit -m 'refresh auth: handle expired token'",
    "git commit -m 'oauth: fix'",
    "git commit -m 'secret: rotate'",
    "gh issue create --title 'token: expires early'",
    "gh pr list --search 'auth:x'",
    "grep -n 'token:' config.yml",
    "docker build --secret id=npmrc,src=.npmrc .",
    "gh auth login --with-token < tok.txt",
    "export GH_TOKEN=$(gh auth token)",
    "git commit -m 'Support Bearer token-based auth'",
    "git commit -m 'Basic auth-header parsing'",
    "git commit -m 'Authorization: check scopes'",
    "git commit -m 'auth: python3.12 compat'",
    "git commit -m 'token: refresh_v2 path'",
    "git commit -m 'secret: sha256-based keys'",
    "git commit -m 'Basic authentication/authorization overview'",
    "git commit -m 'test: Bearer token_expired_401 case'",
    "git commit -m 'auth: OAuth2Callback handler'",
    "git commit -m 'token: getAccessToken2'",
    "git commit -m 'Authorization: requireAdmin2 guard'",
    "gh pr create --title 'secret: SecretStr2 wrapper'",
    "git commit -m 'pass" + "word: bcrypt/scrypt/argon2 options'",  # built: not a key to scanners
    "git commit -m 'secret: k8s/ExternalSecret manifests'",
    "git commit -m 'cache (token: v2Cache)'",
    'grep -rn "api_key=" src/',
    "rg -n 'TOKEN=' .github/workflows",
    "git grep -n \"token=\" -- '*.py'",
    'git log -S "api_key=" --oneline',
    'git commit -m "fix: pass token=None when unauthenticated"',
    "C(token=None)",
    "git clone https://user@github.com/o/r",
    "GIT_AUTHOR_NAME=AJ git commit -m x",
    "GH_TOKEN= gh api user",
    "rg '\"token\":' src/",
    "grep -rn '\"api_key\": ' config/",
]


@pytest.mark.parametrize("text", ORDINARY)
def test_ordinary_commands_pass_the_redactor_unchanged(dl, text):
    assert dl.redact(text) == text


# Fragments that make a backtracking pattern retry at every position when repeated: every
# keyword the patterns name, after each separator, so a new pattern cannot dodge the sweep.
_KEYWORDS = [
    "token",
    "auth",
    "secret",
    "password",
    "api_key",
    "Authorization",
    "Bearer",
    "Basic",
    "curl",
    "mysql",
    "docker login",
    "gh secret set",
    "sshpass",
    "eyJ",
    "ghp_",
    "sk-",
    "hf_",
    "pypi-AgE",
    "npm_",
    "-----BEGIN ",
    "://a",
]
_SEPARATORS = ["", " ", ":", ": ", "=", ":a", ":-", "=a", " -p", " -u", " --token ", "'"]
ADVERSARIAL = sorted(
    {k + sep for k in _KEYWORDS for sep in _SEPARATORS}
    | {"a", "-", " ", "'", '"', "=", ":", "a:", "Aa1", "\n"}
)


@pytest.mark.parametrize("fragment", ADVERSARIAL)
def test_every_redaction_pattern_stays_linear(dl, fragment):
    # Time each pattern at two sizes, best of three: four times the input takes about four
    # times as long when linear and sixteen when quadratic, whatever the machine's speed.
    def took(n: int, pattern: str, repl: str, times: int = 3) -> float:
        text = fragment * max(1, n // len(fragment))
        return cpu_median(lambda: re.sub(pattern, repl, text), times)

    for pattern, repl in all_patterns(dl):
        if took(20000, pattern, repl, times=1) < 0.005:
            continue  # fast at the large size: no growth worth measuring
        large, small = took(20000, pattern, repl), took(5000, pattern, repl)
        assert large / max(small, 1e-6) < 9, (pattern, fragment, small, large)


def test_the_two_pending_paths_agree_and_ignore_a_relative_state_home(monkeypatch, tmp_path):
    go, dl = load_phylax_hooks(monkeypatch, "git_options", "denial_log")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert go.pending_denials() == dl.pending_dir()
    monkeypatch.delenv("XDG_STATE_HOME")
    monkeypatch.setenv("HOME", str(tmp_path))
    assert go.pending_denials() == dl.pending_dir()
    assert dl.pending_dir().startswith(str(tmp_path / ".local" / "state"))
    monkeypatch.setenv("XDG_STATE_HOME", "relative/state")  # the spec: ignore it
    assert (
        go.pending_denials()
        == dl.pending_dir()
        == f"{tmp_path}/.local/state/phylax/pending-denials"
    )


def test_the_hooks_inline_gates_agree_with_pending_any(monkeypatch, tmp_path):
    mg, eg, dl = load_phylax_hooks(monkeypatch, "model_guard", "email_greeting", "denial_log")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    for xdg in (str(tmp_path / "xdg"), "relative/state", None):
        if xdg is None:
            monkeypatch.delenv("XDG_STATE_HOME", raising=False)
        else:
            monkeypatch.setenv("XDG_STATE_HOME", xdg)
        folder = pathlib.Path(dl.pending_dir())
        assert not dl.pending_any() and not mg._denial_waits() and not eg._denial_waits()
        folder.mkdir(parents=True)
        assert dl.pending_any() and mg._denial_waits() and eg._denial_waits(), xdg
        folder.rmdir()
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.delenv("HOME")
    assert not mg._denial_waits() and not eg._denial_waits()  # no HOME: nowhere to look


def test_a_stale_record_is_dropped_unlogged(dl, state, monkeypatch):
    dl.record_denial({"session_id": SESSION}, "block_commits_md", "no", "git add COMMITS.md")
    later = time.time() + dl.STALE_PENDING_SEC + 1
    monkeypatch.setattr(dl.time, "time", lambda: later)
    dl.check_next_call({"session_id": SESSION}, "Bash", "ls")
    assert [r["event"] for r in rows(state)] == ["deny"]
    assert not dl.pending_any()


def test_an_unreadable_record_is_dropped(dl, state):
    pending(state).mkdir(parents=True)
    (pending(state) / f"{SESSION}.json").write_text("{not json")
    dl.check_next_call({"session_id": SESSION}, "Bash", "ls")
    assert rows(state) == [] and not dl.pending_any()


def test_a_folder_removed_between_mkdir_and_open_is_made_again(dl, state, monkeypatch):
    real_open = os.open
    raced = []

    def racing_open(path, *args, **kwargs):
        if str(path).endswith(".json") and not raced:
            raced.append(path)
            raise FileNotFoundError(path)
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(dl.os, "open", racing_open)
    assert dl.record_denial({"session_id": SESSION}, "g", "r", "c")
    assert raced and (pending(state) / f"{SESSION}.json").is_file()


def test_a_reason_quoting_a_secret_is_redacted(dl, state):
    dl.record_denial({"session_id": SESSION}, "g", f"the line 'token={FAKE}' is refused", "c")
    (deny,) = rows(state)
    assert FAKE not in deny["reason"] and "token=[REDACTED]" in deny["reason"]


def test_record_files_are_private(dl, state):
    dl.record_denial({"session_id": "a/../b"}, "g", "r", "c")
    log = state / "phylax" / "denied-calls.jsonl"
    (record,) = pending(state).iterdir()
    assert record.name == "a____b.json"  # the session id cannot leave the folder
    for p in (log, record):
        assert p.stat().st_mode & 0o777 == 0o600


def test_a_record_written_into_an_existing_folder_is_private(dl, state):
    dl.record_denial({"session_id": OTHER}, "g", "r", "c")  # makes the folder
    dl.record_denial({"session_id": SESSION}, "g", "r", "c")  # opens straight into it
    record = pending(state) / f"{SESSION}.json"
    assert record.stat().st_mode & 0o777 == 0o600
    assert json.loads(record.read_text())["guard"] == "g"


def test_a_folder_another_session_made_first_is_used(dl, state, monkeypatch):
    # The first open finds no folder; another session makes it before this one's makedirs.
    real = dl.os.open
    calls = []

    def racing_open(path, flags, mode=0o777):
        if path.endswith(f"{SESSION}.json") and not calls:
            calls.append(path)  # the record's first open: the folder appears just after it fails
            os.makedirs(os.path.dirname(path), mode=0o700)
            raise FileNotFoundError(path)
        return real(path, flags, mode)

    monkeypatch.setattr(dl.os, "open", racing_open)
    assert dl.record_denial({"session_id": SESSION}, "g", "r", "c") is not None
    assert calls  # the race was run
    record = pending(state) / f"{SESSION}.json"
    assert record.stat().st_mode & 0o777 == 0o600


def test_the_log_rotates_past_its_cap(monkeypatch, tmp_path):
    (jl,) = load_phylax_hooks(monkeypatch, "jsonl_log")
    path = str(tmp_path / "x" / "log.jsonl")
    jl.append(path, {"n": 1}, max_bytes=10)
    jl.append(path, {"n": 2}, max_bytes=10)
    assert json.loads((tmp_path / "x" / "log.jsonl.1").read_text())["n"] == 1
    (row,) = [json.loads(line) for line in open(path)]
    assert row["n"] == 2 and "ts" in row


def test_a_log_of_exactly_the_cap_is_not_rotated(monkeypatch, tmp_path):
    (jl,) = load_phylax_hooks(monkeypatch, "jsonl_log")
    path = tmp_path / "log.jsonl"
    jl.append(str(path), {"n": 1})
    jl.append(str(path), {"n": 2}, max_bytes=path.stat().st_size)
    assert not (tmp_path / "log.jsonl.1").exists()
    assert len(path.read_text().splitlines()) == 2


def test_the_secret_gate_log_goes_through_the_shared_writer(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    (ss,) = load_phylax_hooks(monkeypatch, "secret_scan")
    ss.log_event({"outcome": "caught"})
    (row,) = [json.loads(line) for line in ss.log_path().read_text().splitlines()]
    assert row["outcome"] == "caught" and "ts" in row
    assert ss.log_path().stat().st_mode & 0o777 == 0o600


def test_a_deny_sweeps_records_a_session_left_behind(dl, state):
    # A session that ends right after a deny never makes the call that clears its record;
    # without the sweep the folder, and every call's slow path, would stay forever.
    dl.record_denial({"session_id": OTHER}, "g", "r", "c")
    old = pending(state) / f"{OTHER}.json"
    past = time.time() - dl.STALE_PENDING_SEC - 5
    os.utime(old, (past, past))
    dl.record_denial({"session_id": SESSION}, "g", "r", "c")
    assert not old.exists() and (pending(state) / f"{SESSION}.json").exists()


NEVER_BLOCK = {
    # hook script, its options, (tool_name, a passing input), (tool_name, a refused input)
    "git": (
        "git_guards.py",
        {"block_commits_md": "true"},
        ("Bash", {"command": "ls -la"}),
        ("Bash", {"command": "git add COMMITS.md"}),
    ),
    "shapes": (
        "git_guards.py",
        {"block_pkill_full": "true"},
        ("Bash", {"command": "ls -la"}),
        ("Bash", {"command": "pkill -f worker"}),
    ),
    "agent": (
        "model_guard.py",
        {"require_subagent_model": "true"},
        ("Agent", {"prompt": "p", "subagent_type": "general-purpose", "model": "opus"}),
        ("Agent", {"prompt": "p", "subagent_type": "general-purpose"}),
    ),
    "email": (
        "email_greeting.py",
        {"email_greeting": "true", "email_timezone": "America/New_York"},
        (DRAFT, {"to": "a@example.com", "subject": "x"}),
        (DRAFT, {"to": "a@example.com", "subject": "x", "body": "Hi,\n\nx"}),
    ),
}


@pytest.mark.parametrize("hook", sorted(NEVER_BLOCK))
@pytest.mark.parametrize("broken", ["missing", "raises"])
def test_a_broken_denial_log_never_blocks_a_call(tmp_path, state, broken, hook):
    # The log is telemetry: with a record waiting and denial_log.py gone or crashing on
    # import, every hook still passes a plain call and still refuses a guarded one.
    script, options, passing, refused = NEVER_BLOCK[hook]
    hooks = tmp_path / "hooks"
    shutil.copytree(ROOT / "plugins/phylax/hooks", hooks)
    (hooks / "denial_log.py").unlink()
    if broken == "raises":
        (hooks / "denial_log.py").write_text("raise RuntimeError('broken log')\n")
    pending(state).mkdir(parents=True)
    (pending(state) / f"{SESSION}.json").write_text('{"id": "x", "ts": 0}')
    env = hook_env(
        list(options),
        drop=("PHYLAX_", "CLAUDE_CODE_SUBAGENT_MODEL", "ANTHROPIC_"),
        XDG_STATE_HOME=str(state),
        HOME=str(tmp_path),
    )
    env.update({f"CLAUDE_PLUGIN_OPTION_{k.upper()}": v for k, v in options.items()})
    argv = [sys.executable, str(hooks / script), *(["--shapes"] if hook == "shapes" else [])]

    def run(call):
        tool_name, tool_input = call
        payload = {
            "session_id": SESSION,
            "cwd": str(tmp_path),
            "tool_name": tool_name,
            "tool_input": tool_input,
        }
        return subprocess.run(
            argv,
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env=env,
            cwd=tmp_path,
            check=False,
        )

    quiet = run(passing)
    assert (quiet.returncode, quiet.stdout) == (0, ""), quiet.stderr
    loud = run(refused)
    assert loud.returncode == 0 and '"deny"' in loud.stdout, loud.stderr


def test_every_git_refusal_goes_through_verdict_deny():
    # A refusal appended straight to denies would be logged under another guard's name.
    src = (ROOT / "plugins/phylax/hooks/git_checks.py").read_text()
    direct = [
        line.strip()
        for line in src.splitlines()
        if re.search(r"\.denies\.(append|extend|insert)\(|\.denies\s*\+=", line)
    ]
    assert direct == ["self.denies.append(why)"]  # inside Verdict.deny itself


@pytest.mark.parametrize(
    "text",
    ["a-" * 50000, "-" * 50000, "QUJD-_" * 35000, "x" * 200000, "token=" + "a" * 100000],
)
def test_redaction_of_a_huge_command_stays_fast(dl, state, text):
    # Quadratic backtracking on long [A-Za-z0-9_-] or dash runs took 15 s on a 150 KB prompt,
    # past the 10 s hook timeout, so logging could refuse an allowed call.
    start = time.perf_counter()
    dl.clip(text)
    dl.redact(text[:20000])  # redact itself stays linear, for any caller that skips clip
    dl.record_denial({"session_id": SESSION}, "g", text, text)
    assert time.perf_counter() - start < 0.5
    (deny,) = rows(state)
    assert len(deny["command"]) < 1100 and len(deny["reason"]) < 1100


def test_a_huge_prompt_after_a_deny_passes_well_inside_the_timeout(state, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    agent = ("Agent|Task", "require_subagent_model", "Agent")
    assert denied(tool(state, home, *agent, {"description": "x", "prompt": "p"}))
    blob = "QUJD-_" * 25000
    start = time.perf_counter()
    out = tool(state, home, *agent, {"description": "x", "prompt": blob, "model": "opus"})
    assert out is None and time.perf_counter() - start < 5
    deny, nxt = rows(state)
    assert nxt["id"] == deny["id"] and len(nxt["command"]) < 1100


def test_a_subagents_deny_pairs_only_with_its_own_next_call(state, repo):
    on = ["block_commits_md"]
    assert denied(bash(state, repo, "git add COMMITS.md", on=on, agent_id="a1"))
    bash(state, repo, "npm test", on=on, agent_id="a2")  # a sibling: not a1's next call
    bash(state, repo, "ls", on=on)  # the main thread: not a1's either
    assert [r["event"] for r in rows(state)] == ["deny"]
    bash(state, repo, "git status", on=on, agent_id="a1")
    deny, nxt = rows(state)
    assert nxt["id"] == deny["id"] and nxt["agent_id"] == deny["agent_id"] == "a1"


def test_another_actors_record_costs_two_access_calls_and_no_import(dl, state, monkeypatch):
    (go,) = load_phylax_hooks(monkeypatch, "git_options")
    dl.record_denial({"session_id": OTHER}, "g", "r", "c")
    raw = json.dumps({"session_id": SESSION, "tool_input": {"command": "ls"}})
    assert go.pending_record(raw) is False
    assert go.pending_record(json.dumps({"session_id": OTHER, "tool_input": {}})) is True
    sub = json.dumps({"session_id": OTHER, "agent_id": "a9", "tool_input": {}})
    assert go.pending_record(sub) is False


@pytest.mark.parametrize(
    "payload",
    [
        '{"session_id": "a\\"b", "tool_input": {}}',
        '{"session_id": 5}',
        '{"tool_input": {}}',
        '{"session_id": "s", "agent_id": "a\\u00e9"}',
    ],
)
def test_ids_that_cannot_be_read_cheaply_take_the_full_path(monkeypatch, state, payload):
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    (go,) = load_phylax_hooks(monkeypatch, "git_options")
    pending(state).mkdir(parents=True)
    assert go.pending_record(payload) is True


@pytest.mark.parametrize("seed", range(40))
def test_the_cheap_actor_key_matches_the_full_one(dl, monkeypatch, seed):
    # Differential: git_options reads the ids from raw text; denial_log from the parsed JSON.
    import random

    (go,) = load_phylax_hooks(monkeypatch, "git_options")
    rng = random.Random(seed)
    fields = {"cwd": "/w", "tool_input": {"command": rng.choice(['echo "x"', "ls", 'grep "a" b'])}}
    fields["session_id"] = rng.choice([SESSION, "a b", "ü-é", "x" * 80, "s/../t"])
    if rng.random() < 0.5:
        fields["agent_id"] = rng.choice(["a1", "sub agent", "é"])
    items = list(fields.items())
    rng.shuffle(items)
    raw = json.dumps(dict(items), indent=rng.choice([None, 1]), ensure_ascii=rng.random() < 0.5)
    data = json.loads(raw)
    sid, agent = go._raw_value(raw, "session_id"), go._raw_value(raw, "agent_id")
    if "\\" in (sid or "") or "\\" in (agent or ""):
        return  # those take the full path (tested above)
    assert sid == data["session_id"] and agent == data.get("agent_id")
    assert (
        go.safe_id(sid + (f".{agent}" if agent else ""))
        == re.sub(r"[^A-Za-z0-9_-]", "_", dl.actor_of(data))[:64]
    )


def test_a_stale_folder_is_swept_by_the_next_call(dl, state, monkeypatch, repo):
    dl.record_denial({"session_id": OTHER}, "g", "r", "c")
    past = time.time() - dl.STALE_PENDING_SEC - 5
    os.utime(pending(state) / f"{OTHER}.json", (past, past))
    os.utime(pending(state), (past, past))
    bash(state, repo, "ls", on=["block_commits_md"])
    assert not pending(state).exists()


def test_a_long_body_refusal_is_logged_under_its_own_guard(state, repo):
    body = "word " * 400
    on = ["block_long_bodies", "block_commits_md"]
    command = f"gh pr create --title t --body '{body}' && git add COMMITS.md"
    assert denied(bash(state, repo, command, on=on))
    (deny,) = rows(state)
    assert deny["guard"] == "block_long_bodies"
    assert deny["reason"].splitlines()[0].startswith("phylax:") and "COMMITS.md" in deny["reason"]


# --- the module's lookups, each key and fallback pinned ----------------------------------


@pytest.mark.parametrize(
    ("data", "want"),
    [
        ({"session_id": "s", "sessionId": "x", "conversationId": "y"}, "s"),
        ({"session_id": "", "sessionId": "x", "conversationId": "y"}, "x"),
        ({"sessionId": "", "conversationId": "y"}, "y"),
        ({"tool_use_id": "toolu_1"}, "default"),
        ({}, "default"),
        ({"session_id": 7}, "7"),
    ],
)
def test_session_id_of_each_key_in_order(dl, data, want):
    assert dl.session_id_of(data) == want


@pytest.mark.parametrize(
    ("data", "want"),
    [
        ({"session_id": "s"}, "s"),
        ({"session_id": "s", "agent_id": "a1"}, "s.a1"),
        ({"session_id": "s", "agent_id": ""}, "s"),
        ({"session_id": "s", "agent_id": 5}, "s"),
    ],
)
def test_actor_of_adds_a_subagent(dl, data, want):
    assert dl.actor_of(data) == want


@pytest.mark.parametrize(
    ("data", "want"),
    [
        ({"toolCall": {"args": {}}}, "agy"),
        ({"conversationId": "c"}, "agy"),
        ({"toolCall": "not a dict"}, "claude-code"),
        ({"tool_name": "Bash"}, "claude-code"),
    ],
)
def test_harness_of(dl, data, want):
    assert dl.harness_of(data) == want


@pytest.mark.parametrize(
    ("data", "want"),
    [
        ({"tool_input": {"command": "ls"}, "toolCall": {"args": {"CommandLine": "x"}}}, "ls"),
        ({"toolCall": {"args": {"CommandLine": "agy cmd", "command": "y"}}}, "agy cmd"),
        ({"toolCall": {"args": {"command": "agy2"}}}, "agy2"),
        ({"tool_input": {"prompt": "p"}}, "{'prompt': 'p'}"),
        ({"toolCall": None, "tool_input": None}, "{}"),
    ],
)
def test_command_of_each_shape(dl, data, want):
    assert dl.command_of(data) == want


@pytest.mark.parametrize(
    ("denied", "nxt", "guard", "want"),
    [
        ("git commit -m x", "git commit -m y", "g", True),
        ("git push origin a", "git push origin b", "g", True),
        ("pkill -f w", "kill 12", "g", True),
        ("kill 3", "pkill -f w", "g", True),
        ("gh pr create", "gh issue create", "g", True),
        ("gh issue edit 1", "gh api repos/o/r/pulls", "g", True),
        ("gh pr create", "ls", "g", False),
        ("gh pr create", "gh pr view 1", "g", True),
        ("git status", "gh pr view 1", "g", False),
        ("git commit -m x", "git push", "g", False),
        ("ls", "ls", "g", False),
        ("{'x': 1}", "{'subagent_type': 'Explore'}", "require_subagent_model", True),
        ("{'x': 1}", "{'prompt': 'p', 'model': 'opus'}", "require_subagent_model", True),
        ("x", "Agent ok", "require_subagent_model", True),
        ("x", "task ok", "require_subagent_model", True),
        ("x", "ls", "require_subagent_model", False),
        ("x", "the draft", "email_greeting", True),
        ("x", "a message", "email_greeting", True),
        ("x", "an email", "email_greeting", True),
        ("x", "{'body': 'b'}", "email_greeting", True),
        ("x", "ls", "email_greeting", False),
        ("x", "the draft", "other_guard", False),
    ],
)
def test_same_action_each_kind(dl, denied, nxt, guard, want):
    assert dl.same_action(denied, nxt, guard) is want


def test_next_call_rows_carry_every_field(dl, state, monkeypatch):
    t = [1000.0]
    monkeypatch.setattr(dl.time, "time", lambda: t[0])
    data = {"session_id": SESSION, "agent_id": "a1", "tool_use_id": "toolu_5"}
    call_id = dl.record_denial(data, "block_commits_md", "no", "git add COMMITS.md")
    t[0] = 1002.123456
    dl.check_next_call({**data, "tool_use_id": "toolu_6"}, "Bash", "git status")
    deny, nxt = rows(state)
    assert deny == {
        "ts": deny["ts"],
        "epoch": 1000.0,
        "id": call_id,
        "event": "deny",
        "session_id": SESSION,
        "agent_id": "a1",
        "tool_use_id": "toolu_5",
        "harness": "claude-code",
        "guard": "block_commits_md",
        "command": "git add COMMITS.md",
        "reason": "no",
    }
    assert nxt == {
        "ts": nxt["ts"],
        "epoch": 1002.123456,
        "id": call_id,
        "event": "next_call",
        "session_id": SESSION,
        "agent_id": "a1",
        "tool_use_id": "toolu_6",
        "harness": "claude-code",
        "tool_name": "Bash",
        "command": "git status",
        "same_action": False,
        "seconds_after": 2.123,
    }
    assert re.fullmatch(r"1000-[0-9a-f]{8}", call_id)
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d{4}", deny["ts"])


def test_the_default_command_is_read_from_the_hook_input(dl, state):
    data = {"session_id": SESSION, "tool_input": {"command": "git add COMMITS.md"}}
    dl.record_denial(data, "block_commits_md", "no")
    dl.check_next_call({"session_id": SESSION, "toolCall": {"args": {"CommandLine": "ls"}}}, "x")
    deny, nxt = rows(state)
    assert deny["command"] == "git add COMMITS.md" and nxt["command"] == "ls"


def test_a_command_of_exactly_the_limit_is_not_marked_cut(dl):
    assert dl.clip("x" * dl.COMMAND_MAX) == "x" * dl.COMMAND_MAX
    assert dl.clip("x" * (dl.COMMAND_MAX + 1)).endswith(f"…[{dl.COMMAND_MAX + 1} chars]")


@pytest.mark.parametrize(("age", "kept"), [(0, True), (3600, True), (3601, False)])
def test_records_age_out_after_exactly_an_hour(dl, state, monkeypatch, age, kept):
    t = [10_000_000.0]
    monkeypatch.setattr(dl.time, "time", lambda: t[0])
    dl.record_denial({"session_id": SESSION}, "g", "r", "c")
    t[0] += age
    dl.check_next_call({"session_id": SESSION}, "Bash", "ls")
    assert ([r["event"] for r in rows(state)] == ["deny", "next_call"]) is kept


@pytest.mark.parametrize(("age", "swept"), [(3600, False), (3601, True)])
def test_the_sweep_drops_records_older_than_an_hour(dl, state, monkeypatch, age, swept):
    dl.record_denial({"session_id": OTHER}, "g", "r", "c")
    old = pending(state) / f"{OTHER}.json"
    os.utime(old, (5_000_000, 5_000_000))
    monkeypatch.setattr(dl.time, "time", lambda: 5_000_000.0 + age)
    dl.record_denial({"session_id": SESSION}, "g", "r", "c")
    assert old.exists() is not swept


@pytest.mark.parametrize("missing", ["id", "ts", "guard", "command"])
def test_a_record_missing_a_key_is_dropped_unlogged(dl, state, missing):
    pending(state).mkdir(parents=True)
    record = {"id": "x", "ts": time.time(), "guard": "g", "command": "c"}
    del record[missing]
    (pending(state) / f"{SESSION}.json").write_text(json.dumps(record))
    dl.check_next_call({"session_id": SESSION}, "Bash", "ls")
    assert rows(state) == [] and not dl.pending_any()


def test_the_record_folder_is_private(dl, state):
    dl.record_denial({"session_id": SESSION}, "g", "r", "c")
    assert pending(state).stat().st_mode & 0o777 == 0o700


def test_two_shape_refusals_are_logged_as_one_reason(dl, state, monkeypatch):
    (cs,) = load_phylax_hooks(monkeypatch, "command_shapes")
    dl.shapes_denied({"session_id": SESSION}, [cs.FULL_DENY["pkill"], cs.LOOP_DENY])
    (deny,) = rows(state)
    assert deny["guard"] == "block_pkill_full"
    assert deny["reason"] == cs.FULL_DENY["pkill"] + "\n" + cs.LOOP_DENY


def test_an_agy_call_is_logged_as_run_command(dl, state):
    agy = {"conversationId": SESSION, "toolCall": {"args": {"CommandLine": "git add COMMITS.md"}}}
    dl.record_denial(agy, "block_commits_md", "no")
    nxt = {"conversationId": SESSION, "toolCall": {"args": {"CommandLine": "ls -la"}}}
    dl.next_bash_call(json.dumps(nxt))
    deny, row = rows(state)
    assert row["tool_name"] == "run_command" and row["command"] == "ls -la"
    assert row["harness"] == deny["harness"] == "agy"


# --- git_options' cheap reads ------------------------------------------------------------


@pytest.fixture
def go(monkeypatch, state):
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    (mod,) = load_phylax_hooks(monkeypatch, "git_options")
    return mod


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        ('{"session_id": "abc"}', "abc"),
        ('{"session_id":"abc","x":1}', "abc"),
        ('{"session_id" : "a"}', "a"),
        ('{"session_id": ""}', ""),
        ('{"tool_input": {}}', None),
        ('{"session_id": 5}', "\\"),
        ('{"session_id": "a\\"b"}', "\\"),
        ('{"session_id"}', "\\"),
        ('{"session_id": "unterminated', "\\"),
        ('{"session_id": null}', "\\"),
        ('"session_id": "a"', "a"),
        ('{"session_id": "a", "tool_input": {"session_id": "b"}}', "a"),
    ],
)
def test_raw_value_reads_a_plain_string_or_says_it_cannot(go, raw, want):
    assert go._raw_value(raw, "session_id") == want


@pytest.mark.parametrize(
    ("actor", "want"),
    [
        ("abc-DEF_1", "abc-DEF_1"),
        ("a.b/c", "a_b_c"),
        ("ü", "_"),
        ("", "default"),
        ("x" * 70, "x" * 64),
    ],
)
def test_safe_id_keeps_only_safe_ascii(go, actor, want):
    assert go.safe_id(actor) == want


def test_state_home_ignores_a_relative_or_missing_value(go, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_STATE_HOME", "/abs/state")
    assert go.state_home() == "/abs/state"
    assert go.pending_denials() == "/abs/state/phylax/pending-denials"
    for value in ("rel/state", ""):
        monkeypatch.setenv("XDG_STATE_HOME", value)
        assert go.state_home() == f"{tmp_path}/.local/state"
    monkeypatch.delenv("XDG_STATE_HOME")
    assert go.state_home() == f"{tmp_path}/.local/state"
    monkeypatch.delenv("HOME")
    assert go.state_home() == "/.local/state"


def test_pending_record_for_each_case(go, dl, state, monkeypatch):
    own = json.dumps({"session_id": SESSION, "tool_input": {}})
    assert go.pending_record(own) is False  # no folder at all
    dl.record_denial({"session_id": OTHER}, "g", "r", "c")
    assert go.pending_record(own) is False  # another session's record only
    dl.record_denial({"session_id": SESSION, "agent_id": "a1"}, "g", "r", "c")
    assert go.pending_record(own) is False  # this session's subagent, not its main thread
    assert go.pending_record(json.dumps({"session_id": SESSION, "agent_id": "a1"})) is True
    dl.record_denial({"session_id": SESSION}, "g", "r", "c")
    assert go.pending_record(own) is True
    stale = time.time() - go.STALE_PENDING_SEC - 5
    os.unlink(pending(state) / f"{SESSION}.json")
    os.utime(pending(state), (stale, stale))
    assert go.pending_record(own) is True  # a stale folder wants a sweep
    fresh = time.time() - go.STALE_PENDING_SEC + 60
    os.utime(pending(state), (fresh, fresh))
    assert go.pending_record(own) is False


def test_pending_record_at_exactly_the_stale_age_or_a_vanished_folder(go, dl, state, monkeypatch):
    own = json.dumps({"session_id": SESSION, "tool_input": {}})
    dl.record_denial({"session_id": OTHER}, "g", "r", "c")
    mtime = os.stat(pending(state)).st_mtime
    monkeypatch.setattr(go.time, "time", lambda: mtime + go.STALE_PENDING_SEC)
    assert go.pending_record(own) is False  # not yet older than the limit

    def gone(path, *a, **k):
        raise FileNotFoundError(path)

    monkeypatch.setattr(go.os, "stat", gone)  # removed between access() and stat()
    assert go.pending_record(own) is False


def test_clip_drops_a_word_its_window_cuts(dl):
    # A token touching the window's edge may continue past it, so it is dropped, not shown.
    window = dl.COMMAND_MAX + 1024
    token = "ghp_" + "A" * (window - 900 - 4)
    text = "x" * 899 + " " + token + " unscanned"
    assert len("x" * 899 + " " + token) == window
    assert dl.clip(text) == "x" * 899 + " " + f"…[{len(text)} chars]"
    assert dl.clip("x" * 5000) == "…[5000 chars]"  # one word longer than the window


def test_a_token_cut_at_the_window_edge_never_slides_into_view(dl):
    # A long Bearer value shrinks to [REDACTED], pulling later text into the 1,000 kept; a
    # token the window cut short no longer matches its pattern and must not be what slides in.
    head = "Authorization: Bearer " + "j" * 1200 + " "
    pad = "y" * (1985 - len(head) - 1) + " "
    text = head + pad + "ghp_" + "B" * 60 + " tail"
    assert text.index("ghp_") == 1985
    shown = dl.clip(text)
    assert "ghp_" not in shown and "BBBB" not in shown


def test_a_record_in_another_json_encoding_is_still_read(dl, state):
    # json.loads reads UTF-8, UTF-16 and UTF-32 bytes alike; the record is opened as bytes.
    dl.record_denial({"session_id": SESSION}, "block_commits_md", "no", "git add COMMITS.md")
    path = pending(state) / f"{SESSION}.json"
    path.write_bytes(path.read_text().encode("utf-16"))
    dl.check_next_call({"session_id": SESSION}, "Bash", "ls")
    assert [r["event"] for r in rows(state)] == ["deny", "next_call"]


def test_a_second_deny_before_the_next_call_replaces_the_record(dl, state):
    dl.record_denial({"session_id": SESSION}, "block_commits_md", "first", "git add COMMITS.md")
    second = dl.record_denial({"session_id": SESSION}, "block_secrets", "second", "git push")
    record = json.loads((pending(state) / f"{SESSION}.json").read_text())
    assert record["id"] == second and record["guard"] == "block_secrets"
    assert record["command"] == "git push"


def test_prose_naming_a_flag_loses_the_next_word_by_design(dl):
    # The redactor prefers over-redaction: a flag's value may be a lower-case password.
    assert dl.redact("feat: add --token flag") == "feat: add --token [REDACTED]"


def cpu_median(run, times: int = 3) -> float:
    """The median CPU time of RUN: CPU time, unlike wall time, does not count the moments
    another process holds the core, so a loaded machine does not fail the sweep."""
    took = []
    for _ in range(times):
        start = time.process_time()
        run()
        took.append(time.process_time() - start)
    return sorted(took)[len(took) // 2]


def all_patterns(dl):
    """Every redaction pattern, each once: the general ones and each command-anchored flag
    pattern (USERINFO and SQL_PASSWORD serve several commands)."""
    return list(
        dict.fromkeys([*dl.TOKEN_PATTERNS, *(f for _, _, flags in dl.ANCHORED for f in flags)])
    )


@pytest.mark.parametrize("head", ["curl ", "curl -u ", "mysql -p", "npm set a_auth ", "x;", "'"])
def test_redact_as_a_whole_stays_linear(dl, head):
    small = cpu_median(lambda: dl.redact(head * 5000))
    large = cpu_median(lambda: dl.redact(head * 20000))
    assert large < 0.01 or large / max(small, 1e-6) < 9, (head, small, large)


# A keyword's head, then one long run: a pattern whose classes overlap after its head (curl's
# `-u` and `=`) retries from every character of the run.
_HEADS = [k + sep for k in _KEYWORDS for sep in ("", " ", "=", ":", " -u ", " -p ")] + [
    "curl -u ",
    "curl --user=",
    "uv publish -p ",
    "-H 'X-Token: ",
    "npm config set a_authToken ",
]


@pytest.mark.parametrize("tail", ["=", " ", "a", ":", "-", "'", "a:"])
def test_every_redaction_pattern_stays_linear_on_a_long_tail(dl, tail):
    def took(n: int, text_head: str, pattern: str, repl: str, times: int = 3) -> float:
        text = text_head + tail * n
        return cpu_median(lambda: re.sub(pattern, repl, text), times)

    for head in _HEADS:
        for pattern, repl in all_patterns(dl):
            if took(10000, head, pattern, repl, times=1) < 0.005:
                continue  # fast at the large size: no growth worth measuring
            large, small = took(10000, head, pattern, repl), took(2500, head, pattern, repl)
            assert large / max(small, 1e-6) < 9, (pattern, head, tail, small, large)


def test_every_pattern_has_triggers_that_never_hide_a_match(dl):
    # A pattern runs only when one of its triggers is in the text, so a trigger list that
    # misses a shape the pattern matches would silently skip that secret.
    assert len(dl.TRIGGERS) == len(dl.TOKEN_PATTERNS)
    texts = [*ORDINARY, *ADVERSARIAL, *_HEADS]
    texts += [t for t, _, _ in REDACT_CASES]
    texts += [t.replace("%", "-").format(v=FAKE) for t in SWEEP]
    for text in texts:
        for (pattern, _), triggers in zip(dl.TOKEN_PATTERNS, dl.TRIGGERS, strict=True):
            if re.search(pattern, text):
                assert dl.triggered(text.lower(), triggers), (pattern, text[:80])
        for words, triggers, flags in dl.ANCHORED:
            if all(re.search(w, text) for w in words) and any(re.search(p, text) for p, _ in flags):
                assert any(t in text.lower() for t in triggers), (words, text[:80])


def test_a_refusal_naming_no_secret_runs_no_pattern(dl, monkeypatch):
    # The refusal path's cost: a fresh hook process would compile every pattern it runs.
    calls = []
    real = dl.re.sub
    monkeypatch.setattr(dl.re, "sub", lambda *a, **k: calls.append(a[0]) or real(*a, **k))
    dl.clip("{'prompt': 'review the diff and report', 'subagent_type': 'general-purpose'}")
    dl.clip("git add COMMITS.md")
    dl.clip("phylax: name the model it runs on, or pass model: with the call")  # its own reason
    assert calls == []
    # The control: a text holding a secret does run its patterns.
    dl.clip("curl " + "-u" + " alice:" + FAKE + " https://x")
    assert calls


def test_of_two_calls_at_once_only_the_one_that_claims_the_record_logs(dl, state, monkeypatch):
    data = {"session_id": SESSION}
    dl.record_denial(data, "block_commits_md", "no", "git add COMMITS.md")
    real = dl.os.rename

    def the_other_call_reads_mid_claim(src, dst):
        real(src, dst)
        dl.check_next_call(data, "Bash", "git status")  # finds nothing left to claim

    monkeypatch.setattr(dl.os, "rename", the_other_call_reads_mid_claim)
    dl.check_next_call(data, "Bash", "git log")
    events = [r["event"] for r in rows(state)]
    assert events == ["deny", "next_call"]
    assert (
        not list(pathlib.Path(dl.pending_dir()).glob("*.claim"))
        if pathlib.Path(dl.pending_dir()).exists()
        else True
    )


# The closed-list sweep (git, gh, curl, wget, uv, twine, npm, docker, kubectl, aws, gcloud, az,
# sshpass and ssh-keygen, mysql and psql): each tool's documented command-line secret forms.
# `%` stands for `-` and {v} for the value, filled in at runtime so no scanner reads a secret.
SWEEP = [
    "docker login %p '{v} tail' ghcr.io",
    "uv publish %p '{v} tail'",
    "twine upload %p '{v} tail'",
    "mysql %p'{v} tail'",
    "sshpass %p '{v} tail' ssh h",
    "aws configure set aws_secret_access_key '{v} tail'",
    "npm set //r/:_authToken '{v} tail'",
    "curl %x 'u:{v} x@p' h",
    "git config http.proxy u:{v}@proxy:8080",
    "git send-email %%smtp-pass {v} a.patch",
    "git config sendemail.smtpPass {v}",
    "curl %%proxy-pass {v} h",
    "curl %%proxy-cert c.pem:{v} h",
    "wget %e 'http_password = {v}' u",
    "uv auth login host %t {v}",
    "uv auth login host %t{v}",
    "DOCKER_CONTENT_TRUST_ROOT_PASSPHRASE={v} docker push x",
    "kubectl config set users.u.token {v}",
    "kubectl config set users.u.password {v}",
    "kubectl config set users.admin.client-key-data {v}",
    "kubectl create secret generic s %%from-literal=key1={v}",
    "aws s3 cp a s3://b %%sse-c-key {v}",
    "aws s3 cp a s3://b %%sse-c-copy-source-key {v}",
    "aws apigateway create-api-key %%value {v}",
    "aws cloudformation create-stack %%parameters ParameterKey=DB,ParameterValue={v}",
    "gcloud config set proxy/password {v}",
    "az storage x %%storage-key {v}",
    "az x %%access-key {v}",
    "az functionapp keys set %%key-value {v}",
    "az servicebus x %%primary-key {v}",
    "az x %%secondary-key {v}",
    "sshpass %v %p {v} ssh h",
    "sshpass %P prompt %p {v} ssh h",
    "ssh-keygen %N {v} %f k",
    "ssh-keygen %P {v} %p %f k",
    "mysqladmin %p{v} status",
    "mysqlimport %p{v} db f",
    "mysqlshow %p{v}",
    "mysqlcheck %p{v} db",
    "mysqlbinlog %p{v} f",
    "mysqladmin %u root password {v}",
    "mysqlsh root:{v}@host",
    "mysqlsh %%uri root:{v}@host",
    'mysql "%p{v}" db',
    "psql 'host=h password = {v}'",
    "psql 'password={v} dbname=d'",
    "psql %c \"ALTER USER u PASSWORD '{v}'\"",
    "mysql %e \"SET PASSWORD = '{v}'\"",
    "mysql %e \"CREATE USER u IDENTIFIED BY '{v}'\"",
    "mysql %e \"SET PASSWORD FOR 'u'@'h' = '{v}'\"",
    "mysql %e \"ALTER USER u IDENTIFIED WITH caching_sha2_password BY '{v}'\"",
    "mysql %e \"SET PASSWORD FOR u = PASSWORD('{v}')\"",
    "psql %c \"CREATE ROLE r LOGIN PASSWORD '{v}'\"",
    "mysql %e \"SET PASSWORD\n= '{v}'\"",
    "mysql <<EOF\nCREATE USER u IDENTIFIED\nBY '{v}';\nEOF",
    "mysql %e \"ALTER USER u IDENTIFIED WITH 'caching_sha2_password' BY '{v}'\"",
    "curl %%proxy=:{v}@h x",
    "https_proxy=:{v}@host curl x",
    "mysql %e \"SET PASSWORD FOR u\n = '{v}'\"",
    "mysqlsh %%uri=:{v}@h",
    "mysql %e \"SET PASSWORD FOR 'a;b'@h = '{v}'\"",
    "mysql %e \"CREATE USER u IDENTIFIED WITH 'a;b' BY '{v}'\"",
    "mysql %e \"SET PASSWORD FOR 'u'@'" + "h" * 200 + "' = '{v}'\"",
    "mysql %e \"ALTER USER u IDENTIFIED WITH '" + "p" * 65 + "' BY '{v}'\"",
    'mysql %e "SET PASSWORD FOR u' + " " * 150 + "= '{v}'\"",
    "mysql %e \"SET PASSWORD FOR 'a\\'b'@h = '{v}'\"",
    "mysql <<EOF\nSET PASSWORD FOR \"a;b\"@h = '{v}';\nEOF",
    "mysql <<EOF\nSET PASSWORD FOR `a;b`@h = '{v}';\nEOF",
    'mysql %e "SET PASSWORD FOR \\"u\\"@h = \'{v}\'"',
    'mysql <<EOF\nSET PASSWORD FOR "u"@"' + "h" * 200 + "\" = '{v}';\nEOF",
    "mysql <<EOF\nSET PASSWORD FOR `u`@`" + "h" * 200 + "` = '{v}';\nEOF",
]


@pytest.mark.parametrize("template", SWEEP)
def test_the_closed_list_sweep_is_redacted(dl, template):
    text = template.replace("%", "-").format(v=FAKE)
    out = dl.redact(text)
    assert FAKE not in out and "tail'" not in out, out


@pytest.mark.parametrize(
    "text",
    [
        "psql -p 5432 -h db",
        "git clone git@github.com:o/r.git",
        "kubectl get pods -n x",
        "gcloud config set project p",
        "ssh-keygen -t ed25519 -f k",
        "wget https://x/f",
        "mysql -u root -h db",
        "git log --since=2.weeks",
    ],
)
def test_the_sweep_leaves_its_tools_plain_lines_alone(dl, text):
    assert dl.redact(text) == text
