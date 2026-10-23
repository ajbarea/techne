import json
import os
import shutil
import socket
import stat
import subprocess
from pathlib import Path

import pytest
from epistole import auth, config, login
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials

TOML = '[accounts]\nschool = "user@example.edu"\n'


@pytest.fixture(autouse=True)
def restore_getaddrinfo(monkeypatch):
    """login.main installs epistole's resolver for the process; undo it after each test."""
    monkeypatch.setattr(socket, "getaddrinfo", socket.getaddrinfo)


@pytest.fixture
def cfg(tmp_path):
    (tmp_path / "accounts.toml").write_text(TOML)
    return config.load(tmp_path)


def test_save_token_is_private(tmp_path):
    path = auth.token_path(tmp_path, "school")
    auth.save_token(path, '{"token": "x"}')
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


class FakeCreds:
    def __init__(self, email):
        self.email = email

    def to_json(self):
        return json.dumps({"refresh_token": "r", "who": self.email})


class FakeFlow:
    def __init__(self, email):
        self.email = email
        self.kwargs = {}

    def run_local_server(self, **kwargs):
        self.kwargs = kwargs
        return FakeCreds(self.email)


def test_login_refuses_wrong_account(tmp_path, cfg):
    flow = FakeFlow("someone@example.com")
    with pytest.raises(auth.LoginRequired, match=r"signed in as someone@example\.com"):
        auth.login(
            tmp_path,
            cfg,
            "school",
            flow_factory=lambda: flow,
            profile_email=lambda creds: creds.email,
        )
    assert not auth.token_path(tmp_path, "school").exists()


def test_login_saves_matching_account_on_loopback(tmp_path, cfg):
    flow = FakeFlow("User@Example.edu")
    got = auth.login(
        tmp_path,
        cfg,
        "school",
        flow_factory=lambda: flow,
        profile_email=lambda creds: creds.email,
    )
    assert got == "user@example.edu"
    assert flow.kwargs["host"] == "127.0.0.1" and flow.kwargs["port"] == 0
    assert flow.kwargs["timeout_seconds"] == 300
    assert flow.kwargs["prompt"] == "select_account"
    assert flow.kwargs["login_hint"] == cfg.accounts["school"].address
    assert auth.token_path(tmp_path, "school").is_file()


def test_missing_token_without_client_names_client_import(tmp_path):
    with pytest.raises(auth.LoginRequired, match=r"epistole-login --client <downloaded\.json>"):
        auth.load_credentials(tmp_path, "school")


def test_missing_token_with_client_names_plain_login(tmp_path):
    (tmp_path / "client_secret.json").write_text("{}")
    with pytest.raises(auth.LoginRequired, match=r"`!epistole-login school`"):
        auth.load_credentials(tmp_path, "school")


def test_default_flow_without_client_names_client_import(tmp_path):
    with pytest.raises(auth.LoginRequired, match=r"No Google OAuth client yet.*--client"):
        auth.login(tmp_path, None, "personal")


def fake_login(base, cfg, alias, email, **kw):
    flow = FakeFlow(email)
    got = auth.login(
        base, cfg, alias, flow_factory=lambda: flow, profile_email=lambda c: c.email, **kw
    )
    return got, flow


def test_new_alias_records_the_address_google_returned(tmp_path, cfg):
    got, flow = fake_login(tmp_path, cfg, "work", "Me@Example.org")
    assert got == "me@example.org"
    assert "login_hint" not in flow.kwargs and flow.kwargs["prompt"] == "select_account"
    assert auth.token_path(tmp_path, "work").is_file()
    after = config.load(tmp_path)
    assert after.accounts["work"].address == "me@example.org"
    assert after.accounts["school"].address == "user@example.edu"


def test_first_alias_creates_accounts_toml(tmp_path):
    got, _ = fake_login(tmp_path, None, "personal", "user@example.com")
    assert got == "user@example.com"
    assert config.load(tmp_path).accounts["personal"].address == "user@example.com"
    assert stat.S_IMODE((tmp_path / "accounts.toml").stat().st_mode) == 0o600


@pytest.mark.parametrize("alias", ["all", "a:b", "../x", ""])
def test_bad_new_alias_refused_before_any_browser(tmp_path, cfg, alias):
    def factory():
        raise AssertionError("flow started")

    with pytest.raises(config.ConfigError):
        auth.login(tmp_path, cfg, alias, flow_factory=factory, profile_email=lambda c: "x")
    assert not (tmp_path / "tokens").exists()


