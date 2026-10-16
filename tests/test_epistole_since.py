import json
import stat
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from epistole import since

NY = ZoneInfo("America/New_York")
TOML = 'timezone = "America/New_York"\n[accounts]\nschool = "user@example.edu"\n'


@pytest.fixture
def home(tmp_path, monkeypatch):
    (tmp_path / "accounts.toml").write_text(TOML)
    monkeypatch.setenv("EPISTOLE_HOME", str(tmp_path))
    return tmp_path


@pytest.mark.parametrize(
    ("now", "start"),
    [
        (datetime(2026, 10, 15, 20, 30, tzinfo=NY), datetime(2026, 10, 14, tzinfo=NY)),  # Thu
        (datetime(2026, 10, 19, 8, 0, tzinfo=NY), datetime(2026, 10, 16, tzinfo=NY)),  # Mon
        (datetime(2026, 10, 18, 9, 0, tzinfo=NY), datetime(2026, 10, 17, tzinfo=NY)),  # Sun
    ],
)
def test_default_start_is_yesterday_or_friday_on_monday(now, start):
    assert since.default_start(now) == start


def test_write_then_read_round_trips_and_is_private(home):
    since.write(home, 1_792_000_000, now=1_792_000_100)
    assert since.read(home, now=1_792_000_100) == 1_792_000_000
    assert stat.S_IMODE((home / since.FILE).stat().st_mode) == 0o600


def test_future_or_ancient_set_is_refused(home):
    with pytest.raises(ValueError, match="future"):
        since.write(home, 2_000_000_000, now=1_792_000_000)
    with pytest.raises(ValueError, match="year ago"):
        since.write(home, 0, now=1_792_000_000)
    assert since.read(home) is None


@pytest.mark.parametrize("value", [4_102_444_800, 10**15, 0, -5])
def test_implausible_record_falls_back_to_the_default_window(home, value):
    (home / since.FILE).write_text(json.dumps({"last_run": value}))
    assert since.read(home, now=1_792_000_000) is None
    assert "default window" in since.window(home, now=1_792_000_000)


@pytest.mark.parametrize(
    "body", ["not json", "{}", '{"last_run": "1792000000"}', '{"last_run": true}']
)
def test_unreadable_record_counts_as_none(home, body):
    (home / since.FILE).write_text(body)
    assert since.read(home) is None


def test_window_uses_the_record_in_the_configured_zone(home):
    epoch = int(datetime(2026, 10, 15, 19, 43, tzinfo=NY).timestamp())
    since.write(home, epoch, now=epoch + 60)
    out = since.window(home, now=epoch + 3600)
    assert "window start: Thu Oct 15 2026 19:43 EDT (last run)" in out
    assert f"gmail query: after:{epoch - since.OVERLAP}" in out
    assert f"(epoch {epoch + 3600})" in out


def test_window_without_record_says_default(home):
    now = datetime(2026, 10, 15, 20, 30, tzinfo=NY).timestamp()
    out = since.window(home, now=now)
    assert "window start: Wed Oct 14 2026 00:00 EDT (no record; default window)" in out
    assert f"after:{int(datetime(2026, 10, 14, tzinfo=NY).timestamp())}" in out


def test_main_prints_sets_and_rejects_bad_arguments(home, capsys):
    assert since.main([]) == 0
    assert "gmail query: after:" in capsys.readouterr().out
    assert since.main(["--set", "1792000000"]) == 0
    assert "recorded last run:" in capsys.readouterr().out
    assert json.loads((home / since.FILE).read_text()) == {"last_run": 1792000000}
    for bad in (["--set"], ["--set", "-5"], ["--set", "soon"], ["--set", "\u0661\u0667"], ["x"]):
        assert since.main(bad) == 2
    assert since.main(["--set", "9999999999"]) == 1
    assert "future" in capsys.readouterr().err
    assert since.main(["--set", "0"]) == 1


def test_window_works_without_accounts_file(tmp_path, monkeypatch):
    monkeypatch.setenv("EPISTOLE_HOME", str(tmp_path))
    assert since.main([]) == 0


def test_unreadable_accounts_file_falls_back_to_the_system_zone(tmp_path, monkeypatch):
    (tmp_path / "accounts.toml").write_bytes(b"\xff\xfe not utf-8")
    monkeypatch.setenv("EPISTOLE_HOME", str(tmp_path))
    monkeypatch.setenv("TZ", "America/Chicago")
    assert since.zone(tmp_path) == ZoneInfo("America/Chicago")
    assert since.main([]) == 0


def test_system_zone_prefers_an_iana_tz(monkeypatch):
    monkeypatch.setenv("TZ", ":Europe/Berlin")
    assert since._system_zone() == ZoneInfo("Europe/Berlin")
