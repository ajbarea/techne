"""The elenchus findings ledger: append, the escalation ladder, and the daily fold plan."""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import subprocess

import pytest
from conftest import HOOK_PYTHON, ROOT

LEDGER = ROOT / "plugins" / "techne" / "skills" / "elenchus" / "scripts" / "ledger.py"
CATALOG = """# Catalog

## Core rubric

### 1. boundary-input: Boundary and empty inputs

- **Symptom:** s
- **Question:** q
- **Guard:** g
- **Incidents:** none recorded.

## Learned classes

### vacuous-guard: A guard that cannot fail

- **Symptom:** s
- **Question:** q
- **Guard:** g
- **Incidents:** techne#1 (2026-10-01): x.
- **Retired:** a mutation check in make test
"""


def run(state: pathlib.Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [HOOK_PYTHON, str(LEDGER), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
        env={"XDG_STATE_HOME": str(state), "PATH": "/usr/bin:/bin"},
    )


def add(state, repo, pr, cls, rnd=1, severity="Should-fix"):
    out = run(
        state,
        "append",
        "--repo",
        repo,
        "--pr",
        str(pr),
        "--round",
        str(rnd),
        "--severity",
        severity,
        "--class",
        cls,
        "--line",
        f"{cls} in {repo}#{pr}",
    )
    assert out.returncode == 0, out.stderr
    return out


def records(state: pathlib.Path) -> list[dict]:
    path = state / "elenchus" / "findings.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_append_writes_one_line_per_finding(tmp_path):
    add(tmp_path, "ajbarea/techne", "#12", "boundary-input")
    add(tmp_path, "a-private-repo", "feat/x", "New: Lost Lock!", rnd=2, severity="Blocking")
    recs = records(tmp_path)
    assert [(r["repo"], r["pr"], r["class"], r["round"]) for r in recs] == [
        ("ajbarea/techne", "12", "boundary-input", 1),
        ("a-private-repo", "feat/x", "new: lost-lock", 2),
    ]
    assert dt.datetime.fromisoformat(recs[0]["ts"]).tzinfo is not None


@pytest.mark.parametrize("cls", ["Boundary Input", "new:", "boundary_input", "x;rm -rf ~"])
def test_append_refuses_a_class_that_is_no_slug(tmp_path, cls):
    out = run(
        tmp_path,
        "append",
        "--repo",
        "r",
        "--pr",
        "1",
        "--round",
        "1",
        "--severity",
        "Blocking",
        "--class",
        cls,
        "--line",
        "x",
    )
    assert out.returncode == 2 and "not a catalog slug" in out.stderr
    assert not (tmp_path / "elenchus" / "findings.jsonl").exists()


def test_checklist_ladder_counts_prs_not_rounds(tmp_path):
    for rnd in (1, 2, 3):
        add(tmp_path, "techne", 5, "boundary-input", rnd=rnd)  # one PR, three rounds
    add(tmp_path, "techne", 6, "vacuous-guard")
    add(tmp_path, "pharos", 7, "vacuous-guard")
    for pr in (8, 9, 10):
        add(tmp_path, "sphragis", pr, "claim-code-drift")
    out = run(tmp_path, "checklist").stdout
    assert "boundary-input" not in out
    assert (
        "- vacuous-guard: 2 PRs" in out
        and "mechanical" not in out.split("vacuous-guard")[1].split("\n")[0]
    )
    assert "- claim-code-drift: 3 PRs" in out and "needs a mechanical check" in out


def test_checklist_ignores_findings_older_than_the_window(tmp_path):
    path = tmp_path / "elenchus" / "findings.jsonl"
    path.parent.mkdir(parents=True)
    old = (dt.datetime.now(dt.UTC) - dt.timedelta(days=9)).isoformat()
    path.write_text(
        "".join(
            json.dumps(
                {"ts": old, "repo": "r", "pr": str(n), "round": 1, "class": "boundary-input"}
            )
            + "\n"
            for n in (1, 2, 3)
        )
        + "not json\n"
    )
    out = run(tmp_path, "checklist")
    assert "no class found" in out.stdout
    assert "skipped 1 malformed" in out.stderr


def test_fold_plan_dedupes_against_the_catalog(tmp_path):
    catalog = tmp_path / "bug-classes.md"
    catalog.write_text(CATALOG)
    add(tmp_path, "techne", 1, "boundary-input")
    add(tmp_path, "techne", 2, "new: boundary-input")  # a `new:` name the catalog has
    add(tmp_path, "techne", 3, "new: lost-lock")
    add(tmp_path, "pharos", 4, "new: lost-lock")
    add(tmp_path, "techne", 5, "new: one-off")
    add(tmp_path, "techne", 6, "vacuous-guard")
    add(tmp_path, "techne", 7, "made-up-slug")
    plan = json.loads(run(tmp_path, "fold", "--catalog", str(catalog)).stdout)
    assert plan["records"] == 7
    assert sorted(i["pr"] for i in plan["incidents"]["boundary-input"]) == ["1", "2"]
    assert list(plan["new_classes"]) == ["lost-lock"]
    assert plan["new_seen_once"] == ["one-off"]
    assert list(plan["unknown_slugs"]) == ["made-up-slug"]
    assert plan["retired_but_found"] == ["vacuous-guard"]


def test_fold_reads_only_since_the_last_fold(tmp_path):
    catalog = tmp_path / "bug-classes.md"
    catalog.write_text(CATALOG)
    add(tmp_path, "techne", 1, "boundary-input")
    later = (dt.datetime.now(dt.UTC) + dt.timedelta(seconds=5)).isoformat()
    plan = json.loads(run(tmp_path, "fold", "--catalog", str(catalog), "--since", later).stdout)
    assert plan["records"] == 0 and plan["incidents"] == {}