def test_new_alias_refuses_an_address_already_recorded(tmp_path, cfg):
    with pytest.raises(auth.LoginRequired, match="already recorded as 'school'"):
        fake_login(tmp_path, cfg, "other", "user@example.edu")
    assert not auth.token_path(tmp_path, "other").exists()
    assert "other" not in config.load(tmp_path).accounts


def client_json(kind="installed", **over):
    inner = {
        "client_id": "id-123.apps.example",
        "client_secret": "SECRET-xyz",
        "auth_uri": "https://accounts.example.com/auth",
        "token_uri": "https://oauth.example.com/token",
        **over,
    }
    return json.dumps({kind: inner, "extra": 1})


def test_import_client_accepts_installed_privately(tmp_path):
    src = tmp_path / "dl.json"
    src.write_text(client_json())
    home = tmp_path / "home"
    auth.import_client(home, src)
    dest = auth.client_secret_path(home)
    assert json.loads(dest.read_text())["installed"]["client_id"] == "id-123.apps.example"
    assert stat.S_IMODE(dest.stat().st_mode) == 0o600
    assert stat.S_IMODE(home.stat().st_mode) == 0o700


def test_import_client_refuses_web_client(tmp_path):
    src = tmp_path / "dl.json"
    src.write_text(client_json("web"))
    with pytest.raises(auth.LoginRequired, match="Desktop app"):
        auth.import_client(tmp_path / "home", src)
    assert not auth.client_secret_path(tmp_path / "home").exists()


@pytest.mark.parametrize(
    "body",
    [
        "not json",
        "[]",
        "{}",
        '{"installed": []}',
        '{"installed": {"client_id": "a"}}',
        '{"installed": {"client_id": "", "client_secret": "s"}}',
    ],
)
def test_import_client_refuses_malformed(tmp_path, body):
    src = tmp_path / "dl.json"
    src.write_text(body)
    with pytest.raises(auth.LoginRequired):
        auth.import_client(tmp_path / "home", src)
    assert not auth.client_secret_path(tmp_path / "home").exists()


def test_import_client_missing_file(tmp_path):
    with pytest.raises(auth.LoginRequired, match="not found"):
        auth.import_client(tmp_path / "home", tmp_path / "nope.json")


def valid_token(**over):
    data = {
        "token": "tok-SECRET",
        "refresh_token": "ref-SECRET",
        "client_id": "c",
        "client_secret": "s",
        "scopes": auth.SCOPES,
        "expiry": "2099-01-01T00:00:00Z",
    }
    return json.dumps({**data, **over})


def test_status_signed_absent_and_corrupt(tmp_path):
    (tmp_path / "accounts.toml").write_text(
        '[accounts]\na = "a@example.com"\nb = "b@example.com"\nc = "c@example.com"\n'
    )
    (tmp_path / "client_secret.json").write_text("{}")
    auth.save_token(auth.token_path(tmp_path, "a"), valid_token())
    auth.save_token(auth.token_path(tmp_path, "c"), '{"refresh_tok')
    report = auth.status(tmp_path)
    assert report.client is True
    assert [(r.alias, r.address, r.ok) for r in report.rows] == [
        ("a", "a@example.com", True),
        ("b", "b@example.com", False),
        ("c", "c@example.com", False),
    ]
    lines = auth.status_lines(report)
    assert lines[0] == "client: present"
    assert lines[1] == "a  a@example.com  signed in"
    assert lines[2].startswith("b  b@example.com  needs login: no token")
    assert "`!epistole-login b`" in lines[2]
    assert lines[3].startswith("c  c@example.com  needs login: unreadable token")
    assert "SECRET" not in "\n".join(lines)
    assert report.all_ok is False


def test_status_all_signed_in_and_no_accounts(tmp_path):
    empty = auth.status(tmp_path)
    assert empty.rows == [] and empty.all_ok is False and empty.client is False
    assert any("no accounts" in line for line in auth.status_lines(empty))
    (tmp_path / "accounts.toml").write_text('[accounts]\na = "a@example.com"\n')
    auth.save_token(auth.token_path(tmp_path, "a"), valid_token())
    assert auth.status(tmp_path).all_ok is True


def test_status_expired_token_that_cannot_refresh(tmp_path, monkeypatch):
    (tmp_path / "accounts.toml").write_text('[accounts]\na = "a@example.com"\n')
    auth.save_token(auth.token_path(tmp_path, "a"), valid_token(expiry="2001-01-01T00:00:00Z"))

    def refuse(self, request):
        raise RefreshError("invalid_grant")

    monkeypatch.setattr(Credentials, "refresh", refuse)
    row = auth.status(tmp_path).rows[0]
    assert row.ok is False and "expired" in row.detail


