"""Tests for techne:sisters' security floor check (check 17).

Each case builds a git repo with workflow files and a fake `gh` that answers the two
GitHub reads the check makes, and asserts on the one line it prints for the repo.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "plugins" / "techne" / "skills" / "sisters" / "scripts" / "security_floor.py"
SHA = "a" * 40
GOOD = f"""name: ci
on: [push]
permissions:
  contents: read
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@{SHA} # v6
      - run: uvx zizmor .github/workflows/
"""
LOCK_CI = "version: 1\nworkflows:\n  .github/workflows/ci.yml:\n    actions: {}\n"
SA_ON = {
    "secret_scanning": {"status": "enabled"},
    "secret_scanning_push_protection": {"status": "enabled"},
}


def make_repo(tmp_path: Path, workflows: dict[str, str], name: str = "r") -> Path:
    root = tmp_path / name
    (root / ".github" / "workflows").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(
        ["git", "-C", str(root), "remote", "add", "origin", f"git@github.com:aj/{name}.git"],
        check=True,
    )
    for file, text in workflows.items():
        (root / ".github" / "workflows" / file).write_text(text)
    return root


def run(
    tmp_path: Path, repo: Path, *, sa=None, private=False, alerts="204", fail=False, admin=True
) -> str:
    answer = json.dumps(
        {
            "private": private,
            "permissions": {"admin": admin},
            "security_and_analysis": (SA_ON if sa is None else sa) if admin else None,
        }
    )
    fake = tmp_path / "gh"
    fake.write_text(
        "#!/bin/sh\n"
        + ("echo 'HTTP 401: Bad credentials' >&2; exit 1\n" if fail else "")
        + 'case "$*" in\n'
        + f"  *vulnerability-alerts*) printf 'HTTP/2.0 {alerts} X\\n\\n' ;;\n"
        + f"  *) printf '%s' '{answer}' ;;\n"
        + "esac\n"
    )
    fake.chmod(0o755)
    out = subprocess.run(
        [sys.executable, str(SCRIPT), str(repo.parent), repo.name],
        capture_output=True,
        text=True,
        env={**os.environ, "TECHNE_GH": str(fake)},
        check=True,
    )
    return out.stdout.strip()


def test_a_repo_on_the_floor_passes(tmp_path):
    assert run(tmp_path, make_repo(tmp_path, {"ci.yml": GOOD})) == "r: security floor ✓"


@pytest.mark.parametrize(
    "kw,gap",
    [
        ({"sa": {"secret_scanning": {"status": "enabled"}}}, "push protection off"),
        ({"sa": {}}, "secret scanning and push protection off"),
        ({"alerts": "404"}, "Dependabot alerts off"),
    ],
)
def test_github_settings_off_on_a_public_repo_are_gaps(tmp_path, kw, gap):
    out = run(tmp_path, make_repo(tmp_path, {"ci.yml": GOOD}), **kw)
    assert "1 security floor gap:" in out and gap in out


def test_a_private_repo_without_secret_protection_is_the_users_call(tmp_path):
    out = run(tmp_path, make_repo(tmp_path, {"ci.yml": GOOD}), sa={}, private=True)
    assert out.startswith("r: security floor ✓") and "the user's call" in out


def test_settings_that_cannot_be_read_still_check_the_workflows(tmp_path):
    out = run(tmp_path, make_repo(tmp_path, {"ci.yml": GOOD.replace(f"@{SHA}", "@v6")}), fail=True)
    assert "action refs not pinned" in out and "not read (HTTP 401" in out
    assert "not read" in run(tmp_path, make_repo(tmp_path, {"ci.yml": GOOD}, "r2"), alerts="403")


def test_pins_and_the_lockfile(tmp_path):
    loose = GOOD.replace(f"@{SHA}", "@v6")
    out = run(tmp_path, make_repo(tmp_path, {"ci.yml": loose}))
    assert "1 action refs not pinned to a SHA (first: ci.yml: actions/checkout@v6)" in out
    locked = make_repo(
        tmp_path,
        {
            "ci.yml": loose,
            "actions.lock": LOCK_CI,
        },
        "locked",
    )
    assert run(tmp_path, locked) == "locked: security floor ✓"
    reusable = loose + "  call:\n    uses: aj/x/.github/workflows/w.yml@main\n"
    out = run(
        tmp_path,
        make_repo(
            tmp_path,
            {
                "ci.yml": reusable,
                "actions.lock": LOCK_CI,
            },
            "reuse",
        ),
    )
    assert "w.yml@main" in out, "a reusable workflow call needs a SHA even with the lockfile"
    local = GOOD + "      - uses: ./.github/actions/setup\n      - uses: docker://alpine:3\n"
    assert run(tmp_path, make_repo(tmp_path, {"ci.yml": local}, "local")).endswith("✓")


def test_permissions_at_the_top_or_on_every_job(tmp_path):
    per_job = GOOD.replace("permissions:\n  contents: read\n", "").replace(
        "    runs-on:", "    permissions:\n      contents: read\n    runs-on:"
    )
    assert run(tmp_path, make_repo(tmp_path, {"ci.yml": per_job}, "jobs")).endswith("✓")
    second = per_job + "  build:\n    runs-on: ubuntu-latest\n    steps:\n      - run: make\n"
    assert "no permissions: in ci.yml" in run(
        tmp_path, make_repo(tmp_path, {"ci.yml": second}, "two")
    )
    nested = second.replace("      - run: make\n", "      - with:\n          permissions: x\n")
    assert "no permissions: in ci.yml" in run(
        tmp_path, make_repo(tmp_path, {"ci.yml": nested}, "deep")
    )
    wide = GOOD.replace("permissions:\n  contents: read\n", "permissions: write-all\n")
    assert "write-all in ci.yml" in run(tmp_path, make_repo(tmp_path, {"ci.yml": wide}, "wide"))


def test_no_zizmor_and_no_workflows(tmp_path):
    out = run(tmp_path, make_repo(tmp_path, {"ci.yml": GOOD.replace("zizmor", "ruff")}))
    assert "no zizmor in CI" in out
    assert run(tmp_path, make_repo(tmp_path, {}, "bare")) == "bare: security floor ✓"


def test_not_a_repo(tmp_path):
    (tmp_path / "plain").mkdir()
    out = subprocess.run(
        [sys.executable, str(SCRIPT), str(tmp_path), "plain"], capture_output=True, text=True
    ).stdout
    assert (
        out.strip() == f"plain: 1 security floor gap: not a git repository at {tmp_path / 'plain'}"
    )


def test_without_admin_access_the_settings_are_not_read_rather_than_off(tmp_path):
    out = run(tmp_path, make_repo(tmp_path, {"ci.yml": GOOD}), admin=False, alerts="404")
    assert out == "r: security floor ✓ (GitHub settings not read (needs admin access))"


def test_a_job_with_write_all_is_a_gap_under_a_read_only_top(tmp_path):
    job = GOOD.replace("    runs-on:", "    permissions: write-all\n    runs-on:")
    assert "write-all in ci.yml" in run(tmp_path, make_repo(tmp_path, {"ci.yml": job}))
    note = GOOD.replace(
        "permissions:\n  contents: read\n", "permissions: read-all # never write-all\n"
    )
    assert run(tmp_path, make_repo(tmp_path, {"ci.yml": note}, "note")).endswith("✓")


def test_the_lockfile_covers_only_the_workflows_it_names(tmp_path):
    loose = GOOD.replace(f"@{SHA}", "@v6")
    files = {
        "ci.yml": loose,
        "docs.yml": loose,
        "actions.lock": "workflows:\n  '.github/workflows/ci.yml':\n    actions: {}\n",
    }
    out = run(tmp_path, make_repo(tmp_path, files))
    assert "1 action refs not pinned" in out and "docs.yml" in out


def test_a_composite_actions_uses_are_pinned_too(tmp_path):
    repo = make_repo(tmp_path, {"ci.yml": GOOD})
    action = repo / ".github" / "actions" / "setup" / "action.yml"
    action.parent.mkdir(parents=True)
    action.write_text("runs:\n  using: composite\n  steps:\n    - uses: astral-sh/setup-uv@v6\n")
    assert "action.yml: astral-sh/setup-uv@v6" in run(tmp_path, repo)


def test_zizmor_named_only_in_a_comment_does_not_count(tmp_path):
    text = GOOD.replace("      - run: uvx zizmor .github/workflows/\n", "      # TODO add zizmor\n")
    assert "no zizmor in CI" in run(tmp_path, make_repo(tmp_path, {"ci.yml": text}))
    action = GOOD.replace(
        "      - run: uvx zizmor .github/workflows/\n",
        f"      - uses: zizmorcore/zizmor-action@{SHA}\n",
    )
    assert run(tmp_path, make_repo(tmp_path, {"ci.yml": action}, "act")).endswith("✓")


def test_an_unreadable_workflow_is_reported_not_a_crash(tmp_path):
    repo = make_repo(tmp_path, {"ci.yml": GOOD})
    broken = repo / ".github" / "workflows" / "broken.yml"
    broken.write_text(GOOD)
    broken.chmod(0)
    assert "could not read broken.yml" in run(tmp_path, repo)


def test_the_lockfile_names_a_workflow_exactly(tmp_path):
    loose = GOOD.replace(f"@{SHA}", "@v6")
    lock = "workflows:\n  .github/workflows/my-ci.yml:\n    x: 1\n# TODO onboard ci.yml\n"
    files = {"ci.yml": loose, "my-ci.yml": loose, "actions.lock": lock}
    out = run(tmp_path, make_repo(tmp_path, files))
    assert "1 action refs not pinned" in out and "ci.yml: actions/checkout@v6" in out


@pytest.mark.parametrize(
    "step,counts",
    [
        ("      - run: |\n          uvx zizmor .\n", True),
        ("      - run: make zizmor\n", True),
        ("      - run: echo 'add zizmor later'\n", False),
        ("      - name: zizmor someday\n        run: make lint\n", False),
    ],
)
def test_zizmor_counts_only_when_a_step_runs_it(tmp_path, step, counts):
    text = GOOD.replace("      - run: uvx zizmor .github/workflows/\n", step)
    out = run(tmp_path, make_repo(tmp_path, {"ci.yml": text}))
    assert ("no zizmor in CI" not in out) == counts, out
