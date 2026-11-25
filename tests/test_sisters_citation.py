"""Tests for techne:sisters' citation check (check 18).

Each case builds a git repo, a fake `gh` that answers the webhook and release reads, and a
Zenodo record served from a file:// URL, so no case reaches GitHub or Zenodo.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "plugins" / "techne" / "skills" / "sisters" / "scripts" / "citation.py"
ORCID = "0009-0001-7938-2376"
GOOD = f"""cff-version: 1.2.0
message: Cite it.
title: "tool: a thing that does one job"
type: software
version: 1.2.0
doi: 10.5281/zenodo.100
authors:
  - given-names: AJ
    family-names: Barea
    affiliation: Rochester Institute of Technology
    orcid: "https://orcid.org/{ORCID}"
repository-code: "https://github.com/aj/tool"
license: MIT
keywords:
  - code review
  - agentic AI
  - LaTeX
"""
RECORD: dict = {
    "id": 101,
    "metadata": {
        "title": "tool: a thing that does one job",
        "creators": [
            {
                "name": "Barea, AJ",
                "orcid": ORCID,
                "affiliation": "Rochester Institute of Technology",
            }
        ],
        "keywords": ["LaTeX", "agentic AI", "code review"],
    },
}


def make_repo(tmp_path: Path, name: str = "tool", cff: str | None = GOOD, readme: str = "") -> Path:
    root = tmp_path / "ws" / name
    root.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(
        ["git", "-C", str(root), "remote", "add", "origin", f"git@github.com:aj/{name}.git"],
        check=True,
    )
    if cff is not None:
        (root / "CITATION.cff").write_text(cff)
    (root / "README.md").write_text(readme or f"# {name}\n")
    return root


def run(
    tmp_path: Path,
    *repos: Path,
    hook: bool | None = True,
    tag: str = "v1.2.0",
    record: dict | None = RECORD,
) -> list[str]:
    hooks = json.dumps(["https://zenodo.org/api/hooks/receivers/github/events/"] if hook else [])
    fake = tmp_path / "gh"
    fake.write_text(
        "#!/bin/sh\n"
        'case "$*" in\n'
        + (
            "  */hooks*) echo 'HTTP 404: Not Found' >&2; exit 1 ;;\n"
            if hook is None
            else f"  */hooks*) printf '%s' '{hooks}' ;;\n"
        )
        + f"  */releases*) printf '%s' '{json.dumps([tag] if tag else [])}' ;;\n"
        + "esac\n"
    )
    fake.chmod(0o755)
    api = tmp_path / "zenodo"
    (api / "records").mkdir(parents=True, exist_ok=True)
    if record is not None:
        (api / "records" / "100").write_text(json.dumps(record))
    out = subprocess.run(
        [sys.executable, str(SCRIPT), str(repos[0].parent), *(r.name for r in repos)],
        capture_output=True,
        text=True,
        env={**os.environ, "TECHNE_GH": str(fake), "TECHNE_ZENODO_API": api.as_uri()},
        check=True,
    )
    return out.stdout.strip().splitlines()


def test_clean_sister_passes(tmp_path):
    assert run(tmp_path, make_repo(tmp_path)) == ["tool: citation ✓"]


def test_zenodo_off_is_skipped(tmp_path):
    assert run(tmp_path, make_repo(tmp_path, cff=None), hook=False) == [
        "tool: Zenodo off (skipped)"
    ]


def test_unread_webhooks_fall_back_to_a_readme_doi(tmp_path):
    repo = make_repo(tmp_path, cff=None, readme="# tool\n[DOI](https://doi.org/10.5281/zenodo.9)\n")
    [line] = run(tmp_path, repo, hook=None)
    assert line.startswith("tool: 1 citation gap: no CITATION.cff")
    assert "webhooks not read" in line


def test_unread_webhooks_and_no_doi_is_off_with_a_note(tmp_path):
    [line] = run(tmp_path, make_repo(tmp_path, cff=None), hook=None)
    assert line.startswith("tool: Zenodo off (skipped)") and "treated as off" in line


def test_zenodo_json_is_a_gap(tmp_path):
    repo = make_repo(tmp_path)
    (repo / ".zenodo.json").write_text("{}")
    [line] = run(tmp_path, repo)
    assert ".zenodo.json present" in line


@pytest.mark.parametrize(
    ("title", "want"),
    [
        ("ajbarea/tool: tool 1.2.0", "is not"),
        ("tool", "is not"),
        ("other: a thing", "is not"),
        ("tool: a thing that does one job.", "ends with a period"),
    ],
)
def test_title_shape(tmp_path, title, want):
    cff = GOOD.replace('"tool: a thing that does one job"', json.dumps(title))
    [line] = run(tmp_path, make_repo(tmp_path, cff=cff))
    assert want in line


def test_readme_title_counts_as_the_name(tmp_path):
    cff = GOOD.replace('"tool: a', '"Tool Kit: a')
    record = json.loads(json.dumps(RECORD))
    record["metadata"]["title"] = "Tool Kit: a thing that does one job"
    repo = make_repo(tmp_path, cff=cff, readme="# 🗼 Tool Kit\n")
    assert run(tmp_path, repo, record=record) == ["tool: citation ✓"]


@pytest.mark.parametrize(
    ("drop", "want"),
    [
        ("    affiliation: Rochester Institute of Technology\n", "no affiliation"),
        (f'    orcid: "https://orcid.org/{ORCID}"\n', "no ORCID URL"),
    ],
)
def test_author_needs_orcid_and_affiliation(tmp_path, drop, want):
    [line] = run(tmp_path, make_repo(tmp_path, cff=GOOD.replace(drop, "")), record=None)
    assert f"AJ Barea: {want}" in line


def test_bare_orcid_is_not_a_url(tmp_path):
    cff = GOOD.replace(f'"https://orcid.org/{ORCID}"', f'"{ORCID}"')
    [line] = run(tmp_path, make_repo(tmp_path, cff=cff), record=None)
    assert "no ORCID URL" in line


def test_capitalized_keyword_is_a_gap_but_acronyms_pass(tmp_path):
    cff = GOOD.replace("  - code review\n", "  - Code Review\n")
    [line] = run(tmp_path, make_repo(tmp_path, cff=cff), record=None)
    assert "keywords not lowercase: Code Review" in line
    assert "agentic AI" not in line.split("lowercase:")[1]


def test_missing_keywords_license_and_repo(tmp_path):
    cff = GOOD.split("repository-code")[0]
    [line] = run(tmp_path, make_repo(tmp_path, cff=cff), record=None)
    for want in ("no keywords", "no license", "no repository-code"):
        assert want in line


def test_doi_needed_once_released(tmp_path):
    cff = GOOD.replace("doi: 10.5281/zenodo.100\n", "")
    [line] = run(tmp_path, make_repo(tmp_path, cff=cff))
    assert "no concept DOI" in line
    assert run(
        tmp_path, make_repo(tmp_path, name="pre", cff=cff.replace("tool:", "pre:")), tag=""
    ) == ["pre: citation ✓ (no release yet, so no DOI)"]


def test_version_older_than_release_is_a_gap_newer_is_not(tmp_path):
    [line] = run(tmp_path, make_repo(tmp_path), tag="v1.10.0")
    assert "version 1.2.0 older than release v1.10.0" in line
    assert run(
        tmp_path,
        make_repo(tmp_path, name="t2", cff=GOOD.replace("tool:", "t2:")),
        tag="v1.1.9",
        record={
            **RECORD,
            "metadata": {**RECORD["metadata"], "title": "t2: a thing that does one job"},
        },
    ) == ["t2: citation ✓"]


def test_live_record_drift_is_a_gap(tmp_path):
    record = {
        "id": 101,
        "metadata": {
            "title": "aj/tool: tool 1.2.0",
            "creators": [{"name": "AJ Barea", "affiliation": "Rochester Institute of Technology"}],
            "keywords": None,
        },
    }
    [line] = run(tmp_path, make_repo(tmp_path), record=record)
    assert 'Zenodo 101 title "aj/tool: tool 1.2.0" differs' in line
    assert "Zenodo 101 creators differ (AJ Barea [no ORCID, Rochester" in line
    assert "Zenodo 101 keywords differ" in line


def test_unreachable_zenodo_is_a_note_not_a_gap(tmp_path):
    [line] = run(tmp_path, make_repo(tmp_path), record=None)
    assert line.startswith("tool: citation ✓ (Zenodo record 100 not read")


@pytest.mark.parametrize(("text", "want"), [("", "not a mapping"), ("a: [b\n", "not YAML")])
def test_unparseable_file(tmp_path, text, want):
    [line] = run(tmp_path, make_repo(tmp_path, cff=text))
    assert want in line


def test_orcid_drift_across_sisters(tmp_path):
    a = make_repo(tmp_path)
    b = make_repo(
        tmp_path,
        name="two",
        cff=GOOD.replace("tool:", "two:").replace("Rochester Institute of Technology", "RIT"),
    )
    lines = run(tmp_path, a, b, record=None)
    assert lines[-1].startswith(f"ORCID {ORCID}: names or affiliation differ between sisters")
    assert "RIT in two" in lines[-1] and "Rochester Institute of Technology in tool" in lines[-1]


def test_not_cloned(tmp_path):
    (tmp_path / "ws").mkdir()
    out = subprocess.run(
        [sys.executable, str(SCRIPT), str(tmp_path / "ws"), "gone"], capture_output=True, text=True
    )
    assert out.stdout.startswith("gone: not cloned at")