def test_status_offline_is_not_a_login_problem(tmp_path, monkeypatch):
    from google.auth.exceptions import TransportError

    (tmp_path / "accounts.toml").write_text('[accounts]\na = "a@example.com"\n')
    auth.save_token(auth.token_path(tmp_path, "a"), valid_token(expiry="2001-01-01T00:00:00Z"))

    def offline(self, request):
        raise TransportError("down")

    monkeypatch.setattr(Credentials, "refresh", offline)
    line = auth.status_lines(auth.status(tmp_path))[-1]
    assert "could not check" in line and "needs login" not in line


def test_success_message_text(tmp_path, cfg):
    _, flow = fake_login(tmp_path, cfg, "school", "user@example.edu")
    assert flow.kwargs["success_message"] == (
        "Sign-in received. Return to the terminal to confirm the account."
    )


def test_save_token_leaves_no_temp_files(tmp_path):
    path = auth.token_path(tmp_path, "school")
    auth.save_token(path, "one")
    auth.save_token(path, "two")
    assert path.read_text() == "two"
    assert [p.name for p in path.parent.iterdir()] == ["school.json"]


@pytest.mark.parametrize("body", ['{"refresh_tok', '{"client_id": "c"}'])
def test_unreadable_token_asks_for_login(tmp_path, body):
    path = auth.token_path(tmp_path, "school")
    auth.save_token(path, body)
    with pytest.raises(auth.LoginRequired, match="epistole-login school"):
        auth.load_credentials(tmp_path, "school")


def test_failed_refresh_asks_for_login(tmp_path, monkeypatch):
    auth.save_token(auth.token_path(tmp_path, "school"), "{}")

    class Expired:
        valid = False

        def refresh(self, request):
            raise RefreshError("invalid_grant")

    monkeypatch.setattr(Credentials, "from_authorized_user_file", lambda *a, **k: Expired())
    with pytest.raises(auth.LoginRequired, match="epistole-login school"):
        auth.load_credentials(tmp_path, "school")


def run_main(tmp_path, monkeypatch, argv, email="user@example.com"):
    from epistole import login

    monkeypatch.setenv("EPISTOLE_HOME", str(tmp_path))
    flow = FakeFlow(email)
    return login.main(argv, flow_factory=lambda: flow, profile_email=lambda c: c.email), flow


def test_main_client_alone_and_with_alias(tmp_path, monkeypatch, capsys):
    src = tmp_path / "dl.json"
    src.write_text(client_json())
    rc, _ = run_main(tmp_path, monkeypatch, ["--client", str(src)])
    assert rc == 0 and auth.client_secret_path(tmp_path).is_file()
    rc, _ = run_main(tmp_path, monkeypatch, ["--client", str(src), "personal"])
    out = capsys.readouterr()
    assert rc == 0 and "personal signed in as user@example.com" in out.out
    assert "SECRET-xyz" not in out.out + out.err and "id-123" not in out.out + out.err
    assert config.load(tmp_path).accounts["personal"].address == "user@example.com"


def test_main_bad_client_and_bad_alias_exit_nonzero(tmp_path, monkeypatch, capsys):
    src = tmp_path / "dl.json"
    src.write_text(client_json("web"))
    rc, _ = run_main(tmp_path, monkeypatch, ["--client", str(src)])
    assert rc == 1 and "Desktop app" in capsys.readouterr().err
    rc, _ = run_main(tmp_path, monkeypatch, ["all"])
    assert rc == 1 and "reserved" in capsys.readouterr().err
    rc, _ = run_main(tmp_path, monkeypatch, [])
    assert rc == 2
    rc, _ = run_main(tmp_path, monkeypatch, ["--status", "x"])
    assert rc == 2


def test_main_status_exit_codes(tmp_path, monkeypatch, capsys):
    (tmp_path / "accounts.toml").write_text(
        '[accounts]\na = "a@example.com"\nb = "b@example.com"\n'
    )
    auth.save_token(auth.token_path(tmp_path, "a"), valid_token())
    rc, flow = run_main(tmp_path, monkeypatch, ["--status"])
    out = capsys.readouterr().out.splitlines()
    assert rc == 1 and out[0].startswith("client: missing")
    assert "a  a@example.com  signed in" in out and flow.kwargs == {}
    auth.save_token(auth.token_path(tmp_path, "b"), valid_token())
    rc, _ = run_main(tmp_path, monkeypatch, ["--status"])
    assert rc == 0


# ---- fix round 1 ----


