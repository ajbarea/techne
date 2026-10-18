"""The shared plugin key module: manifest-derived keys, the session hook and the store command.

Each test builds a synthetic plugin root, so nothing here depends on one plugin's key list.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest
from conftest import HOOK_PYTHON, ROOT, _load, stub_dir

SHARED = ROOT / "plugins" / "techne" / "_shared" / "plugin_keys.py"
pk = _load("techne_plugin_keys", SHARED)
SECRET = "s3cr3t value 'with' \"quotes\" $HOME `x` \\ end"
S2 = "CLAUDE_PLUGIN_OPTION_S2_API_KEY"
MANIFEST = {
    "name": "synth",
    "userConfig": {
        "ideas_repo": {"type": "directory", "title": "Ideas", "description": "A folder."},
        "openalex_api_key": {
            "type": "string",
            "title": "OpenAlex API key",
            "description": "Raises OpenAlex's search budget; free at openalex.org/settings/api.",
            "required": False,
            "sensitive": True,
        },
        "s2_api_key": {
            "type": "string",
            "title": "Semantic Scholar API key",
            "description": "Adds Semantic Scholar; request one at semanticscholar.org/product/api.",
            "sensitive": True,
        },
        "extra_api_token": {
            "type": "string",
            "title": "Extra API token",
            "description": "Adds an extra source; request one at example.org/api.",
            "sensitive": True,
        },
        "epo_ops_key": {
            "type": "string",
            "title": "EPO OPS key",
            "description": "Adds European patents; register at developers.epo.org.",
            "sensitive": True,
        },
        "epo_ops_secret": {
            "type": "string",
            "title": "EPO OPS secret",
            "description": "Adds European patents; register at developers.epo.org.",
            "sensitive": True,
        },
        "plain_text": {"type": "string", "title": "Plain", "description": "Not secret."},
        "secret_number": {"type": "number", "sensitive": True, "title": "N", "description": "n"},
    },
    "metadata": {"keyGroups": [["epo_ops_key", "epo_ops_secret"]]},
}
ENVS = [
    "OPENALEX_API_KEY",
    "S2_API_KEY",
    "EXTRA_API_TOKEN",
    "EPO_OPS_KEY",
    "EPO_OPS_SECRET",
]
OPTION_VARS = [f"CLAUDE_PLUGIN_OPTION_{e}" for e in ENVS]
OWN = f"sess-1.{os.getpid()}.sh"  # the hook's parent is this pytest process


def make_root(base, manifest=MANIFEST, name="plug"):
    """A plugin root holding a copy of the shared module, as every plugin ships one."""
    root = base / name
    (root / ".claude-plugin").mkdir(parents=True)
    (root / "_shared").mkdir()
    if manifest is not None:
        (root / ".claude-plugin" / "plugin.json").write_text(json.dumps(manifest))
    shutil.copy(SHARED, root / "_shared" / "plugin_keys.py")
    return root


@pytest.fixture
def root(tmp_path):
    return make_root(tmp_path)


@pytest.fixture
def keys(root):
    return pk.load_keys(root)


def script(root):
    return str(root / "_shared" / "plugin_keys.py")


def dead_pid():
    """A pid that is not running: a child that has exited and been reaped."""
    child = subprocess.Popen([HOOK_PYTHON, "-c", "pass"])
    child.wait()
    return child.pid


def run_hook(tmp_path, env, mode="start", sid="sess-1", stdin=None, with_file=True, with_data=True):
    target = tmp_path / "env.sh"
    data = tmp_path / "data"
    base = {"PATH": os.environ["PATH"], **env}
    if with_file:
        base["CLAUDE_ENV_FILE"] = str(target)
    if with_data:
        base["CLAUDE_PLUGIN_DATA"] = str(data)
    payload = json.dumps({"session_id": sid}) if stdin is None else stdin
    root = tmp_path / "plug"
    if not root.exists():
        make_root(tmp_path)
    done = subprocess.run(
        [HOOK_PYTHON, script(root), mode], env=base, input=payload, capture_output=True, text=True
    )
    return done, target, data / "session-keys"


def sourced(target, name, env=None):
    cmd = f'. "{target}"; printf %s "${name}"'
    return subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, env=env or {}).stdout


def tree(root):
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*")) if root.exists() else []


# the manifest is the key table


def test_load_keys_reads_sensitive_string_options_in_manifest_order(keys):
    assert [k.env for k in keys] == ENVS
    assert [k.option for k in keys] == [e.lower() for e in ENVS]
    assert keys[1].title == "Semantic Scholar API key"
    assert keys[0].description.startswith("Raises OpenAlex's search budget")


def test_load_keys_skips_non_secret_and_non_string_options(keys):
    options = {k.option for k in keys}
    assert not options & {"ideas_repo", "plain_text", "secret_number"}


@pytest.mark.parametrize("option", ["bad-name", "1st", "has space", ""])
def test_a_sensitive_option_with_an_unusable_name_raises(tmp_path, option):
    manifest = {"name": "x", "userConfig": {option: {"type": "string", "sensitive": True}}}
    with pytest.raises(ValueError, match="not a valid key name"):
        pk.load_plugin(make_root(tmp_path, manifest))


def test_key_groups_come_from_metadata(keys):
    assert {k.env: k.group for k in keys} == {
        "OPENALEX_API_KEY": -1,
        "S2_API_KEY": -1,
        "EXTRA_API_TOKEN": -1,
        "EPO_OPS_KEY": 0,
        "EPO_OPS_SECRET": 0,
    }
    assert pk.group_ids(keys) == [0]
    assert pk.group_labels(keys) == {0: "EPO_OPS"}


def test_group_without_a_shared_prefix_joins_the_names(tmp_path):
    manifest = json.loads(json.dumps(MANIFEST))
    manifest["metadata"] = {"keyGroups": [["s2_api_key", "extra_api_token"]]}
    loaded = pk.load_keys(make_root(tmp_path, manifest))
    found = {k.env: k.group for k in loaded}
    assert found["S2_API_KEY"] == found["EXTRA_API_TOKEN"] == 0
    assert pk.group_labels(loaded) == {0: "S2_API_KEY+EXTRA_API_TOKEN"}


AWS = {
    "name": "aws",
    "userConfig": {
        name: {"type": "string", "title": name, "description": f"{name}.", "sensitive": True}
        for name in ("aws_id", "aws_secret", "aws_token", "aws_region_key")
    },
    "metadata": {"keyGroups": [["aws_id", "aws_secret"], ["aws_token", "aws_region_key"]]},
}


def test_groups_with_the_same_prefix_stay_separate_groups(tmp_path):
    plugin = pk.load_plugin(make_root(tmp_path, AWS))
    assert {k.env: k.group for k in plugin.keys} == {
        "AWS_ID": 0,
        "AWS_SECRET": 0,
        "AWS_TOKEN": 1,
        "AWS_REGION_KEY": 1,
    }
    assert pk.group_labels(plugin.keys) == {0: "AWS_ID+AWS_SECRET", 1: "AWS_TOKEN+AWS_REGION_KEY"}
    lines = pk.doctor_entries(plugin, {"AWS_ID": "a", "AWS_TOKEN": "t", "AWS_REGION_KEY": "r"})
    assert [(n, p) for n, p, _ in lines] == [
        ("AWS_ID+AWS_SECRET", False),
        ("AWS_TOKEN+AWS_REGION_KEY", True),
    ]
    assert pk.half_groups(plugin.keys, {"AWS_ID": "a", "AWS_TOKEN": "t"}) == {
        0: (["AWS_ID"], ["AWS_SECRET"]),
        1: (["AWS_TOKEN"], ["AWS_REGION_KEY"]),
    }
    assert "Save it together with AWS_SECRET." in pk.template(plugin.keys)


def test_a_label_equal_to_a_key_name_falls_back_to_the_joined_names():
    keys = [
        pk.Key("a", "A_B", "t", "d", 0),
        pk.Key("a_b_c", "A_B_C", "t", "d", 0),
        pk.Key("a_b_d", "A_B_D", "t", "d", 0),
    ]
    assert pk.group_labels(keys) == {0: "A_B+A_B_C+A_B_D"}


@pytest.mark.parametrize("meta", [None, {}, {"keyGroups": []}, "x"])
def test_missing_key_groups_mean_no_groups(tmp_path, meta):
    manifest = dict(MANIFEST, metadata=meta)
    assert {k.group for k in pk.load_keys(make_root(tmp_path, manifest))} == {-1}


@pytest.mark.parametrize(
    "groups",
    [
        "x",
        [5],
        [["nope", "s2_api_key"]],
        [[["a_key"]]],
        [["s2_api_key"]],
        [[]],
        ["s2_api_key"],
        [["s2_api_key", 5]],
        [["plain_text", "s2_api_key"]],
        [["s2_api_key", "extra_api_token"], ["s2_api_key", "openalex_api_key"]],
        [["s2_api_key", "s2_api_key"]],
    ],
)
def test_a_malformed_key_group_raises(tmp_path, groups):
    manifest = dict(MANIFEST, metadata={"keyGroups": groups})
    with pytest.raises(ValueError):
        pk.load_plugin(make_root(tmp_path, manifest))


@pytest.mark.parametrize("manifest", [None, [], {"userConfig": []}, {"name": "x"}])
def test_missing_or_odd_manifest_gives_no_keys(tmp_path, manifest):
    root = make_root(tmp_path, manifest)
    if manifest == []:
        (root / ".claude-plugin" / "plugin.json").write_text("[]")
    assert pk.load_keys(root) == []


def test_unparsable_manifest_gives_no_keys(tmp_path):
    root = make_root(tmp_path, None)
    (root / ".claude-plugin" / "plugin.json").write_text("{not json")
    assert pk.load_plugin(root) == ("plug", [])


def test_plugin_name_and_hint_come_from_the_manifest(root):
    plugin = pk.load_plugin(root)
    assert plugin.name == "synth" and plugin.keys == pk.load_keys(root)
    assert pk.configure_hint(plugin.name) == "/plugin configure synth@techne"


def test_sentence_has_a_capital_and_a_final_period(keys):
    assert keys[0].sentence == "Raises OpenAlex's search budget; free at openalex.org/settings/api."
    assert pk.Key("x_key", "X_KEY", "t", "adds this").sentence == "Adds this."
    assert pk.Key("x_key", "X_KEY", "Title", "").sentence == "Title."
    assert pk.Key("x_key", "X_KEY", "t", "Is it?").sentence == "Is it?"


def test_a_missing_description_falls_back_to_the_title(tmp_path):
    manifest = {
        "name": "bare",
        "userConfig": {
            "a_key": {"type": "string", "title": "A key", "sensitive": True},
            "b_key": {"type": "string", "title": "B key", "description": "  ", "sensitive": True},
            "c_key": {"type": "string", "sensitive": True},
            "d_key": {"type": "string", "description": "Line one\n# line two.", "sensitive": True},
        },
    }
    plugin = pk.load_plugin(make_root(tmp_path, manifest))
    assert [k.description for k in plugin.keys] == [
        "A key",
        "B key",
        "c_key",
        "Line one # line two.",
    ]
    out = pk.template(plugin.keys)
    assert out.startswith("# A key\nA_KEY=\n") and "# c_key\nC_KEY=\n" in out
    assert "# Line one # line two.\nD_KEY=\n" in out
    detail = {n: d for n, _, d in pk.doctor_entries(plugin, {})}
    assert detail["A_KEY"].startswith("not set. A key. Store it with")


def test_doctor_entries_one_line_per_key_and_group(keys):
    plugin = pk.Plugin("synth", keys)
    lines = {n: (p, d) for n, p, d in pk.doctor_entries(plugin, {"S2_API_KEY": "x"})}
    assert list(lines) == ["OPENALEX_API_KEY", "S2_API_KEY", "EXTRA_API_TOKEN", "EPO_OPS"]
    assert lines["S2_API_KEY"] == (True, "set")
    assert lines["OPENALEX_API_KEY"] == (
        False,
        "not set. Raises OpenAlex's search budget; free at openalex.org/settings/api. "
        "Store it with /plugin configure synth@techne, then restart.",
    )
    assert lines["EPO_OPS"][1] == (
        "not set. Adds European patents; register at developers.epo.org. "
        "Needs both EPO_OPS_KEY and EPO_OPS_SECRET. "
        "Store it with /plugin configure synth@techne, then restart."
    )


def test_doctor_group_needs_every_member(keys):
    def present(env):
        return {n: p for n, p, _ in pk.doctor_entries(pk.Plugin("h", keys), env)}["EPO_OPS"]

    assert not present({"EPO_OPS_KEY": "k"}) and not present({"EPO_OPS_SECRET": "s"})
    assert present({"EPO_OPS_KEY": "k", "EPO_OPS_SECRET": "s"})


def test_doctor_group_of_three_says_all_of(tmp_path):
    manifest = json.loads(json.dumps(MANIFEST))
    manifest["metadata"] = {"keyGroups": [["s2_api_key", "extra_api_token", "openalex_api_key"]]}
    three = pk.load_plugin(make_root(tmp_path, manifest))
    detail = pk.doctor_entries(three, {})[-1][2]
    assert "Needs all of OPENALEX_API_KEY and S2_API_KEY and EXTRA_API_TOKEN." in detail


def hook_command(event, mode):
    guard = (
        '[ -d "${CLAUDE_PLUGIN_DATA}/session-keys" ] && '
        if mode == "end"
        else '[ -n "${CLAUDE_PLUGIN_ROOT}" ] && '
    )
    return (
        f'{guard}command -v python3 >/dev/null 2>&1 && exec python3 "${{CLAUDE_PLUGIN_ROOT}}'
        f'/_shared/plugin_keys.py" {mode}; exit 0'
    )


@pytest.mark.parametrize("event,mode", [("SessionStart", "start"), ("SessionEnd", "end")])
def test_hook_commands_run_the_script_and_exit_0_without_python3(tmp_path, root, event, mode):
    command = hook_command(event, mode)
    marker = tmp_path / "ran"
    bindir = stub_dir(tmp_path, {"python3": f'echo "$@" > {marker}'}, links=["sh"])
    (tmp_path / "data" / "session-keys").mkdir(parents=True)
    data = str(tmp_path / "data")
    env = {"PATH": bindir, "CLAUDE_PLUGIN_ROOT": str(root), "CLAUDE_PLUGIN_DATA": data}
    done = subprocess.run(["sh", "-c", command], env=env, capture_output=True, text=True)
    assert done.returncode == 0 and marker.read_text().split()[-1] == mode
    assert marker.read_text().split()[0] == f"{root}/_shared/plugin_keys.py"
    bare = stub_dir(tmp_path, {}, links=["sh"])
    done = subprocess.run(
        ["sh", "-c", command],
        env={"PATH": bare, "CLAUDE_PLUGIN_ROOT": str(root), "CLAUDE_PLUGIN_DATA": data},
    )
    assert done.returncode == 0


def test_the_start_command_exits_0_when_the_host_sets_no_plugin_root(tmp_path):
    """A CLI that converts Claude hooks may leave CLAUDE_PLUGIN_ROOT unset."""
    marker = tmp_path / "ran"
    bindir = stub_dir(tmp_path, {"python3": f"echo ran > {marker}"}, links=["sh"])
    done = subprocess.run(["sh", "-c", hook_command("SessionStart", "start")], env={"PATH": bindir})
    assert done.returncode == 0 and not marker.exists()


def test_the_end_command_does_not_start_python_without_a_key_folder(tmp_path, root):
    marker = tmp_path / "ran"
    bindir = stub_dir(tmp_path, {"python3": f"echo ran > {marker}"}, links=["sh"])
    env = {
        "PATH": bindir,
        "CLAUDE_PLUGIN_ROOT": str(root),
        "CLAUDE_PLUGIN_DATA": str(tmp_path / "d"),
    }
    done = subprocess.run(["sh", "-c", hook_command("SessionEnd", "end")], env=env)
    assert done.returncode == 0 and not marker.exists()


# the hook


@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions")
def test_session_file_is_0600_in_a_0700_dir(tmp_path):
    (tmp_path / "data" / "session-keys").mkdir(parents=True, mode=0o755)
    done, _, directory = run_hook(tmp_path, {S2: SECRET})
    assert done.returncode == 0
    assert directory.stat().st_mode & 0o777 == 0o700
    assert (directory / OWN).stat().st_mode & 0o777 == 0o600
    assert tree(directory) == [OWN]  # no temp file left


def test_env_file_holds_only_a_source_line_never_a_value(tmp_path):
    env = {var: f"value-{i}-{SECRET}" for i, var in enumerate(OPTION_VARS)}
    done, target, directory = run_hook(tmp_path, env)
    text = target.read_text()
    path = str(directory / OWN)
    assert text == f"if [ -f {path} ]; then . {path}; fi\n"
    assert "value-" not in text and SECRET not in text
    assert "value-" not in done.stdout + done.stderr and not (done.stdout + done.stderr)


def test_sourcing_the_env_file_yields_every_value(tmp_path):
    env = {var: f"v{i} {SECRET}" for i, var in enumerate(OPTION_VARS)}
    _, target, _ = run_hook(tmp_path, env)
    for i, env in enumerate(ENVS):
        assert sourced(target, env) == f"v{i} {SECRET}"


def test_a_variable_already_in_the_bash_env_wins(tmp_path):
    opts = {S2: "saved", "CLAUDE_PLUGIN_OPTION_EXTRA_API_TOKEN": "extra"}
    _, target, _ = run_hook(tmp_path, opts)
    assert sourced(target, "S2_API_KEY", {"S2_API_KEY": "shell"}) == "shell"
    assert sourced(target, "EXTRA_API_TOKEN", {"S2_API_KEY": "shell"}) == "extra"
    assert sourced(target, "S2_API_KEY", {"S2_API_KEY": ""}) == "saved"


def test_hook_appends_to_an_existing_env_file(tmp_path):
    (tmp_path / "env.sh").write_text("export OTHER=1\n")
    _, target, _ = run_hook(tmp_path, {S2: "x"})
    assert target.read_text().startswith("export OTHER=1\nif [ -f ")


def test_end_deletes_only_its_own_process_file_and_missing_is_fine(tmp_path):
    _, _, directory = run_hook(tmp_path, {S2: "x"})
    other = directory / f"sess-1.{os.getpid() + 1}.sh"
    other.write_text("x")
    assert (directory / OWN).exists()
    done, _, _ = run_hook(tmp_path, {}, mode="end")
    assert done.returncode == 0 and not (directory / OWN).exists()
    assert other.exists()  # the same conversation in a second process
    done, _, _ = run_hook(tmp_path, {}, mode="end")
    assert done.returncode == 0 and other.exists()


def test_file_name_carries_the_hook_parent_pid(tmp_path):
    _, _, directory = run_hook(tmp_path, {S2: "x"})
    assert tree(directory) == [OWN]


@pytest.mark.skipif(os.name != "posix", reason="pid probe")
def test_prune_removes_a_dead_pid_file_and_keeps_a_live_one(tmp_path):
    directory = tmp_path / "data" / "session-keys"
    directory.mkdir(parents=True)
    dead = directory / f"gone.{dead_pid()}.sh"
    live = directory / f"idle.{os.getpid()}.sh"
    dead.write_text("x")
    live.write_text("x")
    age = time.time() - pk.MAX_AGE_SECONDS - 60
    os.utime(live, (age, age))  # idling past the age limit does not matter on POSIX
    run_hook(tmp_path, {S2: "x"})
    assert not dead.exists() and live.exists() and (directory / OWN).exists()


def test_unparsable_names_are_pruned_by_age_only(tmp_path):
    directory = tmp_path / "data" / "session-keys"
    directory.mkdir(parents=True)
    old, fresh = directory / "old.sh", directory / "fresh.sh"
    old.write_text("x")
    fresh.write_text("x")
    age = time.time() - pk.MAX_AGE_SECONDS - 60
    os.utime(old, (age, age))
    run_hook(tmp_path, {S2: "x"})
    assert not old.exists() and fresh.exists()


def test_windows_never_probes_a_pid_with_os_kill(tmp_path, monkeypatch):
    stale_old = tmp_path / "a.4242.sh"
    recent = tmp_path / "b.4243.sh"
    stale_old.write_text("x")
    recent.write_text("x")
    age = time.time() - pk.MAX_AGE_SECONDS - 60
    os.utime(stale_old, (age, age))

    def boom(*_):
        raise AssertionError("os.kill called")

    monkeypatch.setattr(pk.os, "name", "nt")
    monkeypatch.setattr(pk.os, "kill", boom)
    pk.prune(str(tmp_path), time.time())
    assert not stale_old.exists() and recent.exists()


def test_pid_alive_cases():
    assert pk.pid_alive(os.getpid())
    assert not pk.pid_alive(0) and not pk.pid_alive(-1) and not pk.pid_alive(10**12)


def test_temp_name_symlink_is_not_followed(tmp_path, monkeypatch):
    victim = tmp_path / "victim"
    victim.write_text("keep")
    target = str(tmp_path / "f.sh")
    monkeypatch.setattr(pk.secrets, "token_hex", lambda n: "fixed")
    try:
        os.symlink(victim, f"{target}.fixed.tmp")
    except (OSError, NotImplementedError):
        pytest.skip("no symlinks")
    with pytest.raises(OSError):
        pk.write_private(target, "export S2_API_KEY=topsecret\n")
    assert victim.read_text() == "keep" and not os.path.exists(target)


def test_second_start_does_not_duplicate_the_env_line(tmp_path):
    _, target, _ = run_hook(tmp_path, {S2: "x"})
    once = target.read_text()
    done, _, _ = run_hook(tmp_path, {S2: "x"})
    assert done.returncode == 0 and target.read_text() == once


@pytest.mark.parametrize("sid", ["../x", "a/b", "", "a b", "x\n", "a" * 200, "..", "a.sh"])
def test_unsafe_session_id_writes_nothing(tmp_path, sid):
    done, _, _ = run_hook(tmp_path, {S2: "x"}, sid=sid)
    assert done.returncode == 0
    assert tree(tmp_path / "data") == []


def test_no_options_writes_nothing_and_removes_a_stale_session_file(tmp_path):
    _, target, directory = run_hook(tmp_path, {S2: "x"})
    target.unlink()
    done, target, _ = run_hook(tmp_path, {S2: ""})
    assert done.returncode == 0 and not target.exists()
    assert not (directory / OWN).exists()


@pytest.mark.parametrize("value", ["a\nb", "a\rb"])
def test_hook_skips_a_multiline_value(tmp_path, value):
    _, target, directory = run_hook(tmp_path, {S2: value})
    assert not target.exists() and not (directory / OWN).exists()


def test_hook_skips_a_nul_value(tmp_path):
    # a NUL cannot cross the process environment, so this checks the function
    assert pk.export_lines(pk.load_keys(make_root(tmp_path)), {S2: "a\0b"}) == []


def test_hook_without_env_file_writes_nothing(tmp_path):
    done, _, directory = run_hook(tmp_path, {S2: "x"}, with_file=False)
    assert done.returncode == 0 and not (directory / OWN).exists()


@pytest.mark.parametrize("stdin", ["", "not json", "[]", "{}", '{"session_id": 5}'])
def test_malformed_stdin_exits_0_and_writes_nothing(tmp_path, stdin):
    done, _, _ = run_hook(tmp_path, {S2: SECRET}, stdin=stdin)
    assert done.returncode == 0 and tree(tmp_path / "data") == []
    assert SECRET not in done.stdout + done.stderr


def test_missing_plugin_data_exits_0_and_writes_nothing(tmp_path):
    done, _, _ = run_hook(tmp_path, {S2: SECRET}, with_data=False)
    assert done.returncode == 0 and tree(tmp_path / "data") == []


def test_hook_exits_0_when_the_env_file_is_unwritable(tmp_path):
    env = {S2: SECRET, "CLAUDE_ENV_FILE": str(tmp_path / "no" / "f")}
    done, _, _ = run_hook(tmp_path, env, with_file=False)
    assert done.returncode == 0 and SECRET not in done.stdout + done.stderr


def test_start_with_no_value_set_creates_nothing_and_end_without_a_folder_is_a_no_op(tmp_path):
    done, target, _ = run_hook(tmp_path, {})
    assert done.returncode == 0 and tree(tmp_path / "data") == [] and not target.exists()
    done, _, _ = run_hook(tmp_path, {}, mode="end")
    assert done.returncode == 0 and tree(tmp_path / "data") == []


def test_start_with_no_value_set_still_cleans_an_existing_folder(tmp_path):
    directory = tmp_path / "data" / "session-keys"
    directory.mkdir(parents=True)
    dead = directory / f"gone.{dead_pid()}.sh"
    dead.write_text("x")
    run_hook(tmp_path, {})
    assert not dead.exists()


BROKEN = dict(MANIFEST, metadata={"keyGroups": [[["a_key"]]]})


@pytest.mark.parametrize("mode", ["start", "end"])
def test_a_hook_exits_0_silently_on_a_malformed_manifest(tmp_path, mode):
    make_root(tmp_path, BROKEN)
    (tmp_path / "data" / "session-keys").mkdir(parents=True)
    done, target, _ = run_hook(tmp_path, {S2: SECRET}, mode=mode)
    assert done.returncode == 0 and not (done.stdout + done.stderr)
    assert not target.exists()


def test_run_hook_swallows_any_exception(tmp_path, monkeypatch):
    def boom(*_):
        raise RuntimeError("boom")

    monkeypatch.setattr(pk, "load_keys", boom)
    env = {"CLAUDE_PLUGIN_DATA": str(tmp_path)}
    assert pk.run_hook("start", json.dumps({"session_id": "s"}), env, tmp_path) == 0


# the store command


def test_template_lists_every_name_with_its_comment(root, keys):
    out = subprocess.run([HOOK_PYTHON, script(root), "template"], capture_output=True, text=True)
    assert out.returncode == 0
    lines = out.stdout.splitlines()
    for key in keys:
        assert f"{key.env}=" in lines
        assert f"# {key.description}" in lines
    assert pk.parse(out.stdout, keys) == {}


def test_template_grouped_keys_name_their_partner(keys):
    lines = pk.template(keys).splitlines()
    assert "# Save it together with EPO_OPS_SECRET." in lines
    assert "# Save it together with EPO_OPS_KEY." in lines
    assert "# Adds European patents; register at developers.epo.org." in lines


def test_parse_handles_comments_export_quotes_and_empties(keys):
    text = (
        "# note\n\nS2_API_KEY=abc  \nexport EXTRA_API_TOKEN='q u'\n"
        'OPENALEX_API_KEY="d"\nEPO_OPS_KEY=\nEPO_OPS_SECRET= \n'
    )
    assert pk.parse(text, keys) == {
        "S2_API_KEY": "abc",
        "EXTRA_API_TOKEN": "q u",
        "OPENALEX_API_KEY": "d",
    }


def test_parse_keeps_equals_signs_and_hash_without_space(keys):
    assert pk.parse("S2_API_KEY=a=b==\nEXTRA_API_TOKEN=ab#cd\n", keys) == {
        "S2_API_KEY": "a=b==",
        "EXTRA_API_TOKEN": "ab#cd",
    }


def test_parse_cuts_inline_comments(keys):
    text = (
        "S2_API_KEY=abc # note\nEXTRA_API_TOKEN=def\t# tab\n"
        'OPENALEX_API_KEY=\'q # kept\'  # note\nEPO_OPS_KEY="e"#x"\n'
    )
    with pytest.raises(pk.StoreError):  # text after the closing quote
        pk.parse(text, keys)
    ok = pk.parse(text.replace('#x"', ""), keys)
    assert ok == {
        "S2_API_KEY": "abc",
        "EXTRA_API_TOKEN": "def",
        "OPENALEX_API_KEY": "q # kept",
        "EPO_OPS_KEY": "e",
    }
    assert pk.parse("S2_API_KEY= # only a comment\n", keys) == {}


def test_parse_unterminated_quote_names_line_and_name_not_value(keys):
    with pytest.raises(pk.StoreError) as err:
        pk.parse("S2_API_KEY=ok\nEXTRA_API_TOKEN='hunter2hunter2\n", keys)
    assert "line 2" in str(err.value) and "EXTRA_API_TOKEN" in str(err.value)
    assert "hunter2" not in str(err.value)


def test_store_reads_a_file_with_a_bom(tmp_path):
    done, rec = run_store(tmp_path, CLAUDE_OK, content="\ufeffS2_API_KEY=topsecret\n")
    assert done.returncode == 0, done.stderr
    assert json.loads((rec / "stdin").read_text()) == {"s2_api_key": "topsecret"}


def test_unknown_name_error_names_line_and_name_not_value(keys):
    with pytest.raises(pk.StoreError) as err:
        pk.parse("S2_API_KEY=ok\nGITHUB_TOKEN=hunter2hunter2\n", keys)
    assert "line 2" in str(err.value) and "GITHUB_TOKEN" in str(err.value)
    assert "hunter2" not in str(err.value)
    with pytest.raises(pk.StoreError) as err:
        pk.parse("hunter2hunter2\n", keys)
    assert "hunter2" not in str(err.value)


CLAUDE_OK = """\
if [ "$1 $2" = "plugin list" ]; then
  echo '[{"id":"graphe@techne","scope":"user"},{"id":"synth@techne","scope":"user"}]'
  exit 0
