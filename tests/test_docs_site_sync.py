"""docs-site sync_shared.py: where each shared file lands, and what --check reports."""

import subprocess
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1] / "plugins" / "techne" / "skills" / "docs-site"
SYNC = SKILL / "scripts" / "sync_shared.py"
SHARED = SKILL / "templates" / "shared"


def run(*args: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, SYNC, *map(str, args)], capture_output=True, text=True, check=False
    )


def site(tmp_path: Path, *, unit: bool = True, pytest: bool = True, prune: bool = False) -> Path:
    repo = tmp_path / "site"
    (repo / "docs").mkdir(parents=True)
    (repo / "zensical.toml").write_text('[project]\nnav = [{ "Home" = "index.md" }]\n')
    (repo / "tests" / "unit" if unit else repo / "tests").mkdir(parents=True)
    (repo / "pyproject.toml").write_text(
        '[dependency-groups]\ndev = ["pytest"]\n' if pytest else ""
    )
    if prune:
        (repo / "scripts").mkdir()
        (repo / "scripts" / "prune_site.py").write_text("")
    return repo


def test_sync_writes_every_shared_file_where_the_site_expects_it(tmp_path: Path) -> None:
    repo = site(tmp_path)
    assert run(repo).returncode == 0
    for rel in (
        "overrides/main.html",
        "overrides/partials/copyright.html",
        "docs/javascripts/reveal.js",
    ):
        assert (repo / rel).read_bytes() == (SHARED / rel).read_bytes()
    assert (repo / "tests/unit/test_docs_nav.py").read_bytes() == (
        SHARED / "tests/test_docs_nav.py"
    ).read_bytes()
    assert not (repo / "tests/test_docs_nav.py").exists()


def test_nav_test_goes_to_tests_without_a_unit_dir(tmp_path: Path) -> None:
    repo = site(tmp_path, unit=False)
    run(repo)
    assert (repo / "tests/test_docs_nav.py").is_file()


def test_nav_test_is_skipped_where_it_cannot_run_or_is_not_needed(tmp_path: Path) -> None:
    no_pytest = site(tmp_path / "a", pytest=False)
    pruned = site(tmp_path / "b", prune=True)
    run(no_pytest, pruned)
    assert not list(no_pytest.glob("tests/**/test_docs_nav.py"))
    assert not list(pruned.glob("tests/**/test_docs_nav.py"))
    assert (pruned / "overrides/main.html").is_file()


def test_check_reports_drift_and_writes_nothing(tmp_path: Path) -> None:
    repo = site(tmp_path)
    missing = run("--check", repo)
    assert missing.returncode == 1
    assert "overrides/main.html missing" in missing.stdout
    assert not (repo / "overrides").exists()

    run(repo)
    assert run("--check", repo).returncode == 0

    (repo / "docs/javascripts/reveal.js").write_text("// edited in the site\n")
    drifted = run("--check", repo)
    assert drifted.returncode == 1
    assert "docs/javascripts/reveal.js differs" in drifted.stdout
    assert (repo / "docs/javascripts/reveal.js").read_text() == "// edited in the site\n"


def test_a_repo_without_zensical_is_skipped(tmp_path: Path) -> None:
    (tmp_path / "plain").mkdir()
    result = run("--check", tmp_path / "plain")
    assert result.returncode == 0
    assert "no zensical.toml" in result.stdout
