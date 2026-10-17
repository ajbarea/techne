"""heuresis search keys: the shared table, the SessionStart hook and the store script."""

from __future__ import annotations

import json
import os
import subprocess
import time

import pytest
from conftest import HOOK_PYTHON, ROOT, _load, stub_dir

PLUGIN = ROOT / "plugins" / "heuresis"
TABLE = _load("heuresis_search_keys", PLUGIN / "hooks" / "search_keys.py")
HOOK = PLUGIN / "hooks" / "session_keys.py"
STORE = PLUGIN / "skills" / "setup" / "scripts" / "store_keys.py"
store = _load("heuresis_store_keys", STORE)
hook = _load("heuresis_session_keys", HOOK)
SECRET = "s3cr3t value 'with' \"quotes\" $HOME `x` \\ end"
OPTION_VARS = [f"CLAUDE_PLUGIN_OPTION_{k.option.upper()}" for k in TABLE.KEYS]
S2 = "CLAUDE_PLUGIN_OPTION_S2_API_KEY"


def run_hook(tmp_path, env, mode="start", sid="sess-1", stdin=None, with_file=True, with_data=True):
    target = tmp_path / "env.sh"
    data = tmp_path / "data"
    base = {"PATH": os.environ["PATH"], **env}
    if with_file:
        base["CLAUDE_ENV_FILE"] = str(target)
    if with_data:
        base["CLAUDE_PLUGIN_DATA"] = str(data)
    payload = json.dumps({"session_id": sid}) if stdin is None else stdin
    done = subprocess.run(
        [HOOK_PYTHON, str(HOOK), mode], env=base, input=payload, capture_output=True, text=True
    )
    return done, target, data / "session-keys"


def sourced(target, name, env=None):
    cmd = f'. "{target}"; printf %s "${name}"'
    return subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, env=env or {}).stdout


def tree(root):
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*")) if root.exists() else []


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


def hook_commands():
    hooks = json.loads((PLUGIN / "hooks" / "hooks.json").read_text())["hooks"]
    return {
        event: hooks[event][0]["hooks"][0]["command"] for event in ("SessionStart", "SessionEnd")
    }


@pytest.mark.parametrize("event,mode", [("SessionStart", "start"), ("SessionEnd", "end")])
def test_hook_commands_run_the_script_and_exit_0_without_python3(tmp_path, event, mode):
    command = hook_commands()[event]
    assert f'session_keys.py" {mode}' in command and "exec" not in command
    marker = tmp_path / "ran"
    bindir = stub_dir(tmp_path, {"python3": f'echo "$@" > {marker}'}, links=["sh"])
    env = {"PATH": bindir, "CLAUDE_PLUGIN_ROOT": str(PLUGIN)}
    done = subprocess.run(["sh", "-c", command], env=env, capture_output=True, text=True)
    assert done.returncode == 0 and marker.read_text().split()[-1] == mode
    bare = stub_dir(tmp_path, {}, links=["sh"])
    done = subprocess.run(
        ["sh", "-c", command], env={"PATH": bare, "CLAUDE_PLUGIN_ROOT": str(PLUGIN)}
    )
    assert done.returncode == 0


# the hook


@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions")
def test_session_file_is_0600_in_a_0700_dir(tmp_path):
    (tmp_path / "data" / "session-keys").mkdir(parents=True, mode=0o755)
    done, _, directory = run_hook(tmp_path, {S2: SECRET})
    assert done.returncode == 0
    assert directory.stat().st_mode & 0o777 == 0o700
    assert (directory / "sess-1.sh").stat().st_mode & 0o777 == 0o600
    assert tree(directory) == ["sess-1.sh"]  # no temp file left


def test_env_file_holds_only_a_source_line_never_a_value(tmp_path):
    env = {var: f"value-{i}-{SECRET}" for i, var in enumerate(OPTION_VARS)}
    done, target, directory = run_hook(tmp_path, env)
    text = target.read_text()
    path = str(directory / "sess-1.sh")
    assert text == f"if [ -f {path} ]; then . {path}; fi\n"
    assert "value-" not in text and SECRET not in text
    assert "value-" not in done.stdout + done.stderr and not (done.stdout + done.stderr)


