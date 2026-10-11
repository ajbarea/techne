import json
import stat

import pytest
from epistole import auth, config
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials

TOML = '[accounts]\nschool = "user@example.edu"\n'


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
        return json.dumps({"refresh_token": "r"})


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
    inner = {"client_id": "id-123.apps.example", "client_secret": "SECRET-xyz", **over}
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
