"""foldback.sh's window: it waits on an open fold PR, moves only when a fold PR merged, and
writes nothing on a dry run. A stub gh and a local repo stand in for GitHub; the ledger is
empty, so no curation session starts."""

from __future__ import annotations

import json
import os
import pathlib
import subprocess

import pytest
from conftest import ROOT

FOLDBACK = ROOT / "plugins" / "techne" / "skills" / "elenchus" / "scripts" / "foldback.sh"
CATALOG = "plugins/techne/skills/elenchus/references/bug-classes.md"
OLD = "2026-10-01T00:00:00+00:00"
PENDING_UNTIL = "2026-10-20T00:00:00+00:00"

GH = r"""#!/bin/bash
# A stand-in for gh: prints what the real one would print after its --jq filter.
case "$1 $2" in
"pr list") echo "${STUB_OPEN:-0}" ;;
"pr view")
    [ -n "${STUB_FAIL:-}" ] && { echo "gh: could not resolve" >&2; exit 1; }
    echo "${STUB_STATE:-MERGED}" ;;
"issue list") echo 0 ;;
"repo list") echo "techne, pharos" ;;
"api -X") ;;
*) echo "unexpected gh $*" >&2; exit 9 ;;
esac
"""


def git(cwd: pathlib.Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def world(tmp_path):
    origin = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    (seed / CATALOG).parent.mkdir(parents=True)
    (seed / CATALOG).write_text("<!-- budget: 100 words -->\n# Catalog\n")
    git(seed.parent, "init", "-q", "-b", "main", str(seed))
    git(seed, "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
    git(seed, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "seed")
    git(tmp_path, "clone", "-q", "--bare", str(seed), str(origin))
    repo = tmp_path / "techne"
    git(tmp_path, "clone", "-q", str(origin), str(repo))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "gh").write_text(GH)
    (bin_dir / "gh").chmod(0o755)
    state = tmp_path / "state"
    return {"repo": repo, "bin": bin_dir, "state": state, "dir": state / "elenchus"}


def run(world, **env) -> subprocess.CompletedProcess:
    full = {
        **{k: v for k, v in os.environ.items() if not k.startswith(("STUB_", "ELENCHUS_"))},
        "PATH": f"{world['bin']}:{os.environ['PATH']}",
        "XDG_STATE_HOME": str(world["state"]),
        **env,
    }
    return subprocess.run(
        ["bash", str(FOLDBACK), str(world["repo"])],
        env=full,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def seed_state(world, pending: str | None = None) -> None:
    world["dir"].mkdir(parents=True, exist_ok=True)
    (world["dir"] / "last-fold").write_text(OLD + "\n")
    if pending is not None:
        (world["dir"] / "pending").write_text(pending)


def log(world) -> str:
    return (world["dir"] / "foldback.log").read_text()


def plan_since(world) -> str:
    (plan,) = world["dir"].glob("plan-*.json")
    return json.loads(plan.read_text())["since"]


def test_an_open_fold_pr_holds_the_window(world):
    seed_state(world, f"{PENDING_UNTIL} chore/catalog-fold-2026-10-20\n")
    assert run(world, STUB_OPEN="1").returncode == 0
    assert (world["dir"] / "last-fold").read_text().strip() == OLD
    assert (world["dir"] / "pending").exists()
    assert "still open" in log(world)


def test_a_merged_fold_pr_moves_the_window_to_its_end(world):
    seed_state(world, f"{PENDING_UNTIL} chore/catalog-fold-2026-10-20\n")
    assert run(world, STUB_STATE="MERGED").returncode == 0, log(world)
    assert plan_since(world) == PENDING_UNTIL
    assert not (world["dir"] / "pending").exists()


def test_a_fold_pr_closed_unmerged_keeps_the_window(world):
    seed_state(world, f"{PENDING_UNTIL} chore/catalog-fold-2026-10-20\n")
    assert run(world, STUB_STATE="CLOSED").returncode == 0, log(world)
    assert plan_since(world) == OLD  # its findings are read again


def test_a_dry_run_writes_nothing(world):
    seed_state(world, f"{PENDING_UNTIL} chore/catalog-fold-2026-10-20\n")
    assert run(world, STUB_STATE="MERGED", ELENCHUS_DRY_RUN="1").returncode == 0, log(world)
    assert (world["dir"] / "last-fold").read_text().strip() == OLD
    assert (world["dir"] / "pending").exists()


@pytest.mark.parametrize(
    ("pending", "env", "message"),
    [
        (f"{PENDING_UNTIL} chore/catalog-fold-2026-10-20\n", {"STUB_FAIL": "1"}, "pending kept"),
        ("", {}, "empty or damaged"),
    ],
)
def test_an_unreadable_pending_fold_stops_and_keeps_state(world, pending, env, message):
    seed_state(world, pending)
    assert run(world, **env).returncode == 1
    assert (world["dir"] / "pending").exists()
    assert (world["dir"] / "last-fold").read_text().strip() == OLD
    assert message in log(world)


def test_a_second_run_waits_for_the_first(world):
    seed_state(world)
    lock = world["dir"] / "foldback.lock"
    with lock.open("w") as fh:
        held = subprocess.Popen(["flock", "-x", str(lock), "sleep", "5"])
        try:
            import time

            time.sleep(0.5)
            assert run(world).returncode == 0
            assert "another fold-back is running" in log(world)
        finally:
            held.kill()
            fh.close()
