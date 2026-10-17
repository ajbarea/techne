"""Each plugin's manifest keys match the environment variables its code reads, and its hooks."""

from __future__ import annotations

import json
import re
import subprocess

import pytest
from conftest import HOOK_PYTHON, ROOT, _load

SHARED = ROOT / "plugins" / "techne" / "_shared" / "plugin_keys.py"
pk = _load("techne_plugin_keys_manifests", SHARED)
EXPECTED = {
    "heuresis": [
        "OPENALEX_API_KEY",
        "S2_API_KEY",
        "LENS_API_TOKEN",
        "EPO_OPS_KEY",
        "EPO_OPS_SECRET",
    ],
    "graphe": ["OPENALEX_API_KEY", "S2_API_KEY"],
}
# Names the plugins' code mentions that are not user secrets saved in a manifest:
# heuresis reads GITHUB_TOKEN only as an optional override, and falls back to `gh`.
NOT_SAVED = {"GITHUB_TOKEN"}
SECRET_NAME = re.compile(r"[A-Z][A-Z0-9_]*_(API_KEY|KEY|TOKEN|SECRET)")
STRING_LITERAL = re.compile(r"""["']([A-Z][A-Z0-9_]*)["']""")


def plugin_root(name):
    return ROOT / "plugins" / name


def secret_names_in_code(name):
    """Every string literal shaped like a secret's variable name in the plugin's Python sources,
    however it is read (os.getenv, os.environ.get, a module constant). Tests and the shared key
    module itself are not the plugin's code."""
    found = set()
    for path in plugin_root(name).rglob("*.py"):
        if path.name == "plugin_keys.py" or "tests" in path.relative_to(plugin_root(name)).parts:
            continue
        found |= set(STRING_LITERAL.findall(path.read_text(encoding="utf-8")))
    return {n for n in found if SECRET_NAME.fullmatch(n)} - NOT_SAVED


@pytest.mark.parametrize("name", EXPECTED)
def test_manifest_keys_are_the_env_vars_the_code_reads(name):
    keys = pk.load_keys(plugin_root(name))
    assert [k.env for k in keys] == EXPECTED[name]
    assert secret_names_in_code(name) == set(EXPECTED[name])


def test_the_drift_scan_sees_constants_and_getenv(tmp_path, monkeypatch):
    plugin = tmp_path / "plugins" / "p"
    plugin.mkdir(parents=True)
    (plugin / "a.py").write_text('KEY = "NEW_API_KEY"\nos.getenv("OTHER_TOKEN")\nx = "LOWER_key"\n')
    monkeypatch.setitem(globals(), "ROOT", tmp_path)
    assert secret_names_in_code("p") == {"NEW_API_KEY", "OTHER_TOKEN"}


@pytest.mark.parametrize("name", EXPECTED)
def test_manifest_key_options_are_optional_sensitive_strings_with_a_source(name):
    options = json.loads((plugin_root(name) / ".claude-plugin" / "plugin.json").read_text())[
        "userConfig"
    ]
    for key in pk.load_keys(plugin_root(name)):
        opt = options[key.option]
        assert opt["type"] == "string" and opt["sensitive"] is True and not opt.get("required")
        assert set(opt) <= {"type", "title", "description", "required", "sensitive"}
        assert re.search(r"\b(free at|request|register|lens\.org)", opt["description"])
        assert opt["description"].endswith(".")


def test_every_plugin_manifest_loads_strictly():
    """A bad key name or key group fails here, not at a user's session start."""
    for manifest in (ROOT / "plugins").glob("*/.claude-plugin/plugin.json"):
        options = json.loads(manifest.read_text(encoding="utf-8")).get("userConfig", {})
        plugin = pk.load_plugin(manifest.parent.parent)
        sensitive = [
            n
            for n, o in options.items()
            if isinstance(o, dict) and o.get("sensitive") is True and o.get("type") == "string"
        ]
        assert [k.option for k in plugin.keys] == sensitive, manifest.parent.parent.name


def test_every_sensitive_option_has_a_description_and_the_hook():
    for manifest in (ROOT / "plugins").glob("*/.claude-plugin/plugin.json"):
        plugin = manifest.parent.parent
        options = json.loads(manifest.read_text(encoding="utf-8")).get("userConfig", {})
        sensitive = {n: o for n, o in options.items() if isinstance(o, dict) and o.get("sensitive")}
        for option, spec in sensitive.items():
            assert str(spec.get("description", "")).strip(), f"{plugin.name}.{option}"
        if sensitive:
            hooks = (plugin / "hooks" / "hooks.json").read_text(encoding="utf-8")
            assert "_shared/plugin_keys.py" in hooks, plugin.name


def test_heuresis_declares_the_epo_pair_as_one_group():
    manifest = json.loads((plugin_root("heuresis") / ".claude-plugin" / "plugin.json").read_text())
    assert manifest["metadata"] == {"keyGroups": [["epo_ops_key", "epo_ops_secret"]]}
    keys = pk.load_keys(plugin_root("heuresis"))
    assert {k.env: k.group for k in keys}["EPO_OPS_KEY"] == 0
    assert pk.group_labels(keys) == {0: "EPO_OPS"}
    assert {k.group for k in pk.load_keys(plugin_root("graphe"))} == {-1}


def test_every_plugin_with_sensitive_options_ships_the_hook_and_a_synced_module():
    for manifest in (ROOT / "plugins").glob("*/.claude-plugin/plugin.json"):
        plugin = manifest.parent.parent
        if pk.load_keys(plugin):
            assert (plugin / "hooks" / "hooks.json").is_file(), plugin.name
            assert (plugin / "_shared" / "plugin_keys.py").read_bytes() == SHARED.read_bytes()


def test_hooks_json_is_identical_in_shape_across_plugins():
    docs = [json.loads((plugin_root(n) / "hooks" / "hooks.json").read_text()) for n in EXPECTED]
    assert docs[0] == docs[1]
    hooks = docs[0]["hooks"]
    assert set(hooks) == {"SessionStart", "SessionEnd"}
    for event, mode in (("SessionStart", "start"), ("SessionEnd", "end")):
        (entry,) = hooks[event]
        (hook,) = entry["hooks"]
        guard = '[ -d "${CLAUDE_PLUGIN_DATA}/session-keys" ] && ' if mode == "end" else ""
        assert hook["command"] == (
            f"{guard}command -v python3 >/dev/null 2>&1 && exec python3 "
            f'"${{CLAUDE_PLUGIN_ROOT}}/_shared/plugin_keys.py" {mode}; exit 0'
        )
        assert hook["type"] == "command" and hook["timeout"] == 10


@pytest.mark.parametrize("name", EXPECTED)
def test_template_prints_every_env_var(name):
    out = subprocess.run(
        [HOOK_PYTHON, str(plugin_root(name) / "_shared" / "plugin_keys.py"), "template"],
        capture_output=True,
        text=True,
    )
    assert out.returncode == 0
    assert [x[:-1] for x in out.stdout.splitlines() if x.endswith("=")] == EXPECTED[name]
