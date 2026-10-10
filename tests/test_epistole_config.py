import pathlib

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
    with pytest.raises(config.ConfigError, match=r"accounts\.toml"):
        config.load(tmp_path)


def test_alias_all_is_reserved(tmp_path):
    write(tmp_path, '[accounts]\nall = "user@example.com"\n')
    with pytest.raises(config.ConfigError, match="reserved"):
        config.load(tmp_path)
