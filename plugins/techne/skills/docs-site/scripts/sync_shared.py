"""Copy the shared docs-site files into a Zensical site, or check that its copies match.

    python3 sync_shared.py <repo> [<repo> ...]           # write
    python3 sync_shared.py --check <repo> [<repo> ...]   # report drift, exit 1

Standard library only, so it runs with any python3 >= 3.10 without the repo's environment.
The canonical files live in ../templates/shared/, laid out as they sit in a site. The nav
test goes to tests/unit/ when the repo has it, else tests/; it is skipped in a repo with no
pytest suite, and in one whose build prunes unlisted pages (scripts/prune_site.py), where an
unlisted page never deploys.

Every shared file names techne as its canonical home, and a sync only replaces a file that
does: a site's own hand-written version is refused unless --force is given, so its
features are moved into config (extra.og_image, extra.brand_mark) or its own files first.
"""

from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from pathlib import Path

SHARED = Path(__file__).resolve().parents[1] / "templates" / "shared"
NAV_TEST = Path("tests") / "test_docs_nav.py"
FILES = (
    Path("overrides") / "main.html",
    Path("overrides") / "partials" / "copyright.html",
    Path("docs") / "javascripts" / "reveal.js",
    NAV_TEST,
)
MARKER = "canonical copy is in techne"


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
    for rel in FILES:
        dest = destination(repo, rel)
        if dest is not None:
            pairs.append((SHARED / rel, dest))
    return pairs


def is_synced_copy(path: Path) -> bool:
    return MARKER in " ".join(path.read_text(errors="replace").lower().split())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("repos", nargs="+", type=Path)
    parser.add_argument("--check", action="store_true", help="report drift, write nothing")
    parser.add_argument(
        "--force", action="store_true", help="also replace a site's own hand-written version"
    )
    args = parser.parse_args()

    drift = 0
    for repo in (r.resolve() for r in args.repos):
        if not (repo / "zensical.toml").is_file():
            print(f"{repo}: no zensical.toml, skipped")
            continue
        for src, dest in plan(repo):
            rel = dest.relative_to(repo)
            if dest.is_symlink():
                drift += 1
                print(f"{repo.name}: {rel} is a symlink, refused")
                continue
            if dest.is_file() and filecmp.cmp(src, dest, shallow=False):
                continue
            state = "differs" if dest.is_file() else "missing"
            if args.check:
                drift += 1
                print(f"{repo.name}: {rel} {state}")
            elif state == "differs" and not args.force and not is_synced_copy(dest):
                drift += 1
                print(
                    f"{repo.name}: {rel} is the site's own version, refused (--force replaces it)"
                )
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, dest)
                print(f"{repo.name}: {rel} {'updated' if state == 'differs' else 'added'}")
    if args.check and not drift:
        print("shared docs-site files match")
    return 1 if drift else 0


if __name__ == "__main__":
    sys.exit(main())
