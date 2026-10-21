"""Unit tests for _shared/techne_config.py, the one reader of ~/.claude/techne.toml."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest
from conftest import ROOT, _load

TC = ROOT / "plugins" / "techne" / "_shared" / "techne_config.py"
PARSES_TOML = re.compile(r"\bimport tomllib\b|\bfrom tomllib\b|\btomllib\.loads?\(")


@pytest.fixture(scope="module")
def tc():
    return _load("techne_config", TC)


def write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "techne.toml"
    path.write_text(body, encoding="utf-8")
    return path


def test_no_file_is_none(tc, tmp_path):
    assert tc.load(tmp_path / "absent.toml") is None
    assert tc.load(tmp_path / "not-a-folder" / "techne.toml") is None


def test_a_valid_file_is_parsed(tc, tmp_path):
    assert tc.load(write(tmp_path, 'github_user = "u"\n')) == {"github_user": "u"}


@pytest.mark.parametrize(
    "body", [b"workspace_root = [", b"# caf\xe9\n"], ids=["not-toml", "not-utf8"]
)
def test_a_file_that_is_not_toml_is_invalid(tc, tmp_path, body):
    path = tmp_path / "techne.toml"
    path.write_bytes(body)
    with pytest.raises(tc.ConfigInvalid, match="is not valid TOML"):
        tc.load(path)


def test_a_broken_link_is_unreadable_not_absent(tc, tmp_path):
    link = tmp_path / "techne.toml"
    link.symlink_to(tmp_path / "gone.toml")
    with pytest.raises(tc.ConfigUnreadable, match="a link to a missing file"):
        tc.load(link)


def test_a_folder_is_unreadable(tc, tmp_path):
    (tmp_path / "techne.toml").mkdir()
    with pytest.raises(tc.ConfigUnreadable):
        tc.load(tmp_path / "techne.toml")


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a mode-000 folder")
def test_a_permission_error_is_unreadable(tc, tmp_path):
    folder = tmp_path / "locked"
    folder.mkdir()
    write(folder, 'github_user = "u"\n')
    folder.chmod(0)
    try:
        with pytest.raises(tc.ConfigUnreadable):
            tc.load(folder / "techne.toml")
    finally:
        folder.chmod(0o755)


def test_without_tomllib_an_existing_file_needs_311_and_an_absent_one_is_none(
    tc, tmp_path, monkeypatch
):
    monkeypatch.setitem(sys.modules, "tomllib", None)  # as on python3 3.9
    assert tc.load(tmp_path / "absent.toml") is None
    with pytest.raises(tc.NeedsTomllib, match="cannot read"):
        tc.load(write(tmp_path, 'github_user = "u"\n'))


def test_every_error_is_a_config_error(tc):
    for cls in (tc.NeedsTomllib, tc.ConfigUnreadable, tc.ConfigInvalid):
        assert issubclass(cls, tc.ConfigError)


def test_sisters_are_the_tables_or_none(tc, tmp_path):
    assert tc.sisters({}) == []
    assert tc.sisters({"sisters": [{"name": "a"}]}) == [{"name": "a"}]


@pytest.mark.parametrize(
    "roster, said",
    [("a", "must be a list of tables"), (["a"], "must be a list of tables"),
     ([{"kind": "team"}], "entry 1"), ([{"name": "a"}, {"name": 7}], "entry 2"),
     ([{"name": ""}], "entry 1")],
)  # fmt: skip
def test_a_malformed_roster_raises_rather_than_dropping_entries(tc, roster, said):
    with pytest.raises(tc.ConfigInvalid, match=said):
        tc.sisters({"sisters": roster})


@pytest.mark.parametrize(
    "kind, team", [("team", True), (" Team ", True), ("TEAM", True), ("solo", False), (7, False)]
)
def test_the_kind_rule(tc, kind, team):
    assert tc.is_team({"name": "a", "kind": kind}) is team
    assert tc.is_team({"name": "a"}) is False


def test_status_defaults_to_active(tc):
    assert tc.is_active({"name": "a"})
    assert tc.is_active({"name": "a", "status": "active"})
    assert not tc.is_active({"name": "a", "status": "backburner"})


def test_workspace_root_is_expanded_and_typed(tc, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert tc.workspace_root({"workspace_root": "~/w"}) == tmp_path / "w"
    assert tc.workspace_root({"workspace_root": "/abs"}) == Path("/abs")
    for bad in ({}, {"workspace_root": ""}, {"workspace_root": 3}):
        assert tc.workspace_root(bad) is None
    assert tc.github_user({"github_user": "u"}) == "u"
    assert tc.github_user({"github_user": 1}) is None


def test_matches_by_resolved_path_or_by_owner_slug(tc, tmp_path):
    ws = tmp_path / "ws"
    (ws / "a").mkdir(parents=True)
    alias = tmp_path / "alias"
    alias.symlink_to(ws)
    cfg = {"workspace_root": str(alias), "github_user": "Me"}
    sister = {"name": "A"}
    assert tc.matches(cfg, {"name": "a"}, {ws / "a"}, None)
    assert tc.matches(cfg, sister, {tmp_path / "elsewhere"}, ("me", "a"))
    assert not tc.matches(cfg, sister, {tmp_path / "elsewhere"}, ("other", "a"))
    assert not tc.matches({"workspace_root": str(ws)}, sister, set(), ("me", "a"))


def test_no_other_techne_script_parses_toml_itself():
    """Every reader of techne.toml goes through techne_config, so the failure rules stay one."""
    allowed = {TC, ROOT / "plugins/techne/skills/docs-site/templates/shared/tests/test_docs_nav.py"}
    offenders = [
        path
        for path in (ROOT / "plugins" / "techne").rglob("*.py")
        if path not in allowed and PARSES_TOML.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


@pytest.mark.parametrize("kind", ["dev-zero", "fifo"])
def test_a_device_or_fifo_is_unreadable_without_reading_it(tc, tmp_path, kind):
    path = tmp_path / "techne.toml"
    if kind == "dev-zero":
        path.symlink_to("/dev/zero")
    else:
        os.mkfifo(path)
    with pytest.raises(tc.ConfigUnreadable, match="is not a regular file"):
        tc.load(path)


def test_an_oversized_file_is_unreadable(tc, tmp_path, monkeypatch):
    monkeypatch.setattr(tc, "MAX_BYTES", 64)
    with pytest.raises(tc.ConfigUnreadable, match="is over 64 bytes"):
        tc.load(write(tmp_path, "# " + "x" * 80 + "\n"))


def test_an_unknown_home_user_is_invalid_not_a_crash(tc):
    with pytest.raises(tc.ConfigInvalid, match="names no home folder"):
        tc.workspace_root({"workspace_root": "~nosuchuser-techne/w"})


@pytest.mark.parametrize("status", ["Active", " active ", "ACTIVE"])
def test_status_is_read_in_any_case(tc, status):
    assert tc.is_active({"name": "a", "status": status})
