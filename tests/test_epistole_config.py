import pathlib
import stat
import tomllib

import pytest
from epistole import config

TOML = """
attach_dirs = ["{tmp}/out"]
download_dir = "{tmp}/dl"

[accounts]
school = "user@example.edu"
personal = "user@example.com"
"""


def write(home: pathlib.Path, text: str) -> None:
    home.mkdir(parents=True, exist_ok=True)
    (home / "accounts.toml").write_text(text)


def test_home_honours_env(monkeypatch, tmp_path):
    monkeypatch.setenv("EPISTOLE_HOME", str(tmp_path))
    assert config.home() == tmp_path


def test_load_reads_accounts_and_dirs(tmp_path):
    write(tmp_path, TOML.format(tmp=tmp_path))
    cfg = config.load(tmp_path)
    assert cfg.accounts["school"].address == "user@example.edu"
    assert cfg.attach_dirs == ((tmp_path / "out").resolve(),)
    assert cfg.download_dir == (tmp_path / "dl").resolve()


def test_missing_file_explains_setup(tmp_path):
    with pytest.raises(config.ConfigError, match="epistole-login"):
        config.load(tmp_path)


def test_alias_all_is_reserved(tmp_path):
    write(tmp_path, '[accounts]\nall = "user@example.com"\n')
    with pytest.raises(config.ConfigError, match="reserved"):
        config.load(tmp_path)


@pytest.mark.parametrize("alias", ["a:b", "../x"])
def test_invalid_alias_rejected(tmp_path, alias):
    write(tmp_path, f'[accounts]\n"{alias}" = "user@example.com"\n')
    with pytest.raises(config.ConfigError, match="invalid"):
        config.load(tmp_path)


def test_add_account_creates_file_with_defaults(tmp_path):
    base = tmp_path / "h"
    config.add_account(base, "personal", "User@Example.com")
    assert stat.S_IMODE((base / "accounts.toml").stat().st_mode) == 0o600
    assert stat.S_IMODE(base.stat().st_mode) == 0o700
    cfg = config.load(base)
    assert cfg.accounts["personal"].address == "user@example.com"
    assert cfg.attach_dirs == ()
    assert tomllib.loads((base / "accounts.toml").read_text())["attach_dirs"] == []
    assert cfg.download_dir == pathlib.Path("~/Downloads/epistole").expanduser().resolve()


def test_add_account_preserves_existing_content(tmp_path):
    write(tmp_path, TOML.format(tmp="~/mail"))
    config.add_account(tmp_path, "work", "me@example.org")
    raw = tomllib.loads((tmp_path / "accounts.toml").read_text())
    assert raw["attach_dirs"] == ["~/mail/out"] and raw["download_dir"] == "~/mail/dl"
    assert raw["accounts"] == {
        "school": "user@example.edu",
        "personal": "user@example.com",
        "work": "me@example.org",
    }
    assert stat.S_IMODE((tmp_path / "accounts.toml").stat().st_mode) == 0o600
    assert sorted(p.name for p in tmp_path.iterdir()) == ["accounts.toml"]


def test_add_account_refuses_existing_reserved_and_bad_alias(tmp_path):
    write(tmp_path, TOML.format(tmp=tmp_path))
    before = (tmp_path / "accounts.toml").read_text()
    for alias, match in [
        ("school", "already"),
        ("all", "reserved"),
        ("a:b", "invalid"),
        ("ok\n", "invalid"),
    ]:
        with pytest.raises(config.ConfigError, match=match):
            config.add_account(tmp_path, alias, "x@example.com")
    assert (tmp_path / "accounts.toml").read_text() == before


def test_add_account_quotes_unusual_paths(tmp_path):
    write(tmp_path, 'attach_dirs = ["/srv/C:\\\\Mail \\"q\\""]\n[accounts]\na = "u@example.com"\n')
    config.add_account(tmp_path, "b", "v@example.com")
    raw = tomllib.loads((tmp_path / "accounts.toml").read_text())
    assert raw["attach_dirs"] == ['/srv/C:\\Mail "q"']


def test_check_alias(tmp_path):
    config.check_alias("good_1-x")
    for bad in ["all", "", "a b", "x\n"]:
        with pytest.raises(config.ConfigError):
            config.check_alias(bad)


def test_missing_file_and_empty_accounts_name_the_next_command(tmp_path):
    with pytest.raises(config.ConfigError, match=r"epistole-login --client <downloaded\.json>"):
        config.load(tmp_path)
    (tmp_path / "client_secret.json").write_text("{}")
    with pytest.raises(config.ConfigError) as info:
        config.load(tmp_path)
    assert "`!epistole-login <alias>`" in str(info.value) and "--client" not in str(info.value)
    write(tmp_path, 'download_dir = "~/x"\n')
    with pytest.raises(config.ConfigError, match="epistole-login <alias>"):
        config.load(tmp_path)


def test_add_account_works_on_a_file_with_no_accounts(tmp_path):
    write(tmp_path, 'attach_dirs = ["~/x"]\n')
    config.add_account(tmp_path, "personal", "u@example.com")
    raw = tomllib.loads((tmp_path / "accounts.toml").read_text())
    assert raw["attach_dirs"] == ["~/x"] and raw["accounts"] == {"personal": "u@example.com"}


def test_rewrite_starts_with_a_managed_by_comment(tmp_path):
    config.add_account(tmp_path, "a", "a@example.com")
    first = (tmp_path / "accounts.toml").read_text().splitlines()[0]
    assert first.startswith("#") and "epistole-login" in first and "comments are not kept" in first


