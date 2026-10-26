"""Each local marketplace entry repeats its plugin.json description word for word."""

from __future__ import annotations

import json
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
MARKETPLACE = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
LOCAL = [
    e
    for e in MARKETPLACE["plugins"]
    if isinstance(e.get("source"), str) and e["source"].startswith("./")
]


@pytest.mark.parametrize("entry", LOCAL, ids=[e["name"] for e in LOCAL])
def test_marketplace_description_matches_the_plugin(entry):
    manifest = ROOT / entry["source"] / ".claude-plugin" / "plugin.json"
    assert entry["description"] == json.loads(manifest.read_text())["description"]


def test_every_local_plugin_is_checked():
    assert {e["name"] for e in LOCAL} >= {"techne", "phylax", "heuresis", "schole"}
