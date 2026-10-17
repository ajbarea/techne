import stat

import pytest
from schole import cli, config


@pytest.mark.parametrize(
    ("site", "want"),
    [
        ("https://mycourses.rit.edu", "https://mycourses.rit.edu"),
        ("https://lms.example.edu/", "https://lms.example.edu"),
    ],
)
def test_site_must_be_an_https_origin(site, want):
    assert config.check_site(site) == want


@pytest.mark.parametrize(
    "site", ["http://lms.example.edu", "https://lms.example.edu/d2l/home", "lms.example.edu", ""]
)
def test_bad_sites_are_refused(site):
    with pytest.raises(config.ConfigError):
        config.check_site(site)


def test_save_and_load_round_trip_privately(tmp_path):
    cfg = config.Config("https://lms.example.edu", "2261", "America/New_York")
    config.save(tmp_path, cfg)
    assert config.load(tmp_path) == cfg
    assert stat.S_IMODE((tmp_path / "schole.toml").stat().st_mode) == 0o600


@pytest.mark.parametrize(
    "body",
    [
        'site = "https://x.example"\nextra = 1\n',
        'site = "https://x.example"\nterm = 5\n',
        'site = "https://x.example"\ntimezone = "Mars/Base"\n',
        "site = [\n",
    ],
)
def test_bad_config_is_refused(tmp_path, body):
    (tmp_path / "schole.toml").write_text(body)
    with pytest.raises(config.ConfigError):
        config.load(tmp_path)


def test_profile_is_private(tmp_path):
    path = config.profile(tmp_path / "home")
    assert stat.S_IMODE(path.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_sweep_without_config_names_the_login_command(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SCHOLE_HOME", str(tmp_path))
    assert cli.main(["sweep"]) == 1
    assert "schole-login --site" in capsys.readouterr().err


class FakeCtx:
    def __init__(self, pages=1):
        self.pages = [object()] * pages


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("SCHOLE_HOME", str(tmp_path))
    config.save(tmp_path, config.Config("https://lms.example.edu", "2261", None))
    return tmp_path


def fake_browser(ctx):
    import contextlib

    @contextlib.contextmanager
    def browser(base, headless):
        yield ctx

    return browser


def test_term_alone_updates_the_saved_config(home, monkeypatch):
    monkeypatch.setattr(cli, "browser", fake_browser(FakeCtx()))
    monkeypatch.setattr(cli, "signed_in", lambda ctx, site: True)
    assert cli.main(["login", "--term", "2262", "--status"]) == 0
    assert config.load(home) == config.Config("https://lms.example.edu", "2262", None)


def test_status_reports_needs_login(home, monkeypatch, capsys):
    monkeypatch.setattr(cli, "browser", fake_browser(FakeCtx()))
    monkeypatch.setattr(cli, "signed_in", lambda ctx, site: False)
    assert cli.main(["login", "--status"]) == 3
    assert "needs login" in capsys.readouterr().out


def test_login_reports_a_closed_window(home, monkeypatch, capsys):
    class Page:
        def goto(self, url):
            pass

    ctx = FakeCtx()
    ctx.pages = [Page()]
    monkeypatch.setattr(cli, "browser", fake_browser(ctx))
    monkeypatch.setattr(cli, "POLL", 0)

    def signed_in(c, site):
        c.pages.clear()
        return False

    monkeypatch.setattr(cli, "signed_in", signed_in)
    assert cli.main(["login"]) == 1
    assert "closed before sign-in finished" in capsys.readouterr().err


def test_first_login_needs_a_site(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SCHOLE_HOME", str(tmp_path))
    assert cli.main(["login", "--term", "2261"]) == 1
    assert "--site" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("message", "want"),
    [
        ("Executable doesn't exist at /x/chrome", "playwright install chromium"),
        ("Failed to create ProcessSingleton", "profile is in use"),
        ("Target page, context or browser has been closed", "window closed"),
    ],
)
def test_browser_failures_name_the_fix(message, want):
    assert want in cli.browser_failure(RuntimeError(message))


class CookieJar:
    def __init__(self, cookies):
        self.jar = list(cookies)

    def cookies(self):
        return list(self.jar)

    def add_cookies(self, cookies):
        self.jar.extend(cookies)


SESSION_COOKIE = {
    "name": "d2lSessionVal",
    "value": "s",
    "domain": "lms.example.edu",
    "path": "/",
    "expires": -1,
}
LASTING_COOKIE = {
    "name": "remember",
    "value": "r",
    "domain": "lms.example.edu",
    "path": "/",
    "expires": 2e9,
}


def test_session_cookies_outlive_the_browser_privately(tmp_path):
    saved = tmp_path / cli.SESSION
    cli.keep_session(CookieJar([SESSION_COOKIE, LASTING_COOKIE]), saved)
    assert stat.S_IMODE(saved.stat().st_mode) == 0o600
    fresh = CookieJar([])
    cli.restore_session(fresh, saved)
    assert fresh.jar == [SESSION_COOKIE]


@pytest.mark.parametrize("body", [None, "", "{not json", "{}", "[]"])
def test_missing_or_bad_session_file_adds_nothing(tmp_path, body):
    saved = tmp_path / cli.SESSION
    if body is not None:
        saved.write_text(body)
    fresh = CookieJar([])
    cli.restore_session(fresh, saved)
    assert fresh.jar == []