def test_sourcing_the_env_file_yields_every_value(tmp_path):
    env = {var: f"v{i} {SECRET}" for i, var in enumerate(OPTION_VARS)}
    _, target, _ = run_hook(tmp_path, env)
    for i, key in enumerate(TABLE.KEYS):
        assert sourced(target, key.env) == f"v{i} {SECRET}"


def test_a_variable_already_in_the_bash_env_wins(tmp_path):
    _, target, _ = run_hook(tmp_path, {S2: "saved", "CLAUDE_PLUGIN_OPTION_LENS_API_TOKEN": "lens"})
    assert sourced(target, "S2_API_KEY", {"S2_API_KEY": "shell"}) == "shell"
    assert sourced(target, "LENS_API_TOKEN", {"S2_API_KEY": "shell"}) == "lens"
    assert sourced(target, "S2_API_KEY", {"S2_API_KEY": ""}) == "saved"


def test_hook_appends_to_an_existing_env_file(tmp_path):
    (tmp_path / "env.sh").write_text("export OTHER=1\n")
    _, target, _ = run_hook(tmp_path, {S2: "x"})
    assert target.read_text().startswith("export OTHER=1\nif [ -f ")


def test_end_deletes_the_session_file_and_missing_is_fine(tmp_path):
    _, _, directory = run_hook(tmp_path, {S2: "x"})
    assert (directory / "sess-1.sh").exists()
    done, _, _ = run_hook(tmp_path, {}, mode="end")
    assert done.returncode == 0 and not (directory / "sess-1.sh").exists()
    done, _, _ = run_hook(tmp_path, {}, mode="end")
    assert done.returncode == 0


def test_prune_removes_an_old_file_and_keeps_a_fresh_one(tmp_path):
    directory = tmp_path / "data" / "session-keys"
    directory.mkdir(parents=True)
    old, fresh = directory / "old.sh", directory / "fresh.sh"
    old.write_text("x")
    fresh.write_text("x")
    age = time.time() - hook.MAX_AGE_SECONDS - 60
    os.utime(old, (age, age))
    run_hook(tmp_path, {S2: "x"})
    assert not old.exists() and fresh.exists() and (directory / "sess-1.sh").exists()


@pytest.mark.parametrize("sid", ["../x", "a/b", "", "a b", "x\n", "a" * 200, "..", "a.sh"])
def test_unsafe_session_id_writes_nothing(tmp_path, sid):
    done, _, _ = run_hook(tmp_path, {S2: "x"}, sid=sid)
    assert done.returncode == 0
    assert tree(tmp_path) == []


def test_no_options_writes_nothing_and_removes_a_stale_session_file(tmp_path):
    _, target, directory = run_hook(tmp_path, {S2: "x"})
    target.unlink()
    done, target, _ = run_hook(tmp_path, {S2: ""})
    assert done.returncode == 0 and not target.exists()
    assert not (directory / "sess-1.sh").exists()


@pytest.mark.parametrize("value", ["a\nb", "a\rb"])
def test_hook_skips_a_multiline_value(tmp_path, value):
    _, target, directory = run_hook(tmp_path, {S2: value})
    assert not target.exists() and not (directory / "sess-1.sh").exists()


def test_hook_skips_a_nul_value():
    # a NUL cannot cross the process environment, so this checks the function
    assert hook.export_lines({S2: "a\0b"}) == []


def test_hook_without_env_file_writes_nothing(tmp_path):
    done, _, directory = run_hook(tmp_path, {S2: "x"}, with_file=False)
    assert done.returncode == 0 and not (directory / "sess-1.sh").exists()


@pytest.mark.parametrize("stdin", ["", "not json", "[]", "{}", '{"session_id": 5}'])
def test_malformed_stdin_exits_0_and_writes_nothing(tmp_path, stdin):
    done, _, _ = run_hook(tmp_path, {S2: SECRET}, stdin=stdin)
    assert done.returncode == 0 and tree(tmp_path) == []
    assert SECRET not in done.stdout + done.stderr


def test_missing_plugin_data_exits_0_and_writes_nothing(tmp_path):
    done, _, _ = run_hook(tmp_path, {S2: SECRET}, with_data=False)
    assert done.returncode == 0 and tree(tmp_path) == []


