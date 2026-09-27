"""Copy the shared docs-site files into a Zensical site, or check that its copies match.

    uv run --quiet python sync_shared.py <repo> [<repo> ...]           # write
    uv run --quiet python sync_shared.py --check <repo> [<repo> ...]   # report drift, exit 1

The canonical files live in ../templates/shared/, laid out as they sit in a site. The nav
test goes to tests/unit/ when the repo has it, else tests/; it is skipped in a repo with no
pytest suite, and in one whose build prunes unlisted pages (scripts/prune_site.py), where an
unlisted page never deploys.
"""

from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from pathlib import Path

SHARED = Path(__file__).resolve().parents[1] / "templates" / "shared"
NAV_TEST = Path("tests") / "test_docs_nav.py"


def destination(repo: Path, rel: Path) -> Path | None:
    """Where a shared file goes in this repo, or None when it does not apply."""
    if rel != NAV_TEST:
        return repo / rel
    if not (repo / "tests").is_dir() or (repo / "scripts" / "prune_site.py").is_file():
        return None
    pyproject = repo / "pyproject.toml"
    if not pyproject.is_file() or "pytest" not in pyproject.read_text():
        return None
    unit = repo / "tests" / "unit"
    return (unit if unit.is_dir() else repo / "tests") / rel.name


def plan(repo: Path) -> list[tuple[Path, Path]]:
    pairs = []
    for src in sorted(p for p in SHARED.rglob("*") if p.is_file()):
        dest = destination(repo, src.relative_to(SHARED))
        if dest is not None:
            pairs.append((src, dest))
    return pairs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("repos", nargs="+", type=Path)
    parser.add_argument("--check", action="store_true", help="report drift, write nothing")
    args = parser.parse_args()

    drift = 0
    for repo in (r.resolve() for r in args.repos):
        if not (repo / "zensical.toml").is_file():
            print(f"{repo}: no zensical.toml, skipped")
            continue
        for src, dest in plan(repo):
            rel = dest.relative_to(repo)
            if dest.is_file() and filecmp.cmp(src, dest, shallow=False):
                continue
            state = "differs" if dest.is_file() else "missing"
            if args.check:
                drift += 1
                print(f"{repo.name}: {rel} {state}")
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, dest)
                print(f"{repo.name}: {rel} {'updated' if state == 'differs' else 'added'}")
    if args.check and not drift:
        print("shared docs-site files match")
    return 1 if drift else 0


if __name__ == "__main__":
    sys.exit(main())