fi
printf '%s\\n' "$@" > "$REC/argv"
cat > "$REC/stdin"
echo "Configuration saved. Restart Claude Code to apply it."
"""


def run_store(tmp_path, body, *args, content="S2_API_KEY=topsecret\nEPO_OPS_KEY=k2\n", mode=0o600):
    rec = tmp_path / "rec"
    rec.mkdir(exist_ok=True)
    keys = tmp_path / "keys.env"
    keys.write_text(content, encoding="utf-8")
    keys.chmod(mode)
    path = stub_dir(tmp_path, {"claude": body} if body else {}, links=["cat", "printf"])
    root = tmp_path / "plug"
    if not root.exists():
        make_root(tmp_path)
    done = subprocess.run(
        [HOOK_PYTHON, script(root), "store", str(keys), *args],
        env={"PATH": path, "REC": str(rec)},
        capture_output=True,
        text=True,
    )
    return done, rec


def test_store_sends_json_on_stdin_never_argv(tmp_path):
    done, rec = run_store(tmp_path, CLAUDE_OK)
    assert done.returncode == 0, done.stderr
    assert json.loads((rec / "stdin").read_text()) == {
        "s2_api_key": "topsecret",
        "epo_ops_key": "k2",
    }
    argv = (rec / "argv").read_text().split()
    assert argv == ["plugin", "configure", "synth@techne", "--values-stdin"]
    assert "topsecret" not in (rec / "argv").read_text()
    assert "S2_API_KEY" in done.stdout and "EPO_OPS_KEY" in done.stdout
    assert "topsecret" not in done.stdout + done.stderr
    assert "Restart Claude Code" in done.stdout


def test_store_uses_the_given_plugin_id_without_listing(tmp_path):
    body = 'if [ "$1" = list ] || [ "$2" = list ]; then exit 9; fi\n' + CLAUDE_OK
    done, rec = run_store(tmp_path, body, "--plugin", "synth@mine")
    assert done.returncode == 0, done.stderr
    assert "synth@mine" in (rec / "argv").read_text()


def test_store_refuses_several_synth_ids(tmp_path):
    body = """echo '[{"id":"synth@a"},{"id":"synth@b"}]'"""
    done, _ = run_store(tmp_path, body)
    assert done.returncode == 2
    assert "synth@a" in done.stderr and "synth@b" in done.stderr
    assert "topsecret" not in done.stdout + done.stderr


def test_store_prefers_the_enabled_install(tmp_path):
    body = (
        'if [ "$2" = list ]; then echo \'[{"id":"synth@old","enabled":false},'
        '{"id":"synth@techne","enabled":true}]\'; exit 0; fi\n' + CLAUDE_OK
    )
    done, rec = run_store(tmp_path, body)
    assert done.returncode == 0, done.stderr
    assert "synth@techne" in (rec / "argv").read_text()


def test_pick_plugin_id_cases():
    def pick(listing, wanted, root=Path("/nowhere")):
        return pk.find_plugin_id(listing, wanted, "synth", root)

    one_disabled = json.dumps([{"id": "synth@a", "enabled": False}])
    assert pick(one_disabled, None) == "synth@a"
    assert pick(json.dumps([{"id": "synth@a"}, {"id": "x@y"}]), None) == "synth@a"
    both_off = json.dumps(
        [{"id": "synth@a", "enabled": False}, {"id": "synth@b", "enabled": False}]
    )
    for listing in (both_off, json.dumps([{"id": "synth@a"}, {"id": "synth@b"}])):
        with pytest.raises(pk.StoreError, match="synth@a, synth@b"):
            pick(listing, None)


def test_the_entry_installed_at_this_plugin_root_wins(tmp_path):
    here = tmp_path / "cache" / "synth" / "abc"
    here.mkdir(parents=True)
    link = tmp_path / "link"
    link.symlink_to(here)
    listing = json.dumps(
        [
            {"id": "synth@techne", "enabled": True, "installPath": str(link)},
            {"id": "synth@other", "enabled": True, "installPath": str(tmp_path / "elsewhere")},
            {"id": "synth@third", "enabled": True, "installPath": str(tmp_path / "x")},
            {"id": "synth@synced", "enabled": True, "installPath": ""},
        ]
    )
    assert pk.find_plugin_id(listing, None, "synth", here) == "synth@techne"
    assert pk.find_plugin_id(listing, "synth@mine", "synth", here) == "synth@mine"


def test_a_synced_entry_without_an_install_path_is_ignored(tmp_path):
    listing = json.dumps(
        [
            {"id": "synth@techne", "enabled": True, "installPath": str(tmp_path / "a")},
            {"id": "synth@synced", "enabled": True, "installPath": ""},
        ]
    )
    assert pk.find_plugin_id(listing, None, "synth", tmp_path / "b") == "synth@techne"
    two = json.dumps(
        [
            {"id": "synth@a", "enabled": True, "installPath": str(tmp_path / "a")},
            {"id": "synth@b", "enabled": True, "installPath": str(tmp_path / "c")},
        ]
    )
    with pytest.raises(pk.StoreError, match="synth@a, synth@b"):
        pk.find_plugin_id(two, None, "synth", tmp_path / "b")
    only_synced = json.dumps([{"id": "synth@synced", "installPath": ""}])
    with pytest.raises(pk.StoreError, match="not installed"):
        pk.find_plugin_id(only_synced, None, "synth", tmp_path / "b")


def test_redact_hides_raw_and_json_escaped_values():
    value = 'a"b\\c'
    text = f"raw {value} escaped {json.dumps(value)[1:-1]}"
    assert value not in pk.redact(text, [value]) and 'a\\"b' not in pk.redact(text, [value])


def test_store_names_the_missing_install(tmp_path):
    done, _ = run_store(tmp_path, "echo '[]'")
    assert done.returncode == 2 and "not installed" in done.stderr


def test_store_failure_redacts_values(tmp_path):
    body = (
        'if [ "$2" = list ]; then echo \'[{"id":"synth@techne"}]\'; exit 0; fi\n'
        'v=$(cat); echo "bad input: $v and topsecret and k2" >&2; exit 7'
    )
    done, _ = run_store(tmp_path, body)
    assert done.returncode == 2
    assert "exited 7" in done.stderr and "***" in done.stderr
    assert "topsecret" not in done.stdout + done.stderr
    assert "k2" not in (done.stdout + done.stderr).replace("EPO_OPS_K", "")


def test_store_unknown_name_exits_2_without_calling_claude(tmp_path):
    done, rec = run_store(tmp_path, CLAUDE_OK, content="S2_API_KEY=ok\nNOPE=hunter2hunter2\n")
    assert done.returncode == 2
    assert "line 2" in done.stderr and "NOPE" in done.stderr and "hunter2" not in done.stderr
    assert not (rec / "stdin").exists()


def test_store_with_no_values_exits_1(tmp_path):
    done, rec = run_store(tmp_path, CLAUDE_OK, content="# only\nS2_API_KEY=\n")
    assert done.returncode == 1 and "nothing stored" in done.stdout
    assert not (rec / "stdin").exists()


def test_store_without_claude_on_path_is_a_clear_error(tmp_path):
    done, _ = run_store(tmp_path, None)
    assert done.returncode == 2 and "`claude` is not on PATH" in done.stderr
    assert "topsecret" not in done.stdout + done.stderr


@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions")
def test_store_warns_about_a_group_readable_file(tmp_path):
    done, _ = run_store(tmp_path, CLAUDE_OK, mode=0o644)
    assert done.returncode == 0 and "can be read or changed by others" in done.stderr
    assert "topsecret" not in done.stdout + done.stderr
    quiet, _ = run_store(tmp_path, CLAUDE_OK, mode=0o600)
    assert "by others" not in quiet.stderr


@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions")
def test_store_does_not_warn_about_an_executable_private_file(tmp_path):
    done, _ = run_store(tmp_path, CLAUDE_OK, mode=0o700)
    assert "by others" not in done.stderr
    warned, _ = run_store(tmp_path, CLAUDE_OK, mode=0o620)
    assert "by others" in warned.stderr


def test_store_half_pair_warns_by_name_and_still_stores(tmp_path):
    done, rec = run_store(tmp_path, CLAUDE_OK)  # EPO_OPS_KEY without EPO_OPS_SECRET
    assert done.returncode == 0, done.stderr
    assert "EPO_OPS_KEY given without EPO_OPS_SECRET" in done.stderr
    assert "EPO_OPS stays skipped until EPO_OPS_SECRET is saved too." in done.stdout
    sent = json.loads((rec / "stdin").read_text())
    assert sent == {"s2_api_key": "topsecret", "epo_ops_key": "k2"}
    assert "k2" not in (done.stdout + done.stderr).replace("EPO_OPS_K", "")
    full, _ = run_store(tmp_path, CLAUDE_OK, content="EPO_OPS_KEY=k2\nEPO_OPS_SECRET=s2\n")
    assert "given without" not in full.stderr and "stays skipped" not in full.stdout


def test_half_groups_derive_from_the_table(keys):
    assert pk.half_groups(keys, {"S2_API_KEY": "x"}) == {}
    assert pk.half_groups(keys, {"EPO_OPS_SECRET": "x"}) == {
        0: (["EPO_OPS_SECRET"], ["EPO_OPS_KEY"])
    }


def test_store_exit_codes_per_path(tmp_path):
    root = make_root(tmp_path / "x")
    ok, _ = run_store(tmp_path, CLAUDE_OK)
    assert ok.returncode == 0
    empty, _ = run_store(tmp_path, CLAUDE_OK, content="\n")
    assert empty.returncode == 1
    bad, _ = run_store(tmp_path, CLAUDE_OK, content="garbage\n")
    assert bad.returncode == 2
    absent = tmp_path / "absent.env"
    nofile = subprocess.run(
        [HOOK_PYTHON, script(root), "store", str(absent)], capture_output=True, text=True
    )
    assert nofile.returncode == 2
    usage = subprocess.run([HOOK_PYTHON, script(root), "store"], capture_output=True, text=True)
    assert usage.returncode == 2
    noclaude, _ = run_store(tmp_path, None)
    assert noclaude.returncode == 2
    listing = 'if [ "$2" = list ]; then echo \'[{"id":"synth@t"}]\'; exit 0; fi\n'
    crash, _ = run_store(tmp_path, listing + "exit 5")
    assert crash.returncode == 2
    none_installed, _ = run_store(tmp_path, "echo '[]'")
    assert none_installed.returncode == 2


def test_unknown_subcommand_exits_2_with_usage(root):
    done = subprocess.run([HOOK_PYTHON, script(root)], capture_output=True, text=True)
    assert done.returncode == 2 and "Usage:" in done.stderr


def test_store_for_a_plugin_without_keys_stores_nothing(tmp_path):
    make_root(tmp_path, {"name": "empty"})
    body = 'if [ "$2" = list ]; then echo \'[{"id":"empty@techne"}]\'; exit 0; fi\nexit 9'
    done, rec = run_store(tmp_path, body, content="S2_API_KEY=topsecret\n")
    assert done.returncode == 2 and "unknown name" in done.stderr
    assert "topsecret" not in done.stdout + done.stderr
    assert not list(rec.iterdir())


# store into every plugin that declares the key

OTHER = {
    "name": "other",
    "userConfig": {
        "s2_api_key": {"type": "string", "title": "S2", "description": "S2.", "sensitive": True},
        "other_secret_key": {
            "type": "string",
            "title": "Other",
            "description": "Other.",
            "sensitive": True,
        },
        "epo_ops_key": {"type": "string", "title": "K", "description": "K.", "sensitive": True},
        "epo_ops_secret": {"type": "string", "title": "S", "description": "S.", "sensitive": True},
    },
    "metadata": {"keyGroups": [["epo_ops_key", "epo_ops_secret"]]},
}


def run_multi(tmp_path, others, content, *args, fail=None):
    """Run store in `synth` (installed at tmp/plug) beside other installs.

    `others` maps an id to (manifest or None, enabled, install path override or None).
    """
    shutil.rmtree(tmp_path / "rec", ignore_errors=True)
    entries = [{"id": "synth@techne", "enabled": True, "installPath": str(tmp_path / "plug")}]
    for ident, (manifest, enabled, override) in others.items():
        folder = ident.split("@")[0]
        shutil.rmtree(tmp_path / folder, ignore_errors=True)
        installed = make_root(tmp_path, manifest, name=folder) if manifest is not None else None
        path = str(installed) if override is None else override
        entries.append({"id": ident, "enabled": enabled, "installPath": path})
    fail_line = (
        f'if [ "$3" = {fail} ]; then echo "bad input topsecret" >&2; exit 7; fi\n' if fail else ""
    )
    body = (
        f"if [ \"$2\" = list ]; then printf '%s\\n' '{json.dumps(entries)}'; exit 0; fi\n"
        'printf \'%s\\n\' "$@" > "$REC/argv.$3"\ncat > "$REC/stdin.$3"\n' + fail_line + "echo ok\n"
    )
    return run_store(tmp_path, body, *args, content=content)


def sent(rec):
    return {f.name[len("stdin.") :]: json.loads(f.read_text()) for f in rec.glob("stdin.*")}


def test_a_shared_key_is_stored_in_every_plugin_that_declares_it(tmp_path):
    done, rec = run_multi(tmp_path, {"other@techne": (OTHER, True, None)}, "S2_API_KEY=topsecret\n")
    assert done.returncode == 0, done.stderr
    assert sent(rec) == {
        "synth@techne": {"s2_api_key": "topsecret"},
        "other@techne": {"s2_api_key": "topsecret"},
    }
    lines = done.stdout.splitlines()
    assert "Stored in Claude Code's secure storage for synth@techne: S2_API_KEY" in lines
    assert "Stored in Claude Code's secure storage for other@techne: S2_API_KEY" in lines
    for argv in rec.glob("argv.*"):
        assert "topsecret" not in argv.read_text()
        assert argv.read_text().split()[:2] == ["plugin", "configure"]
    assert "topsecret" not in done.stdout + done.stderr


def test_a_key_only_the_other_plugin_declares_goes_only_there(tmp_path):
    other = {"other@techne": (OTHER, True, None)}
    done, rec = run_multi(tmp_path, other, "OTHER_SECRET_KEY=zz\n")
    assert done.returncode == 0, done.stderr
    assert sent(rec) == {"other@techne": {"other_secret_key": "zz"}}
    done, rec = run_multi(tmp_path, other, "OTHER_SECRET_KEY=zz\nEXTRA_API_TOKEN=lt\n")
    assert sent(rec) == {
        "synth@techne": {"extra_api_token": "lt"},
        "other@techne": {"other_secret_key": "zz"},
    }


def test_disabled_empty_path_and_unloadable_installs_are_skipped(tmp_path):
    others = {
        "off@techne": (OTHER, False, None),
        "empty@techne": (OTHER, True, ""),
        "gone@techne": (OTHER, True, str(tmp_path / "nowhere")),
        "bare@techne": ({"name": "bare"}, True, None),
        "broken@techne": (dict(OTHER, metadata={"keyGroups": [[["x"]]]}), True, None),
    }
    done, rec = run_multi(tmp_path, others, "S2_API_KEY=topsecret\n")
    assert done.returncode == 0, done.stderr
    assert sent(rec) == {"synth@techne": {"s2_api_key": "topsecret"}}
    assert done.stderr == ""


def test_a_failing_plugin_does_not_stop_the_others_and_exits_2(tmp_path):
    other = {"other@techne": (OTHER, True, None)}
    done, rec = run_multi(tmp_path, other, "S2_API_KEY=topsecret\n", fail="other@techne")
    assert done.returncode == 2
    assert "Stored in Claude Code's secure storage for synth@techne: S2_API_KEY" in done.stdout
    assert "other@techne exited 7" in done.stderr and "***" in done.stderr
    assert "topsecret" not in done.stdout + done.stderr
    first, rec = run_multi(tmp_path, other, "S2_API_KEY=topsecret\n", fail="synth@techne")
    assert first.returncode == 2 and "synth@techne exited 7" in first.stderr
    assert "Stored in Claude Code's secure storage for other@techne" in first.stdout
    assert set(sent(rec)) == {"synth@techne", "other@techne"}


def test_plugin_flag_stores_into_that_plugin_only_without_listing(tmp_path):
    other = {"other@techne": (OTHER, True, None)}
    done, rec = run_multi(tmp_path, other, "S2_API_KEY=topsecret\n", "--plugin", "other@techne")
    assert done.returncode == 0, done.stderr
    assert sent(rec) == {"other@techne": {"s2_api_key": "topsecret"}}
    done, rec = run_multi(tmp_path, other, "S2_API_KEY=topsecret\n", "--plugin", "synth@techne")
    assert set(sent(rec)) == {"synth@techne"}


def test_a_name_no_plugin_declares_is_the_line_numbered_error(tmp_path):
    other = {"other@techne": (OTHER, True, None)}
    done, rec = run_multi(tmp_path, other, "S2_API_KEY=ok\nNOPE=hunter2hunter2\n")
    assert done.returncode == 2 and "line 2" in done.stderr and "NOPE" in done.stderr
    assert "hunter2" not in done.stderr and not list(rec.glob("stdin.*"))
    done, rec = run_multi(tmp_path, {}, "OTHER_SECRET_KEY=zz\n")
    assert done.returncode == 2 and "line 1" in done.stderr and not list(rec.glob("stdin.*"))


def test_half_group_warnings_are_per_plugin(tmp_path):
    other = {"other@techne": (OTHER, True, None)}
    done, _ = run_multi(tmp_path, other, "EPO_OPS_KEY=k2\n")
    assert done.returncode == 0, done.stderr
    assert "warning: synth@techne: EPO_OPS_KEY given without EPO_OPS_SECRET" in done.stderr
    assert "warning: other@techne: EPO_OPS_KEY given without EPO_OPS_SECRET" in done.stderr
    solo = {"other@techne": (dict(OTHER, metadata={}), True, None)}
    done, _ = run_multi(tmp_path, solo, "EPO_OPS_KEY=k2\n")
    assert "other@techne: EPO_OPS_KEY given" not in done.stderr
    assert "synth@techne: EPO_OPS_KEY given" in done.stderr


def test_own_install_needs_a_string_id_named_for_this_plugin(tmp_path):
    here = tmp_path / "here"
    here.mkdir()
    listing = json.dumps(
        [
            {"id": 5, "installPath": str(here)},
            {"id": "", "installPath": str(here)},
            {"id": "other@techne", "enabled": True, "installPath": str(here)},
            {"id": "synth@techne", "enabled": True, "installPath": str(tmp_path / "x")},
        ]
    )
    assert pk.find_plugin_id(listing, None, "synth", here) == "synth@techne"
    bad = json.dumps([{"id": "other@techne", "installPath": str(here)}, {"id": 7}])
    with pytest.raises(pk.StoreError, match="not installed"):
        pk.find_plugin_id(bad, None, "synth", here)
