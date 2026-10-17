"""heuresis setup doctor: tools, folders, keys."""

from __future__ import annotations

import json
import subprocess

from conftest import DOCTOR_LINE, HOOK_PYTHON, ROOT, _load

DOCTOR = ROOT / "plugins" / "heuresis" / "skills" / "setup" / "scripts" / "doctor.py"
d = _load("heuresis_doctor", DOCTOR)


def names(checks):
    return {c.name: c.status for c in checks}


def test_missing_ideas_repo_is_missing_and_keys_are_optional(tmp_path):
    values = {"IDEAS_REPO": str(tmp_path / "nope"), "REPOS_ROOT": str(tmp_path)}
    found = names(d.checks(values, environ={}))
    assert found["ideas_repo"] == "missing"
    assert found["OPENALEX_API_KEY"] == "optional"
    assert found["LENS_API_TOKEN"] == "optional"


def test_unset_key_points_at_plugin_configure(tmp_path):
    values = {"IDEAS_REPO": str(tmp_path), "REPOS_ROOT": str(tmp_path)}
    lines = {c.name: c.detail for c in d.checks(values, environ={})}
    for env in ("S2_API_KEY", "EPO_OPS"):
        assert "/plugin configure heuresis@techne" in lines[env]
        assert "restart" in lines[env]
    assert "Needs both EPO_OPS_KEY and EPO_OPS_SECRET." in lines["EPO_OPS"]


def test_key_lines_are_pinned(tmp_path):
    values = {"IDEAS_REPO": str(tmp_path), "REPOS_ROOT": str(tmp_path)}
    lines = {c.name: (c.status, c.detail) for c in d.checks(values, environ={"S2_API_KEY": "x"})}
    store = "Store it with /plugin configure heuresis@techne, then restart."
    assert lines["OPENALEX_API_KEY"] == (
        "optional",
        f"not set. Raises OpenAlex's search budget; free at openalex.org/settings/api. {store}",
    )
    assert lines["S2_API_KEY"] == ("ok", "set")
    assert lines["LENS_API_TOKEN"] == (
        "optional",
        f"not set. Adds worldwide patents; request API access in your lens.org profile. {store}",
    )
    assert lines["EPO_OPS"] == (
        "optional",
        "not set. Adds European patents; register at developers.epo.org. "
        f"Needs both EPO_OPS_KEY and EPO_OPS_SECRET. {store}",
    )
    keys = [n for n in lines if n.isupper()]
    assert keys == ["OPENALEX_API_KEY", "S2_API_KEY", "LENS_API_TOKEN", "EPO_OPS"]


def test_epo_needs_both_halves(tmp_path):
    values = {"IDEAS_REPO": str(tmp_path), "REPOS_ROOT": str(tmp_path)}
    assert names(d.checks(values, environ={"EPO_OPS_KEY": "k"}))["EPO_OPS"] == "optional"


def test_every_group_gets_a_line_needing_all_members(tmp_path, monkeypatch):
    real = d.pk.load_plugin(d.PLUGIN)
    extra = [
        real.keys[0]._replace(option=f"zz_{n}", env=f"ZZ_{n}", group=7, description="Adds zz.")
        for n in (1, 2, 3)
    ]
    monkeypatch.setattr(d.pk, "load_plugin", lambda root: real._replace(keys=[*real.keys, *extra]))
    values = {"IDEAS_REPO": str(tmp_path), "REPOS_ROOT": str(tmp_path)}
    lines = {c.name: c for c in d.checks(values, environ={"ZZ_1": "x", "ZZ_2": "x"})}
    assert lines["ZZ"].status == "optional"
    assert "Needs all of ZZ_1 and ZZ_2 and ZZ_3" in lines["ZZ"].detail
    assert "Needs both EPO_OPS_KEY and EPO_OPS_SECRET" in lines["EPO_OPS"].detail
    every = dict.fromkeys(["ZZ_1", "ZZ_2", "ZZ_3"], "x")
    assert {c.name: c.status for c in d.checks(values, environ=every)}["ZZ"] == "ok"


def test_ready_ideas_repo_and_keys(tmp_path):
    repo = tmp_path / "ideas"
    (repo / "ideas").mkdir(parents=True)
    (repo / "projects.toml").write_text("")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    keys = ("OPENALEX_API_KEY", "S2_API_KEY", "LENS_API_TOKEN", "EPO_OPS_KEY", "EPO_OPS_SECRET")
    values = {"IDEAS_REPO": str(repo), "REPOS_ROOT": str(tmp_path)}
    found = names(d.checks(values, environ=dict.fromkeys(keys, "x")))
    assert found["ideas_repo"] == "ok"
    assert found["LENS_API_TOKEN"] == "ok"
    assert found["EPO_OPS"] == "ok"


def test_unsubstituted_placeholder_reads_as_unset(tmp_path):
    values = {"IDEAS_REPO": "${user_config.ideas_repo}", "REPOS_ROOT": ""}
    found = names(d.checks(values, environ={}))
    assert found["ideas_repo"] == "missing" and found["repos_root"] == "missing"


def test_output_lines_follow_the_doctor_format(tmp_path):
    argv = [HOOK_PYTHON, str(DOCTOR), f"IDEAS_REPO={tmp_path}", f"REPOS_ROOT={tmp_path}"]
    done = subprocess.run(argv, capture_output=True, text=True)
    assert done.stdout.strip()
    assert all(DOCTOR_LINE.match(line) for line in done.stdout.splitlines()), done.stdout


def run_doctor(*args):
    return subprocess.run([HOOK_PYTHON, str(DOCTOR), *args], capture_output=True, text=True)


def test_exit_code_is_1_when_ideas_repo_missing_and_0_when_ready(tmp_path):
    missing = run_doctor(f"IDEAS_REPO={tmp_path / 'nope'}", f"REPOS_ROOT={tmp_path}")
    assert missing.returncode == 1, missing.stdout
    repo = tmp_path / "ideas"
    (repo / "ideas").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    ready = run_doctor(f"IDEAS_REPO={repo}", f"REPOS_ROOT={tmp_path}")
    assert ready.returncode == 0, ready.stdout
    assert ready.stdout.splitlines()[-1] == "result: ready"


def test_a_malformed_manifest_is_one_optional_line_not_a_traceback(tmp_path, monkeypatch):
    plugin = tmp_path / "plugin"
    (plugin / ".claude-plugin").mkdir(parents=True)
    manifest = {"name": "x", "userConfig": {"a_key": {"type": "string", "sensitive": True}}}
    manifest["metadata"] = {"keyGroups": [[["a_key"]]]}
    (plugin / ".claude-plugin" / "plugin.json").write_text(json.dumps(manifest))
    monkeypatch.setattr(d, "PLUGIN", plugin)
    values = {"IDEAS_REPO": str(tmp_path), "REPOS_ROOT": str(tmp_path)}
    lines = {c.name: (c.status, c.detail) for c in d.checks(values, environ={})}
    assert lines["search keys"] == ("optional", "plugin.json unreadable")
