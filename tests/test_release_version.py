"""The release version is declared in four places; they must agree."""

from __future__ import annotations

import json
import re
import tomllib

from conftest import ROOT


def _cff(key: str) -> str:
    text = (ROOT / "CITATION.cff").read_text()
    m = re.search(rf'^{key}:\s*"?([^"\n]+?)"?\s*$', text, re.MULTILINE)
    assert m, f"CITATION.cff has no {key}"
    return m.group(1)


def _locked() -> str:
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    return next(p["version"] for p in lock["package"] if p["name"] == "techne")


def test_versions_are_in_step():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())["version"]
    bibtex = re.search(r"version\s*=\s*\{([^}]+)\}", (ROOT / "README.md").read_text())
    assert bibtex, "README.md Cite block has no BibTeX version"
    assert project == market == _cff("version") == _locked() == bibtex.group(1)


def test_release_date_is_an_iso_date():
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", _cff("date-released"))


def test_citation_cff_is_the_only_citation_file():
    assert not (ROOT / ".zenodo.json").exists()