def test_hook_exits_0_when_the_env_file_is_unwritable(tmp_path):
    env = {S2: SECRET, "CLAUDE_ENV_FILE": str(tmp_path / "no" / "f")}
    done, _, _ = run_hook(tmp_path, env, with_file=False)
    assert done.returncode == 0 and SECRET not in done.stdout + done.stderr


# the store script


def test_template_lists_every_name_with_its_comment():
    out = subprocess.run([HOOK_PYTHON, str(STORE), "--template"], capture_output=True, text=True)
    assert out.returncode == 0
    lines = out.stdout.splitlines()
    for key in TABLE.KEYS:
        assert f"{key.env}=" in lines
        head = key.why.split("; ")[0]
        assert any(x.startswith("# ") and head[1:] in x for x in lines)
    assert store.parse(out.stdout) == {}


def test_template_grouped_keys_name_their_partner():
    lines = store.template().splitlines()
    assert "# Adds European patents, with EPO_OPS_SECRET; register at developers.epo.org" in lines
    assert "# Adds European patents, with EPO_OPS_KEY; register at developers.epo.org" in lines
    assert len({x for x in lines if x.startswith("#")}) == len(TABLE.KEYS)


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


def test_parse_keeps_equals_signs_and_hash_without_space():
    assert store.parse("S2_API_KEY=a=b==\nLENS_API_TOKEN=ab#cd\n") == {
        "S2_API_KEY": "a=b==",
        "LENS_API_TOKEN": "ab#cd",
    }


def test_parse_cuts_inline_comments():
    text = (
        "S2_API_KEY=abc # note\nLENS_API_TOKEN=def\t# tab\n"
        'OPENALEX_API_KEY=\'q # kept\'  # note\nEPO_OPS_KEY="e"#x"\n'
    )
    with pytest.raises(store.StoreError):  # text after the closing quote
        store.parse(text)
    ok = store.parse(text.replace('#x"', ""))
    assert ok == {
        "S2_API_KEY": "abc",
        "LENS_API_TOKEN": "def",
        "OPENALEX_API_KEY": "q # kept",
        "EPO_OPS_KEY": "e",
    }
    assert store.parse("S2_API_KEY= # only a comment\n") == {}


def test_parse_unterminated_quote_names_line_and_name_not_value():
    with pytest.raises(store.StoreError) as err:
        store.parse("S2_API_KEY=ok\nLENS_API_TOKEN='hunter2hunter2\n")
    assert "line 2" in str(err.value) and "LENS_API_TOKEN" in str(err.value)
    assert "hunter2" not in str(err.value)


def test_store_reads_a_file_with_a_bom(tmp_path):
    done, rec = run_store(tmp_path, CLAUDE_OK, content="\ufeffS2_API_KEY=topsecret\n")
    assert done.returncode == 0, done.stderr
    assert json.loads((rec / "stdin").read_text()) == {"s2_api_key": "topsecret"}


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
    keys.write_text(content, encoding="utf-8")
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


def test_store_prefers_the_enabled_install(tmp_path):
    body = (
        'if [ "$2" = list ]; then echo \'[{"id":"heuresis@old","enabled":false},'
        '{"id":"heuresis@techne","enabled":true}]\'; exit 0; fi\n' + CLAUDE_OK
    )
    done, rec = run_store(tmp_path, body)
    assert done.returncode == 0, done.stderr
    assert "heuresis@techne" in (rec / "argv").read_text()


def test_pick_plugin_id_cases():
    pick = store.find_plugin_id
    one_disabled = json.dumps([{"id": "heuresis@a", "enabled": False}])
    assert pick(one_disabled, None) == "heuresis@a"
    assert pick(json.dumps([{"id": "heuresis@a"}, {"id": "x@y"}]), None) == "heuresis@a"
    both_off = json.dumps(
        [{"id": "heuresis@a", "enabled": False}, {"id": "heuresis@b", "enabled": False}]
    )
    for listing in (both_off, json.dumps([{"id": "heuresis@a"}, {"id": "heuresis@b"}])):
        with pytest.raises(store.StoreError, match="heuresis@a, heuresis@b"):
            pick(listing, None)


def test_redact_hides_raw_and_json_escaped_values():
    value = 'a"b\\c'
    text = f"raw {value} escaped {json.dumps(value)[1:-1]}"
    assert value not in store.redact(text, [value]) and 'a\\"b' not in store.redact(text, [value])


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
