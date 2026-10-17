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
# Read by a plugin's code but never a saved key: heuresis falls back to `gh` for GitHub.
NOT_SAVED = {"GITHUB_TOKEN", "OPENALEX_MAILTO"}
ENV_READ = re.compile(r"""environ(?:\.get)?\s*[(\[]\s*["']([A-Z][A-Z0-9_]*)["']""")


def plugin_root(name):
    return ROOT / "plugins" / name


def env_vars_read(name):
    """Names the plugin's Python source reads from the environment, found by grep."""
    found = set()
    for path in plugin_root(name).rglob("*.py"):
        if path.name == "plugin_keys.py":
            continue
        found |= set(ENV_READ.findall(path.read_text(encoding="utf-8")))
    return found - NOT_SAVED


@pytest.mark.parametrize("name", EXPECTED)
def test_manifest_keys_are_the_env_vars_the_code_reads(name):
    keys = pk.load_keys(plugin_root(name))
    assert [k.env for k in keys] == EXPECTED[name]
    reads = {e for e in env_vars_read(name) if e.endswith(("_KEY", "_TOKEN", "_SECRET"))}
    assert reads == set(EXPECTED[name])


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


def test_heuresis_declares_the_epo_pair_as_one_group():
    manifest = json.loads((plugin_root("heuresis") / ".claude-plugin" / "plugin.json").read_text())
    assert manifest["metadata"] == {"keyGroups": [["epo_ops_key", "epo_ops_secret"]]}
    assert {k.env: k.group for k in pk.load_keys(plugin_root("heuresis"))}["EPO_OPS_KEY"] == (
        "EPO_OPS"
    )
    assert {k.group for k in pk.load_keys(plugin_root("graphe"))} == {""}


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
        assert hook["command"] == (
            "command -v python3 >/dev/null 2>&1 && exec python3 "
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
