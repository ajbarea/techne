#!/usr/bin/env python3
"""Check each sister's citation metadata against the citation convention (check 18).

Usage:
    citation.py WORKSPACE REPO [REPO ...]

Applies to a sister with Zenodo on: a Zenodo webhook on the GitHub repo, or a
Zenodo DOI in its README or CITATION.cff. Such a sister keeps one CITATION.cff
and no .zenodo.json (Zenodo ignores CITATION.cff when both exist), and the file
carries:
  - a title "<name>: <tagline>", where <name> is the repo's name or its README
    title, with no trailing period
  - authors given as given-names and family-names, each with an ORCID URL and an
    affiliation; one ORCID carries the same names and affiliation in every sister
  - keywords, each word lowercase unless it is an acronym (two or more capitals)
  - license and repository-code
  - the concept DOI, once the repo has a GitHub release
  - a version, when present, no older than the latest release tag
With a DOI, the live Zenodo record it resolves to must carry the file's title,
creators ("Family, Given" with ORCID and affiliation) and keywords.

Prints one line per sister, `<repo>: citation ✓`, `<repo>: Zenodo off (skipped)`,
or the gaps, with notes in parentheses for what could not be read. Then one line
per ORCID whose names or affiliation differ between sisters. Always exits 0.
PyYAML parses the file; without it, run through `uv run --with pyyaml`.
"""

# research(2026-11): help.zenodo.org/docs/github/describe-software/citation-file (Zenodo reads
# title, version, license, type, abstract, authors with given/family names, affiliation and
# orcid, and keywords; a .zenodo.json makes it ignore CITATION.cff entirely), the CFF 1.2.0
# schema guide (identifiers, concept DOI, repository-code), and DataCite's creator property
# ("Family, Given" with an ORCID name identifier and an affiliation).

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

GH = os.environ.get("TECHNE_GH", "gh")
ZENODO_API = os.environ.get("TECHNE_ZENODO_API", "https://zenodo.org/api").rstrip("/")
ZENODO_DOI = re.compile(r"10\.5281/zenodo\.(\d+)", re.IGNORECASE)
ORCID_URL = re.compile(r"^https://orcid\.org/(\d{4}-\d{4}-\d{4}-\d{3}[\dX])$")
H1 = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)


