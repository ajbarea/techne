"""heuresis search keys: the shared table, the SessionStart hook and the store script."""

from __future__ import annotations

import json
import os
import subprocess

import pytest
from conftest import HOOK_PYTHON, ROOT, _load, stub_dir

PLUGIN = ROOT / "plugins" / "heuresis"
TABLE = _load("heuresis_search_keys", PLUGIN / "hooks" / "search_keys.py")
HOOK = PLUGIN / "hooks" / "export_keys.py"
STORE = PLUGIN / "skills" / "setup" / "scripts" / "store_keys.py"
store = _load("heuresis_store_keys", STORE)
SECRET = "s3cr3t value 'with' \"quotes\" $HOME `x` \\ end"
OPTION_VARS = [f"CLAUDE_PLUGIN_OPTION_{k.option.upper()}" for k in TABLE.KEYS]


def run_hook(tmp_path, env, *, with_file=True):
    target = tmp_path / "env.sh"
    base = {"PATH": os.environ["PATH"], **env}
    if with_file:
        base["CLAUDE_ENV_FILE"] = str(target)
    done = subprocess.run([HOOK_PYTHON, str(HOOK)], env=base, capture_output=True, text=True)
    return done, target


def sourced(target, name):
    cmd = f'source "{target}"; printf %s "${name}"'
    return subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, env={}).stdout


# the table and the manifest


def test_table_names_every_key_once():
    assert [k.env for k in TABLE.KEYS] == [
        "OPENALEX_API_KEY",
        "S2_API_KEY",
        "LENS_API_TOKEN",
        "EPO_OPS_KEY",
        "EPO_OPS_SECRET",
    ]
    assert len({k.option for k in TABLE.KEYS}) == len(TABLE.KEYS)


def test_manifest_options_match_the_table_and_are_sensitive():
    manifest = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())
    opts = manifest["userConfig"]
    keyed = {n: o for n, o in opts.items() if o.get("sensitive")}
    assert set(keyed) == {k.option for k in TABLE.KEYS}
    assert {"ideas_repo", "repos_root"} <= set(opts)
    for k in TABLE.KEYS:
        opt = opts[k.option]
        assert opt["type"] == "string" and not opt.get("required")
        assert opt["description"].lower().startswith(k.why.lower())
        assert set(opt) <= {"type", "title", "description", "required", "sensitive"}


