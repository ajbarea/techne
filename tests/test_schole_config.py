import json
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
    def browser(base, site, headless):
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


class BrowserError(Exception):
    pass


BrowserError.__module__ = "playwright._impl._errors"
SITE = "https://lms.example.edu"


def cookie(name, domain, expires=-1):
    return {"name": name, "value": "v", "domain": domain, "path": "/", "expires": expires}


SESSION = cookie("d2lSessionVal", "lms.example.edu")
PARENT = cookie("lb", ".example.edu")
SSO = cookie("idp_session", "sso.example.edu")
LASTING = cookie("remember", "lms.example.edu", expires=2e9)


class CookieJar:
    def __init__(self, cookies=(), refuse=False):
        self.jar = list(cookies)
        self.refuse = refuse
        self.closed = False

    def cookies(self):
        if self.closed:
            raise BrowserError("Target page, context or browser has been closed")
        return list(self.jar)

    def add_cookies(self, cookies):
        if self.refuse:
            raise BrowserError("Cookie should have a url or a domain/path pair")
        self.jar.extend(cookies)

    def close(self):
        self.closed = True


def fake_playwright(monkeypatch, ctx):
    import contextlib
    import sys
    import types

    class Chromium:
        def launch_persistent_context(self, *args, **kwargs):
            return ctx

    @contextlib.contextmanager
    def sync_playwright():
        yield types.SimpleNamespace(chromium=Chromium())

    api = types.ModuleType("playwright.sync_api")
    api.sync_playwright = sync_playwright  # ty: ignore[unresolved-attribute]
    monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", api)


def saved_file(base):
    return config.profile(base) / cli.SESSION


def test_only_the_sites_session_cookies_are_kept_privately(tmp_path):
    saved = tmp_path / cli.SESSION
    cli.keep_session(CookieJar([SESSION, PARENT, SSO, LASTING]), saved, SITE)
    assert stat.S_IMODE(saved.stat().st_mode) == 0o600
    fresh = CookieJar()
    assert cli.restore_session(fresh, saved, SITE)
    assert fresh.jar == [SESSION, PARENT]


@pytest.mark.parametrize("body", [None, "", "{not json", "{}", "[]", '[1, "x"]', json.dumps([SSO])])
def test_missing_or_bad_session_file_adds_nothing(tmp_path, body):
    saved = tmp_path / cli.SESSION
    if body is not None:
        saved.write_text(body)
    fresh = CookieJar()
    assert cli.restore_session(fresh, saved, SITE)
    assert fresh.jar == []


def test_browser_restores_before_use_and_keeps_on_close(tmp_path, monkeypatch):
    saved_file(tmp_path).write_text(json.dumps([SESSION]))
    ctx = CookieJar()
    fake_playwright(monkeypatch, ctx)
    rotated = cookie("d2lSecureSessionVal", "lms.example.edu")
    with cli.browser(tmp_path, SITE, headless=True) as c:
        assert c.jar == [SESSION]
        c.jar.append(rotated)
    assert ctx.closed
    assert json.loads(saved_file(tmp_path).read_text()) == [SESSION, rotated]


def test_refused_restore_keeps_the_saved_file(tmp_path, monkeypatch, capsys):
    body = json.dumps([SESSION])
    saved_file(tmp_path).write_text(body)
    fake_playwright(monkeypatch, CookieJar(refuse=True))
    with cli.browser(tmp_path, SITE, headless=True):
        pass
    assert saved_file(tmp_path).read_text() == body
    assert "could not restore the saved sign-in" in capsys.readouterr().err


def test_closed_browser_keeps_the_saved_file(tmp_path, monkeypatch):
    body = json.dumps([SESSION])
    saved_file(tmp_path).write_text(body)
    ctx = CookieJar()
    fake_playwright(monkeypatch, ctx)
    with cli.browser(tmp_path, SITE, headless=False):
        ctx.closed = True
    assert saved_file(tmp_path).read_text() == body


def test_unwritable_profile_warns_instead_of_raising(tmp_path, capsys):
    cli.keep_session(CookieJar([SESSION]), tmp_path / "gone" / cli.SESSION, SITE)
    assert "could not save the sign-in" in capsys.readouterr().err


def test_interrupted_private_write_leaves_no_partial_file(tmp_path, monkeypatch):
    def fail(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(config.os, "replace", fail)
    with pytest.raises(OSError):
        config.write_private(tmp_path / "f.json", "secret")
    assert list(tmp_path.iterdir()) == []


def test_save_tightens_an_existing_config(tmp_path):
    file = tmp_path / "schole.toml"
    file.write_text("")
    file.chmod(0o644)
    config.save(tmp_path, config.Config(SITE, "2261", None))
    assert stat.S_IMODE(file.stat().st_mode) == 0o600