def nested_login(tmp_path, monkeypatch, outer_email, inner_email, alias="rit", inner_alias=None):
    """Run login(alias) whose browser wait is interleaved with a complete second login."""
    from epistole import login

    monkeypatch.setenv("EPISTOLE_HOME", str(tmp_path))

    class Outer(FakeFlow):
        def run_local_server(self, **kwargs):
            inner = FakeFlow(inner_email)
            rc = login.main(
                [inner_alias or alias],
                flow_factory=lambda: inner,
                profile_email=lambda c: c.email,
            )
            assert rc == 0
            return super().run_local_server(**kwargs)

    outer = Outer(outer_email)
    return auth.login(
        tmp_path,
        None,
        alias,
        flow_factory=lambda: outer,
        profile_email=lambda c: c.email,
    )


def test_interleaved_login_never_saves_the_wrong_account_under_an_alias(tmp_path, monkeypatch):
    with pytest.raises(auth.LoginRequired, match=r"signed in as wrong@example\.com.*right@example"):
        nested_login(tmp_path, monkeypatch, "wrong@example.com", "right@example.edu")
    assert config.load(tmp_path).accounts["rit"].address == "right@example.edu"
    assert json.loads(auth.token_path(tmp_path, "rit").read_text())["who"] == "right@example.edu"


def test_interleaved_login_same_account_is_accepted(tmp_path, monkeypatch):
    got = nested_login(tmp_path, monkeypatch, "Right@Example.edu", "right@example.edu")
    assert got == "right@example.edu"
    assert list(config.load(tmp_path).accounts) == ["rit"]


def test_interleaved_logins_never_record_one_address_twice(tmp_path, monkeypatch):
    with pytest.raises(auth.LoginRequired, match="already recorded as 'b1'"):
        nested_login(tmp_path, monkeypatch, "a@example.com", "a@example.com", "b2", "b1")
    assert list(config.load(tmp_path).accounts) == ["b1"]
    assert not auth.token_path(tmp_path, "b2").exists()