def test_hook_option_env_names_match_the_guard():
    hooks = json.loads((PLUGIN / "hooks" / "hooks.json").read_text())
    command = hooks["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    for var in OPTION_VARS:
        assert f"${var}" in command
    assert "export_keys.py" in command


# the hook's shell guard


@pytest.mark.parametrize("value", ["", "x"])
def test_guard_starts_python_only_when_an_option_is_set(tmp_path, value):
    hooks = json.loads((PLUGIN / "hooks" / "hooks.json").read_text())
    command = hooks["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    marker = tmp_path / "ran"
    bindir = stub_dir(tmp_path, {"python3": f"echo ran > {marker}"}, links=["bash"])
    env = {
        "PATH": bindir,
        "CLAUDE_PLUGIN_ROOT": str(PLUGIN),
        "CLAUDE_PLUGIN_OPTION_S2_API_KEY": value,
    }
    done = subprocess.run(["bash", "-c", command], env=env, capture_output=True, text=True)
    assert done.returncode == 0
    assert marker.exists() == bool(value)


# the hook


def test_hook_writes_quoted_exports_that_round_trip(tmp_path):
    done, target = run_hook(tmp_path, {"CLAUDE_PLUGIN_OPTION_S2_API_KEY": SECRET})
    assert done.returncode == 0
    assert target.read_text().startswith("export S2_API_KEY=")
    assert sourced(target, "S2_API_KEY") == SECRET


def test_hook_writes_every_option_it_is_given(tmp_path):
    env = {var: f"v{i}" for i, var in enumerate(OPTION_VARS)}
    _, target = run_hook(tmp_path, env)
    for i, key in enumerate(TABLE.KEYS):
        assert sourced(target, key.env) == f"v{i}"


def test_hook_leaves_a_key_already_exported_in_the_shell(tmp_path):
    env = {
        "CLAUDE_PLUGIN_OPTION_S2_API_KEY": "saved",
        "S2_API_KEY": "shell",
        "CLAUDE_PLUGIN_OPTION_LENS_API_TOKEN": "lens",
    }
    _, target = run_hook(tmp_path, env)
    text = target.read_text()
    assert "S2_API_KEY" not in text and "LENS_API_TOKEN=lens" in text


def test_hook_replaces_an_empty_exported_key(tmp_path):
    env = {"CLAUDE_PLUGIN_OPTION_S2_API_KEY": "saved", "S2_API_KEY": ""}
    _, target = run_hook(tmp_path, env)
    assert sourced(target, "S2_API_KEY") == "saved"


def test_hook_writes_nothing_without_an_env_file(tmp_path):
    done, target = run_hook(tmp_path, {"CLAUDE_PLUGIN_OPTION_S2_API_KEY": "x"}, with_file=False)
    assert done.returncode == 0 and not target.exists()


def test_hook_skips_a_multiline_value(tmp_path):
    done, target = run_hook(tmp_path, {"CLAUDE_PLUGIN_OPTION_S2_API_KEY": "a\nb"})
    assert done.returncode == 0 and not target.exists()


def test_hook_skips_a_nul_value():
    # a NUL cannot cross the process environment, so this checks the function
    mod = _load("heuresis_export_keys", HOOK)
    assert mod.export_lines({"CLAUDE_PLUGIN_OPTION_S2_API_KEY": "a\0b"}) == []


def test_hook_appends_and_never_prints_a_value(tmp_path):
    target = tmp_path / "env.sh"
    target.write_text("export OTHER=1\n")
    done, _ = run_hook(tmp_path, {"CLAUDE_PLUGIN_OPTION_S2_API_KEY": SECRET})
    assert target.read_text().startswith("export OTHER=1\n")
    assert SECRET not in done.stdout + done.stderr and not (done.stdout + done.stderr)


def test_hook_exits_0_when_the_env_file_is_unwritable(tmp_path):
    env = {"CLAUDE_PLUGIN_OPTION_S2_API_KEY": SECRET, "CLAUDE_ENV_FILE": str(tmp_path / "no" / "f")}
    done = subprocess.run(
        [HOOK_PYTHON, str(HOOK)],
        env={"PATH": os.environ["PATH"], **env},
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0 and SECRET not in done.stdout + done.stderr


# the store script


def test_template_lists_every_name_with_its_comment():
    out = subprocess.run([HOOK_PYTHON, str(STORE), "--template"], capture_output=True, text=True)
    assert out.returncode == 0
    lines = out.stdout.splitlines()
    for key in TABLE.KEYS:
        assert f"{key.env}=" in lines
        assert any(x.startswith("#") and key.why[1:] in x for x in lines)
    assert store.parse(out.stdout) == {}


def test_parse_handles_comments_export_quotes_and_empties():
    text = (
        "# note\n\nS2_API_KEY=abc  \nexport LENS_API_TOKEN='q u'\n"
        'OPENALEX_API_KEY="d"\nEPO_OPS_KEY=\nEPO_OPS_SECRET= \n'
    )
    assert store.parse(text) == {
        "S2_API_KEY": "abc",
        "LENS_API_TOKEN": "q u",
        "OPENALEX_API_KEY": "d",
    }


def test_parse_keeps_mismatched_quotes_and_equals_signs():
    assert store.parse("S2_API_KEY='abc\nLENS_API_TOKEN=a=b==\n") == {
        "S2_API_KEY": "'abc",
        "LENS_API_TOKEN": "a=b==",
    }


def test_unknown_name_error_names_line_and_name_not_value():
    with pytest.raises(store.StoreError) as err:
        store.parse("S2_API_KEY=ok\nGITHUB_TOKEN=hunter2hunter2\n")
    assert "line 2" in str(err.value) and "GITHUB_TOKEN" in str(err.value)
    assert "hunter2" not in str(err.value)
    with pytest.raises(store.StoreError) as err:
        store.parse("hunter2hunter2\n")
    assert "hunter2" not in str(err.value)


CLAUDE_OK = """\
if [ "$1 $2" = "plugin list" ]; then
  echo '[{"id":"graphe@techne","scope":"user"},{"id":"heuresis@techne","scope":"user"}]'
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
    keys.write_text(content)
    keys.chmod(mode)
    path = stub_dir(tmp_path, {"claude": body} if body else {}, links=["cat", "printf"])
    done = subprocess.run(
        [HOOK_PYTHON, str(STORE), str(keys), *args],
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
    assert argv == ["plugin", "configure", "heuresis@techne", "--values-stdin"]
    assert "topsecret" not in (rec / "argv").read_text()
    assert "S2_API_KEY" in done.stdout and "EPO_OPS_KEY" in done.stdout
    assert "topsecret" not in done.stdout + done.stderr
    assert "Restart Claude Code" in done.stdout


def test_store_uses_the_given_plugin_id_without_listing(tmp_path):
    body = 'if [ "$1" = list ] || [ "$2" = list ]; then exit 9; fi\n' + CLAUDE_OK
    done, rec = run_store(tmp_path, body, "--plugin", "heuresis@mine")
    assert done.returncode == 0, done.stderr
    assert "heuresis@mine" in (rec / "argv").read_text()


def test_store_refuses_several_heuresis_ids(tmp_path):
    body = """echo '[{"id":"heuresis@a"},{"id":"heuresis@b"}]'"""
    done, _ = run_store(tmp_path, body)
    assert done.returncode == 2
    assert "heuresis@a" in done.stderr and "heuresis@b" in done.stderr
    assert "topsecret" not in done.stdout + done.stderr


def test_store_names_the_missing_install(tmp_path):
    done, _ = run_store(tmp_path, "echo '[]'")
    assert done.returncode == 2 and "not installed" in done.stderr


def test_store_failure_redacts_values(tmp_path):
    body = (
        'if [ "$2" = list ]; then echo \'[{"id":"heuresis@techne"}]\'; exit 0; fi\n'
        'v=$(cat); echo "bad input: $v and topsecret and k2" >&2; exit 7'
    )
    done, _ = run_store(tmp_path, body)
    assert done.returncode == 1
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
    assert done.returncode == 0 and "readable by others" in done.stderr
    assert "topsecret" not in done.stdout + done.stderr
    quiet, _ = run_store(tmp_path, CLAUDE_OK, mode=0o600)
    assert "readable by others" not in quiet.stderr
