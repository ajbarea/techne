import json
import stat

import pytest
from epistole import auth, config

TOML = '[accounts]\nschool = "user@example.edu"\n'


@pytest.fixture
def cfg(tmp_path):
    (tmp_path / "accounts.toml").write_text(TOML)
    (tmp_path / "client_secret.json").write_text("{}")
    return config.load(tmp_path)


def test_save_token_is_private(tmp_path):
    path = auth.token_path(tmp_path, "school")
    auth.save_token(path, '{"token": "x"}')
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_missing_token_says_how_to_log_in(tmp_path):
    with pytest.raises(auth.LoginRequired, match="epistole-login school"):
        auth.load_credentials(tmp_path, "school")


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
    assert auth.token_path(tmp_path, "school").is_file()


def test_unknown_alias_is_refused(tmp_path, cfg):
    with pytest.raises(auth.LoginRequired, match="no account 'work'"):
        auth.login(
            tmp_path,
            cfg,
            "work",
            flow_factory=lambda: FakeFlow("x"),
            profile_email=lambda c: c.email,
        )