@pytest.mark.parametrize(
    "body",
    [
        'attach_dirs = "~/x"\n[accounts]\na = "u@example.com"\n',
        'attach_dirs = [1]\n[accounts]\na = "u@example.com"\n',
        'download_dir = ["x"]\n[accounts]\na = "u@example.com"\n',
        'surprise = 1\n[accounts]\na = "u@example.com"\n',
    ],
)
def test_wrong_shapes_and_unknown_keys_are_refused(tmp_path, body):
    write(tmp_path, body)
    with pytest.raises(config.ConfigError):
        config.load(tmp_path)


@pytest.mark.parametrize(
    "body",
    ['accounts = "x"\n', "[accounts]\nschool = 5\n", '[accounts]\nschool = "no-at-sign"\n'],
)
def test_accounts_table_shape_is_validated(tmp_path, body):
    write(tmp_path, body)
    with pytest.raises(config.ConfigError, match="accounts"):
        config.load(tmp_path)


def test_toml_syntax_error_names_file_and_line(tmp_path):
    write(tmp_path, '[accounts]\nschool = "ok"\nbroken = \n')
    with pytest.raises(config.ConfigError) as info:
        config.load(tmp_path)
    assert "accounts.toml" in str(info.value) and "line 3" in str(info.value)


def test_existing_explicit_attach_dirs_are_unchanged(tmp_path):
    write(tmp_path, 'attach_dirs = ["~/Downloads"]\n[accounts]\na = "u@example.com"\n')
    assert config.load(tmp_path).attach_dirs == (
        pathlib.Path("~/Downloads").expanduser().resolve(),
    )
    config.add_account(tmp_path, "b", "v@example.com")
    assert tomllib.loads((tmp_path / "accounts.toml").read_text())["attach_dirs"] == ["~/Downloads"]


@pytest.mark.parametrize("value", ["rel/home", "./home", "home"])
def test_relative_epistole_home_is_refused(monkeypatch, value):
    monkeypatch.setenv("EPISTOLE_HOME", value)
    with pytest.raises(config.ConfigError, match="EPISTOLE_HOME"):
        config.home()


def test_tilde_epistole_home_expands(monkeypatch):
    monkeypatch.setenv("EPISTOLE_HOME", "~/x")
    assert config.home() == pathlib.Path("~/x").expanduser()


@pytest.mark.parametrize(
    "body",
    [
        'attach_dirs = ["out"]\n[accounts]\na = "u@example.com"\n',
        'download_dir = "dl"\n[accounts]\na = "u@example.com"\n',
        'download_dir = "./dl"\n[accounts]\na = "u@example.com"\n',
    ],
)
def test_relative_paths_in_accounts_toml_are_refused(tmp_path, body):
    write(tmp_path, body)
    with pytest.raises(config.ConfigError, match="absolute"):
        config.load(tmp_path)


def test_rewrite_round_trips_every_control_character(tmp_path):
    weird = "/x/" + "".join(chr(c) for c in [*range(1, 32), 0x7F, 0x85]) + "y"
    write(tmp_path, f'download_dir = {config._q(weird)}\n[accounts]\na = "u@example.com"\n')
    config.add_account(tmp_path, "b", "v@example.com")
    assert tomllib.loads((tmp_path / "accounts.toml").read_text())["download_dir"] == weird


@pytest.mark.parametrize("key", ["attach_dirs", "download_dir"])
def test_unknown_tilde_user_is_a_config_error_naming_the_key(tmp_path, key):
    value = '["~nosuchuser_epistole/x"]' if key == "attach_dirs" else '"~nosuchuser_epistole/x"'
    write(tmp_path, f'{key} = {value}\n[accounts]\na = "u@example.com"\n')
    with pytest.raises(config.ConfigError, match=key):
        config.load(tmp_path)


def test_unknown_tilde_user_in_epistole_home_is_a_config_error(monkeypatch):
    monkeypatch.setenv("EPISTOLE_HOME", "~nosuchuser_epistole/h")
    with pytest.raises(config.ConfigError, match="EPISTOLE_HOME"):
        config.home()


# --- timezone ---


def test_timezone_is_optional_and_read(tmp_path):
    write(tmp_path, TOML.format(tmp=tmp_path))
    assert config.load(tmp_path).timezone is None
    write(tmp_path, 'timezone = "America/New_York"\n' + TOML.format(tmp=tmp_path))
    assert config.load(tmp_path).timezone == "America/New_York"


@pytest.mark.parametrize(
    "value", ['"Mars/Olympus"', '""', "5", '"../etc/passwd"', '"/etc/localtime"']
)
def test_bad_timezone_is_refused(tmp_path, value):
    write(tmp_path, f"timezone = {value}\n" + TOML.format(tmp=tmp_path))
    with pytest.raises(config.ConfigError, match="IANA zone name"):
        config.load(tmp_path)


def test_add_account_keeps_the_timezone(tmp_path):
    write(tmp_path, 'timezone = "America/New_York"\n' + TOML.format(tmp=tmp_path))
    config.add_account(tmp_path, "work", "me@work.example")
    cfg = config.load(tmp_path)
    assert cfg.timezone == "America/New_York" and "work" in cfg.accounts
    config.add_account(tmp_path, "more", "me@more.example")
    assert config.load(tmp_path).timezone == "America/New_York"
