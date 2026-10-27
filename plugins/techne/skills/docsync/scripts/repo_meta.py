#!/usr/bin/env python3
"""A repo's GitHub About section and its README opening, as JSON, for docsync's metadata check.

Usage: python3 repo_meta.py [path]   (a file or directory inside the repo; default the CWD)

Prints {repo, description, homepage, topics, pages_url, readme, opening, problems}. `opening`
is the README's prose before its first section heading (at most three paragraphs, each with
its line): the title, badges, images, HTML tags, comments, front matter, code, tables,
collapsed <details> and link-only lines are left out, and a tagline heading in the header
(below h2, or inside a centred <div>) is kept. `problems` lists what a rule settles without
reading the code: an empty description, no topics, an unset homepage while a GitHub Pages
site is live, a github.io homepage off that site, a missing README or opening.
Whether the description and opening still match what the repo does is the skill's call.
Exits 2 with the reason on stderr when the folder is not in a git repo, the repo has no
GitHub origin, or GitHub cannot be read (gh's own message is quoted). Runs on python3 3.9.
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
from repo_kind import TIMEOUT, decode, sh  # noqa: E402  # ty: ignore[unresolved-import]

MAX_PARAGRAPHS = 3
# GitHub shows the README from .github/ first, then the root, then docs/ (docs.github.com,
# "About the repository README file").
README_DIRS = (".github", "", "docs")

_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_FRONT_MATTER = re.compile(r"\A---[ \t]*\n.*?\n(?:---|\.\.\.)[ \t]*(?:\n|\Z)", re.DOTALL)
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_ATX = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t#]*$")
_HTML_HEADING = re.compile(r"^ {0,3}<h([1-6])[\s>]", re.IGNORECASE)
_SETEXT = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
_BREAK = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
_TABLE_ROW = re.compile(r"^[ \t]*\|")
_REF_DEFINITION = re.compile(r"^ {0,3}\[[^\]]+\]:[ \t]*\S")
_INDENTED_CODE = re.compile(r"^(?: {4}|\t)")
# Containers a README header is centred in; a heading inside one is a tagline, not a section.
_HERO_OPEN = re.compile(r"<(?:div|p|center|picture)\b", re.IGNORECASE)
_HERO_CLOSE = re.compile(r"</(?:div|p|center|picture)\s*>", re.IGNORECASE)
_DETAILS_OPEN = re.compile(r"<details\b", re.IGNORECASE)
_DETAILS_CLOSE = re.compile(r"</details\s*>", re.IGNORECASE)

_IMAGE = re.compile(r"!\[[^\]]*\](?:\([^)]*\)|\[[^\]]*\])")
_LINK = re.compile(r"\[([^\]]*)\](?:\([^)]*\)|\[[^\]]*\])")
_AUTOLINK = re.compile(r"<((?:https?|mailto):[^<>\s]+)>")
# A tag has its name right after `<`, so `a < b and c > d` stays text.
_TAG = re.compile(r"</?[A-Za-z][A-Za-z0-9-]*(?:\s[^<>]*)?/?>")
_ADMONITION = re.compile(r"\[!(?:NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]", re.IGNORECASE)
_EMPHASIS = re.compile(r"(\*{1,3}|_{2,3})(\S(?:.*?\S)?)\1")
_QUOTE = re.compile(r"^ {0,3}>[ \t]?", re.MULTILINE)


def blank_out(pattern: re.Pattern[str], text: str) -> str:
    """text with each match replaced by its newlines alone, so line numbers hold."""
    return pattern.sub(lambda m: "\n" * m.group(0).count("\n"), text)


def prose(block: str) -> str:
    """A block's readable text: no images, badges, tags, quote markers or link targets."""
    text = _IMAGE.sub("", block)
    text = _LINK.sub(r"\1", text)
    text = _AUTOLINK.sub(r"\1", text)
    text = _QUOTE.sub("", _TAG.sub("", text))
    text = _EMPHASIS.sub(r"\2", _ADMONITION.sub("", text))
    return " ".join(html.unescape(text).split())


def is_lead(block: str, text: str) -> bool:
    """Whether a paragraph says something: letters, more than a label ("Docs:"), and more
    than a row of links ("Docs · Explorer · Paper")."""
    if not any(c.isalpha() for c in text):
        return False
    if len(text.split()) <= 3 and text.endswith(":"):
        return False
    no_images = _IMAGE.sub("", block)
    links = len(_LINK.findall(no_images)) + len(_AUTOLINK.findall(no_images))
    bare = prose(_LINK.sub("", _AUTOLINK.sub("", no_images)))
    return not (links >= 2 and len(re.findall(r"[^\W\d_]{2,}", bare)) <= 3)


