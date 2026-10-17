"""heuresis runs from its own lock, which must match the root lock and get Dependabot updates."""

from __future__ import annotations

import yaml
from conftest import ROOT, locked_versions

PLUGIN = ROOT / "plugins" / "heuresis"
RUNTIME = ("pyyaml",)


def test_root_and_plugin_locks_pin_the_same_runtime_versions():
    root, plugin = locked_versions(ROOT / "uv.lock"), locked_versions(PLUGIN / "uv.lock")
    assert set(RUNTIME) <= set(plugin) and set(RUNTIME) <= set(root)
    shared = sorted((set(plugin) & set(root)) - {"heuresis", "techne"})
    differ = {n: (plugin[n], root[n]) for n in shared if plugin[n] != root[n]}
    assert not differ, f"plugin lock vs root lock: {differ}; re-lock so they match"


def test_dependabot_updates_the_plugin_lock():
    updates = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text())["updates"]
    uv = next(u for u in updates if u["package-ecosystem"] == "uv")
    assert {"/", "/plugins/heuresis"} <= set(uv.get("directories", [uv.get("directory")]))