def gh(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([GH, *args], capture_output=True, text=True, timeout=30)


def slug(root: Path) -> str | None:
    """owner/name of the repo's origin on GitHub."""
    try:
        url = subprocess.run(
            ["git", "-C", str(root), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r"(?:^|[@/])github\.com[:/]([^/]+/[^/]+?)(?:\.git)?/?$", url)
    return m.group(1) if m else None


def read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def github(name: str | None) -> tuple[bool | None, str | None, list[str]]:
    """(Zenodo webhook on, latest release tag, notes); None where it could not be read."""
    if not name:
        return None, None, ["no GitHub origin"]
    notes: list[str] = []
    hook: bool | None = None
    tag: str | None = None
    try:
        hooks = gh("api", f"repos/{name}/hooks", "--jq", "[.[].config.url // empty]")
        if hooks.returncode == 0:
            hook = any("zenodo.org" in u for u in json.loads(hooks.stdout or "[]"))
        else:
            notes.append("webhooks not read (needs admin access)")
        rel = gh("api", f"repos/{name}/releases?per_page=1", "--jq", "[.[].tag_name]")
        if rel.returncode == 0:
            tags = json.loads(rel.stdout or "[]")
            tag = tags[0] if tags else ""
        else:
            notes.append("releases not read")
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        notes.append(f"GitHub not read ({type(exc).__name__})")
    return hook, tag, notes


def version_tuple(v: str) -> tuple[int, ...] | None:
    m = re.fullmatch(r"v?(\d+(?:\.\d+)*)", str(v).strip())
    return tuple(int(x) for x in m.group(1).split(".")) if m else None


def keyword_gaps(keywords: object) -> list[str]:
    if not isinstance(keywords, list) or not keywords:
        return ["no keywords"]
    bad = [
        k
        for k in keywords
        if not isinstance(k, str)
        or not k.strip()
        or any(w != w.lower() and sum(c.isupper() for c in w) < 2 for w in k.split())
    ]
    return [f"keywords not lowercase: {', '.join(map(str, bad))}"] if bad else []


def author_gaps(authors: object) -> tuple[list[str], list[tuple[str, str, str, str]]]:
    """(gaps, [(orcid, given, family, affiliation)]) for the people among the authors."""
    if not isinstance(authors, list) or not authors:
        return ["no authors"], []
    gaps: list[str] = []
    people = []
    for i, a in enumerate(authors, 1):
        if not isinstance(a, dict):
            gaps.append(f"author {i} is not a mapping")
            continue
        if "family-names" not in a and "name" in a:
            continue  # an entity author: Zenodo takes its name as given
        who = f"{a.get('given-names', '?')} {a.get('family-names', '?')}"
        for key in ("given-names", "family-names", "affiliation"):
            if not str(a.get(key) or "").strip():
                gaps.append(f"{who}: no {key}")
        m = ORCID_URL.match(str(a.get("orcid") or ""))
        if not m:
            gaps.append(f"{who}: no ORCID URL")
        else:
            people.append(
                (
                    m.group(1),
                    str(a.get("given-names") or ""),
                    str(a.get("family-names") or ""),
                    str(a.get("affiliation") or ""),
                )
            )
    return gaps, people


def title_gaps(title: object, names: set[str]) -> list[str]:
    if not isinstance(title, str) or not title.strip():
        return ["no title"]
    head, sep, tagline = title.partition(": ")
    if not sep or head.strip().lower() not in names or not tagline.strip():
        return [f'title "{title}" is not "<name>: <tagline>"']
    if title.rstrip().endswith("."):
        return ["title ends with a period"]
    return []


def zenodo_record(record_id: str) -> tuple[dict | None, str | None]:
    """(record, error) for the record a DOI's id resolves to (a concept id gives the latest)."""
    url = f"{ZENODO_API}/records/{record_id}"
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:
            return json.load(resp), None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return None, f"Zenodo record {record_id} not read ({type(exc).__name__})"


def record_gaps(cff: dict, record: dict, record_id: str) -> list[str]:
    meta = record.get("metadata") or {}
    rid = record.get("id", record_id)
    gaps: list[str] = []
    if meta.get("title") != cff.get("title"):
        gaps.append(f'Zenodo {rid} title "{meta.get("title")}" differs')
    want = [
        (
            f"{a.get('family-names')}, {a.get('given-names')}",
            (ORCID_URL.match(str(a.get("orcid") or "")) or [None, None])[1],
            a.get("affiliation"),
        )
        for a in cff.get("authors") or []
        if isinstance(a, dict) and "family-names" in a
    ]
    have = [
        (c.get("name"), c.get("orcid"), c.get("affiliation")) for c in meta.get("creators") or []
    ]
    if want != have:
        shown = "; ".join(f"{n} [{o or 'no ORCID'}, {a or 'no affiliation'}]" for n, o, a in have)
        gaps.append(f"Zenodo {rid} creators differ ({shown})")
    if sorted(meta.get("keywords") or []) != sorted(cff.get("keywords") or []):
        gaps.append(f"Zenodo {rid} keywords differ")
    return gaps


def check(workspace: Path, repo: str) -> tuple[str, list[tuple[str, str, str, str]]]:
    root = workspace / repo
    if not root.is_dir():
        return f"{repo}: not cloned at {root}", []
    cff_text = read(root / "CITATION.cff")
    readme = read(root / "README.md") or ""
    name = slug(root)
    hook, tag, notes = github(name)
    on = hook if hook is not None else bool(ZENODO_DOI.search(readme + (cff_text or "")))
    if not on:
        if hook is None:
            notes.append("treated as off: no Zenodo DOI in README or CITATION.cff")
        return f"{repo}: Zenodo off (skipped){fmt_notes(notes)}", []
    gaps: list[str] = []
    if (root / ".zenodo.json").exists():
        gaps.append(
            ".zenodo.json present (Zenodo then ignores CITATION.cff) → fold it in, delete it"
        )
    if cff_text is None:
        return f"{repo}: 1 citation gap: no CITATION.cff{fmt_notes(notes)}", []
    try:
        import yaml
    except ImportError:
        return f"{repo}: CITATION.cff not parsed (needs PyYAML: uv run --with pyyaml)", []
    try:
        cff = yaml.safe_load(cff_text)
    except yaml.YAMLError as exc:
        return f"{repo}: 1 citation gap: CITATION.cff is not YAML ({type(exc).__name__})", []
    if not isinstance(cff, dict):
        return f"{repo}: 1 citation gap: CITATION.cff is not a mapping", []
    names = {repo.lower(), (name or "").rsplit("/", 1)[-1].lower()}
    h1 = H1.search(readme)
    if h1:
        names.add(re.sub(r"^[^\w]+", "", h1.group(1)).strip().lower())
    gaps += title_gaps(cff.get("title"), names)
    a_gaps, people = author_gaps(cff.get("authors"))
    gaps += a_gaps + keyword_gaps(cff.get("keywords"))
    for key in ("license", "repository-code"):
        if not cff.get(key):
            gaps.append(f"no {key}")
    doi = ZENODO_DOI.search(str(cff.get("doi") or ""))
    if not doi and tag:
        gaps.append("no concept DOI (doi:)")
    elif not doi and tag == "":
        notes.append("no release yet, so no DOI")
    if "version" in cff and tag:
        have, latest = version_tuple(cff["version"]), version_tuple(tag)
        if have and latest and have < latest:
            gaps.append(f"version {cff['version']} older than release {tag}")
    if doi:
        record, err = zenodo_record(doi.group(1))
        if err:
            notes.append(err)
        elif record is not None:
            gaps += record_gaps(cff, record, doi.group(1))
    if not gaps:
        return f"{repo}: citation ✓{fmt_notes(notes)}", people
    label = "citation gap" if len(gaps) == 1 else "citation gaps"
    return f"{repo}: {len(gaps)} {label}: {'; '.join(gaps)}{fmt_notes(notes)}", people


def fmt_notes(notes: list[str]) -> str:
    return f" ({'; '.join(notes)})" if notes else ""


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: citation.py WORKSPACE REPO [REPO ...]", file=sys.stderr)
        return 0
    workspace, repos = Path(argv[0]), argv[1:]
    with ThreadPoolExecutor(max_workers=min(8, len(repos))) as pool:
        results = list(pool.map(lambda r: check(workspace, r), repos))
    seen: dict[str, dict[tuple[str, str, str], list[str]]] = {}
    for repo, (line, people) in zip(repos, results, strict=True):
        print(line)
        for orcid, given, family, affiliation in people:
            seen.setdefault(orcid, {}).setdefault((given, family, affiliation), []).append(repo)
    for orcid, forms in sorted(seen.items()):
        if len(forms) > 1:
            shown = "; ".join(
                f"{g} {f}, {a or 'no affiliation'} in {', '.join(rs)}"
                for (g, f, a), rs in sorted(forms.items())
            )
            print(f"ORCID {orcid}: names or affiliation differ between sisters: {shown}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