def test_failed_account_write_leaves_no_token(tmp_path, monkeypatch):
    def fail(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(config, "add_account", fail)
    with pytest.raises(OSError):
        fake_login(tmp_path, None, "new", "n@example.com")
    assert not auth.token_path(tmp_path, "new").exists()


def test_main_relative_client_resolves_against_caller_directory(tmp_path, monkeypatch):
    work = tmp_path / "downloads"
    work.mkdir()
    (work / "installed.json").write_text(client_json())
    elsewhere = tmp_path / "plugin"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setenv("EPISTOLE_CWD", str(work))
    rc, _ = run_main(tmp_path / "home", monkeypatch, ["--client", "./installed.json"])
    assert rc == 0 and auth.client_secret_path(tmp_path / "home").is_file()


def test_relative_epistole_home_is_refused_by_login(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("EPISTOLE_CWD", str(tmp_path))
    monkeypatch.setenv("EPISTOLE_HOME", "rel/home")
    assert login.main(["--status"]) == 1
    assert "EPISTOLE_HOME" in capsys.readouterr().err
    assert not (tmp_path / "rel").exists()


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv not installed")
def test_wrapper_passes_the_callers_directory(tmp_path):
    work = tmp_path / "downloads"
    work.mkdir()
    (work / "installed.json").write_text(client_json())
    wrapper = Path(__file__).resolve().parent.parent / "plugins/epistole/bin/epistole-login"
    env = {
        **os.environ,
        "EPISTOLE_HOME": str(tmp_path / "home"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),  # the wrapper syncs its venv here
    }
    env.pop("EPISTOLE_CWD", None)
    done = subprocess.run(
        [str(wrapper), "--client", "installed.json"],
        cwd=work,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert (tmp_path / "home" / "client_secret.json").is_file()
    assert "SECRET-xyz" not in done.stdout + done.stderr


def test_main_reports_unticked_permission_in_one_line(tmp_path, monkeypatch, capsys):
    class Unticked(FakeFlow):
        def run_local_server(self, **kwargs):
            raise Warning("Scope has changed from a to b")

    from epistole import login

    monkeypatch.setenv("EPISTOLE_HOME", str(tmp_path))
    rc = login.main(["new"], flow_factory=lambda: Unticked("x"), profile_email=lambda c: "x")
    err = capsys.readouterr().err
    assert rc == 1 and "Traceback" not in err and len(err.strip().splitlines()) == 1
    assert "both Gmail" in err and "epistole-login new" in err


def test_main_catches_any_other_failure_without_traceback(tmp_path, monkeypatch, capsys):
    from epistole import login

    class WSGITimeoutError(AttributeError):
        pass

    for exc, text in [
        (WSGITimeoutError("t"), "timed out"),
        (OSError("disk"), "OSError"),
        (RuntimeError("SECRET-xyz"), "RuntimeError"),
    ]:

        class Boom(FakeFlow):
            def run_local_server(self, _exc=exc, **kwargs):
                raise _exc

        monkeypatch.setenv("EPISTOLE_HOME", str(tmp_path))
        rc = login.main(["new"], flow_factory=lambda: Boom("x"), profile_email=lambda c: "x")
        err = capsys.readouterr().err
        assert rc == 1 and "Traceback" not in err and text in err and "SECRET-xyz" not in err


def test_binary_client_file_is_refused_cleanly(tmp_path):
    src = tmp_path / "dl.json"
    src.write_bytes(b"\xff\xfe\x00\x80")
    with pytest.raises(auth.LoginRequired):
        auth.import_client(tmp_path / "home", src)


def test_import_client_requires_endpoints(tmp_path):
    src = tmp_path / "dl.json"
    src.write_text('{"installed": {"client_id": "x", "client_secret": "s"}}')
    with pytest.raises(auth.LoginRequired, match="auth_uri"):
        auth.import_client(tmp_path / "home", src)


@pytest.mark.parametrize("body", ["[]", "null", "5"])
def test_non_object_token_is_one_rows_problem(tmp_path, body):
    (tmp_path / "accounts.toml").write_text(
        '[accounts]\na = "a@example.com"\nb = "b@example.com"\n'
    )
    auth.save_token(auth.token_path(tmp_path, "a"), body)
    auth.save_token(auth.token_path(tmp_path, "b"), valid_token())
    rows = auth.status(tmp_path).rows
    assert [r.ok for r in rows] == [False, True]
    assert "unreadable token" in rows[0].detail


def test_status_refresh_is_bounded(tmp_path, monkeypatch):
    (tmp_path / "accounts.toml").write_text('[accounts]\na = "a@example.com"\n')
    auth.save_token(auth.token_path(tmp_path, "a"), valid_token(expiry="2001-01-01T00:00:00Z"))
    seen = {}

    def refresh(self, request):
        seen["timeout"] = request.keywords["timeout"]
        raise RefreshError("invalid_grant")

    monkeypatch.setattr(Credentials, "refresh", refresh)
    auth.status(tmp_path)
    assert seen["timeout"] == auth.STATUS_TIMEOUT <= 15


def test_missing_client_names_the_alias_asked_for(tmp_path):
    with pytest.raises(auth.LoginRequired, match=r"--client <downloaded\.json> personal`"):
        auth.login(tmp_path, None, "personal")


def test_empty_alias_argument_is_refused_not_ignored(tmp_path, monkeypatch, capsys):
    src = tmp_path / "dl.json"
    src.write_text(client_json())
    rc, _ = run_main(tmp_path, monkeypatch, ["--client", str(src), ""])
    assert rc == 1 and "invalid" in capsys.readouterr().err


def test_first_login_with_an_existing_file_that_has_no_accounts(tmp_path, monkeypatch, capsys):
    (tmp_path / "accounts.toml").write_text('attach_dirs = ["~/x"]\n')
    rc, _ = run_main(tmp_path, monkeypatch, ["personal"])
    assert rc == 0 and "personal signed in" in capsys.readouterr().out
    assert config.load(tmp_path).accounts["personal"].address == "user@example.com"


def test_status_reports_a_syntax_error_as_a_config_error(tmp_path, monkeypatch, capsys):
    (tmp_path / "accounts.toml").write_text("[accounts\n")
    rc, _ = run_main(tmp_path, monkeypatch, ["--status"])
    err = capsys.readouterr().err
    assert rc == 1 and "accounts.toml" in err and "sign-in failed" not in err


@pytest.mark.parametrize("secret", ["", None])
def test_missing_or_empty_secret_says_how_to_get_one(tmp_path, secret):
    inner = {"client_id": "x", "auth_uri": "a", "token_uri": "t"}
    if secret is not None:
        inner["client_secret"] = secret
    src = tmp_path / "dl.json"
    src.write_text(json.dumps({"installed": inner}))
    with pytest.raises(auth.LoginRequired, match="new client secret"):
        auth.import_client(tmp_path / "home", src)


def test_login_reports_an_unknown_tilde_user_as_a_config_error(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    home.mkdir()
    (home / "accounts.toml").write_text(
        'attach_dirs = ["~nosuchuser_epistole/x"]\n[accounts]\na = "u@example.com"\n'
    )
    monkeypatch.setenv("EPISTOLE_HOME", str(home))
    assert login.main(["--status"]) == 1
    err = capsys.readouterr().err
    assert "attach_dirs" in err and "RuntimeError" not in err
