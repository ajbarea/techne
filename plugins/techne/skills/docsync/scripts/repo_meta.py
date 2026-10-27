#!/usr/bin/env python3
"""A repo's GitHub About section and its README opening, as JSON, for docsync's metadata check.

Usage: python3 repo_meta.py [path]   (a file or directory inside the repo; default the CWD)

Prints {repo, description, homepage, topics, pages_url, readme, opening, problems}. `opening`
is the README's prose paragraphs before its first section heading (at most three, each with its
line), with the hero images, badges, HTML tags and comments taken out. `problems` lists what a
rule settles without reading the code: an empty description, no topics, an unset homepage while
a GitHub Pages site is live, a github.io homepage off that site, a missing README or opening.
Whether the description and opening still match what the repo does is the skill's call.
Exits 2 with the reason on stderr when the repo has no GitHub origin or GitHub cannot be read.
Runs on python3 3.9.
"""

from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # the plugin cache stays as installed
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "_shared"))
import doctor_lib  # noqa: E402  # ty: ignore[unresolved-import]
from git_env import github_slug, without_repo_overrides  # noqa: E402  # ty: ignore[unresolved-import]

TIMEOUT = 15
MAX_PARAGRAPHS = 3
# GitHub shows the README from .github/ first, then the root, then docs/ (docs.github.com,
# "About the repository README file").
README_DIRS = (".github", "", "docs")

_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_FENCE = re.compile(r"^ {0,3}(```|~~~)")
_SECTION = re.compile(r"^ {0,3}(#{2,6}\s|<h[2-6][\s>])", re.IGNORECASE)
_TITLE = re.compile(r"^ {0,3}#\s.*$|<h1[\s>].*?</h1>", re.IGNORECASE | re.DOTALL | re.MULTILINE)
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)|!\[[^\]]*\]\[[^\]]*\]")
_EMPTY_LINK = re.compile(r"\[\s*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_TAG = re.compile(r"<[^>]+>")
_QUOTE = re.compile(r"^ {0,3}>[ \t]?", re.MULTILINE)


def sh(*args: str) -> str | None:
    """stdout of a command, or None when it fails, times out or is missing."""
    code, out = doctor_lib.run(
        args, timeout=TIMEOUT, merge_stderr=False, env=without_repo_overrides()
    )
    return out.strip() if code == 0 else None


def blank_out(pattern: re.Pattern[str], text: str) -> str:
    """text with each match replaced by its newlines alone, so line numbers hold."""
    return pattern.sub(lambda m: "\n" * m.group(0).count("\n"), text)


def prose(block: str) -> str:
    """A block's readable text: no title, images, badges, tags, quote markers or link targets."""
    text = _TITLE.sub("", block)
    text = _IMAGE.sub("", text)
    text = _EMPTY_LINK.sub("", text)
    text = _LINK.sub(r"\1", text)
    text = _QUOTE.sub("", _TAG.sub("", text))
    return " ".join(html.unescape(text).split())


def opening(text: str) -> list[dict]:
    """The prose paragraphs before the first section heading, each with its first line."""
    lines = blank_out(_COMMENT, text).splitlines()
    found: list[dict] = []
    block: list[tuple[int, str]] = []
    fenced = False

    def close() -> None:
        body = prose("\n".join(line for _, line in block))
        if body and any(c.isalpha() for c in body):
            found.append({"line": next(n for n, line in block if line.strip()), "text": body})
        block.clear()

    for number, line in enumerate(lines, 1):
        if _FENCE.match(line):
            close()
            fenced = not fenced
            continue
        if fenced:
            continue
        if _SECTION.match(line):
            break
        if line.strip():
            block.append((number, line))
        else:
            close()
        if len(found) >= MAX_PARAGRAPHS:
            break
    if len(found) < MAX_PARAGRAPHS and not fenced:
        close()
    return found[:MAX_PARAGRAPHS]


def readme(top: Path) -> Path | None:
    """The README GitHub shows on the repo page, by its own precedence."""
    for where in README_DIRS:
        folder = top / where
        if not folder.is_dir():
            continue
        names = sorted(
            p for p in folder.iterdir()
            if p.is_file() and (p.name.lower() == "readme" or p.name.lower().startswith("readme."))
        )  # fmt: skip
        if names:
            return names[0]
    return None


def problems(info: dict, pages: str | None, found: Path | None, top: Path, lead: list) -> list[str]:
    out = []
    if not (info.get("description") or "").strip():
        out.append("description: empty")
    if not info.get("topics"):
        out.append("topics: none set")
    homepage = (info.get("homepage") or "").strip()
    if pages and not homepage:
        out.append(f"homepage: empty while GitHub Pages serves {pages}")
    elif pages and re.match(r"https?://[^/]+\.github\.io(/|$)", homepage, re.IGNORECASE):
        if not homepage.rstrip("/").lower().startswith(pages.rstrip("/").lower()):
            out.append(f"homepage: {homepage} is not under the GitHub Pages site {pages}")
    if found is None:
        out.append("readme: none in .github/, the repo root or docs/")
    elif not lead:
        rel = found.relative_to(top).as_posix()
        out.append(f"readme: {rel} has no opening paragraph before its first section heading")
    return out


def main(argv: list[str]) -> int:
    target = Path(argv[0] if argv else ".").absolute()
    while not target.exists() and target != target.parent:
        target = target.parent
    where = str(target if target.is_dir() else target.parent)
    top = sh("git", "-C", where, "rev-parse", "--show-toplevel")
    slug = github_slug(sh("git", "-C", where, "remote", "get-url", "origin") or "") if top else None
    if not top or not slug:
        print(
            f"repo_meta: {where} has no GitHub origin, so there is no About section",
            file=sys.stderr,
        )
        return 2
    repo = "/".join(slug)
    api = ("gh", "api", "--hostname", "github.com")
    try:
        info = json.loads(sh(*api, f"repos/{repo}") or "null")
    except json.JSONDecodeError:
        info = None
    if not isinstance(info, dict):
        print(f"repo_meta: could not read {repo} on GitHub (is gh signed in?)", file=sys.stderr)
        return 2
    pages = sh(*api, f"repos/{repo}/pages", "--jq", ".html_url") or None
    root = Path(top)
    found = readme(root)
    lead = opening(found.read_text(encoding="utf-8", errors="replace")) if found else []
    report = {
        "repo": repo,
        "description": info.get("description") or "",
        "homepage": info.get("homepage") or "",
        "topics": list(info.get("topics") or []),
        "pages_url": pages,
        "readme": found.relative_to(root).as_posix() if found else None,
        "opening": lead,
        "problems": problems(info, pages, found, root, lead),
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