def opening(text: str) -> list[dict]:
    """The prose paragraphs before the first section heading, each with its first line."""
    text = text.replace("\r\n", "\n").lstrip("﻿")
    text = blank_out(_FRONT_MATTER, text)
    lines = blank_out(_COMMENT, text).split("\n")
    found: list[dict] = []
    block: list[tuple[int, str]] = []
    fence: tuple[str, int] | None = None
    hero = details = 0

    def close() -> None:
        raw = "\n".join(line for _, line in block)
        body = prose(raw)
        if body and is_lead(raw, body):
            found.append({"line": block[0][0], "text": body})
        block.clear()

    def ends(level: int, number: int, words: str) -> bool:
        """Handle a heading; True when it ends the opening. A title is skipped. Before any
        prose, a heading inside the header container or below h2 is a tagline and kept."""
        close()
        if level == 1:
            return False
        if found:
            return True
        if hero > 0 or level >= 3:
            block.append((number, words))
            close()
            return False
        return True

    index = 0
    while index < len(lines) and len(found) < MAX_PARAGRAPHS:
        line, number = lines[index], index + 1
        following = lines[index + 1] if index + 1 < len(lines) else ""
        index += 1
        mark = _FENCE.match(line)
        if fence is not None:
            # A fence closes on the same character, at least as long, and nothing after it.
            if mark and mark.group(1)[0] == fence[0] and len(mark.group(1)) >= fence[1]:
                fence = None if not line.strip().strip(fence[0]) else fence
            continue
        if mark:
            close()
            fence = (mark.group(1)[0], len(mark.group(1)))
            continue
        details += len(_DETAILS_OPEN.findall(line))
        if details:
            details = max(0, details - len(_DETAILS_CLOSE.findall(line)))
            close()
            continue
        hero = max(0, hero + len(_HERO_OPEN.findall(line)) - len(_HERO_CLOSE.findall(line)))
        atx, tag = _ATX.match(line), _HTML_HEADING.match(line)
        setext = bool(line.strip()) and not block and bool(_SETEXT.match(following))
        if atx or tag or (setext and not _BREAK.match(line)):
            if atx:
                level, words = len(atx.group(1)), atx.group(2) or ""
            elif tag:
                level, words = int(tag.group(1)), line
            else:
                level, words = (1 if following.strip()[0] == "=" else 2), line
                index += 1  # the underline
            if ends(level, number, words):
                break
        elif not line.strip() or _BREAK.match(line):
            close()
        elif _TABLE_ROW.match(line) or _REF_DEFINITION.match(line):
            close()
        elif not (_INDENTED_CODE.match(line) and not block):
            block.append((number, line))
    if len(found) < MAX_PARAGRAPHS:
        close()
    return found


def readme(top: Path) -> Path | None:
    """The README GitHub shows on the repo page, by its own precedence. A link that leaves
    the repo is passed over."""
    root = top.resolve()
    for where in README_DIRS:
        folder = top / where
        if not folder.is_dir():
            continue
        names = sorted(
            p for p in folder.iterdir()
            if (p.name.lower() == "readme" or p.name.lower().startswith("readme."))
            and p.is_file() and p.resolve().is_relative_to(root)
        )  # fmt: skip
        if names:
            return names[0]
    return None


def under(url: str, site: str) -> bool:
    """Whether url is site or a page below it, compared by whole path segments."""
    return (url.rstrip("/") + "/").lower().startswith(site.rstrip("/").lower() + "/")


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
        if not under(homepage, pages):
            out.append(f"homepage: {homepage} is not under the GitHub Pages site {pages}")
    if found is None:
        out.append("readme: none in .github/, the repo root or docs/")
    elif not lead:
        rel = found.relative_to(top).as_posix()
        out.append(f"readme: {rel} has no opening paragraph before its first section heading")
    return out


def stop(message: str) -> int:
    print(f"repo_meta: {message}", file=sys.stderr)
    return 2


def main(argv: list[str]) -> int:
    target = Path(argv[0] if argv else ".").absolute()
    while not target.exists() and target != target.parent:
        target = target.parent
    where = str(target if target.is_dir() else target.parent)
    top = sh("git", "-C", where, "rev-parse", "--show-toplevel")
    if not top:
        return stop(f"{where} is not in a git repository")
    origin = sh("git", "-C", where, "remote", "get-url", "origin")
    slug = github_slug(origin or "")
    if not slug:
        named = origin or "no origin remote"
        return stop(f"{top} has no GitHub origin ({named}), so it has no About section")
    repo = "/".join(slug)
    code, out = doctor_lib.run(
        ("gh", "api", "--hostname", "github.com", f"repos/{repo}"),
        timeout=TIMEOUT,
        env=without_repo_overrides(),
    )
    try:
        info = json.loads(out) if code == 0 else None
    except json.JSONDecodeError:
        info = None
    if not isinstance(info, dict):
        reason = out.strip().splitlines()[-1] if out.strip() else f"gh exited {code}"
        return stop(f"could not read {repo} on GitHub: {reason}")
    pages = sh("gh", "api", "--hostname", "github.com", f"repos/{repo}/pages", "--jq", ".html_url")
    root = Path(top)
    found = readme(root)
    lead = opening(decode(found.read_bytes())) if found else []
    report = {
        "repo": repo,
        "description": info.get("description") or "",
        "homepage": info.get("homepage") or "",
        "topics": list(info.get("topics") or []),
        "pages_url": pages or None,
        "readme": found.relative_to(root).as_posix() if found else None,
        "opening": lead,
        "problems": problems(info, pages or None, found, root, lead),
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
