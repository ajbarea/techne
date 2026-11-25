#!/usr/bin/env python3
"""Check each sister's citation metadata against the citation convention (check 18).

Usage:
    citation.py WORKSPACE REPO [REPO ...]

Applies to a sister with Zenodo on: a Zenodo webhook on the GitHub repo, or, when
the webhooks cannot be read, a Zenodo DOI in its README or CITATION.cff. Such a
sister keeps one CITATION.cff and no .zenodo.json (Zenodo ignores CITATION.cff
when both exist), and the file carries:
  - a title "<name>: <tagline>", where <name> is spelled as the repo's name or its
    README title, with no trailing period
  - person authors with given-names and family-names, an ORCID URL with a valid
    checksum and an affiliation; one ORCID carries the same names and
    affiliation in every sister
  - keywords, each word lowercase unless it is an acronym (two or more capitals)
  - license and repository-code
  - the concept DOI, once the repo has a published GitHub release
  - a quoted version, when present, no older than the latest published release
With a DOI, the live Zenodo record it resolves to must exist, must be reached by
the concept DOI rather than a version DOI, and must carry the file's title,
creators ("Family, Given" with ORCID and affiliation) and keywords.

Prints one line per sister: `<repo>: citation ✓`, `<repo>: Zenodo off (skipped)`,
`<repo>: citation not checked (...)` when GitHub could not be read and nothing
local names a Zenodo DOI, or the gaps, with notes in parentheses for what could
not be read. Then one line per ORCID whose names or affiliation differ between
sisters. Always exits 0. PyYAML parses the file; without it, run through
`uv run --with pyyaml`.
"""

# research(2026-11): help.zenodo.org/docs/github/describe-software/citation-file (Zenodo reads
# title, version, license, type, abstract, authors with given/family names, affiliation and
# orcid, and keywords; a .zenodo.json makes it ignore CITATION.cff entirely), the CFF 1.2.0
# schema guide (identifiers, concept DOI, repository-code), DataCite's creator property
# ("Family, Given" with an ORCID name identifier and an affiliation), and ORCID's checksum
# (ISO 7064 11-2, support.orcid.org "Structure of the ORCID Identifier").

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

Person = tuple[str, str, str, str]  # (orcid, given, family, affiliation)


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


def gh_json(what: str, *args: str) -> tuple[object, str | None]:
    """(parsed output, None), or (None, a note naming what failed and why)."""
    try:
        out = gh(*args)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"{what} not read ({type(exc).__name__})"
    if out.returncode:
        lines = out.stderr.strip().splitlines()
        return None, f"{what} not read ({(lines[0] if lines else 'gh failed')[:80]})"
    try:
        return json.loads(out.stdout or "null"), None
    except ValueError:
        return None, f"{what} not read (gh printed no JSON)"


def github(name: str | None) -> tuple[bool | None, str | None, list[str]]:
    """(Zenodo webhook on, latest published release tag or "", notes); None where unread."""
    if not name:
        return None, None, ["no GitHub origin"]
    notes: list[str] = []
    urls, note = gh_json("webhooks", "api", f"repos/{name}/hooks", "--jq", "[.[].config.url]")
    hook = any("zenodo.org" in str(u) for u in urls) if isinstance(urls, list) else None
    notes += [note] if note else []
    tags, note = gh_json(
        "releases",
        "api",
        f"repos/{name}/releases?per_page=30",
        "--jq",
        "[.[] | select(.draft | not) | .tag_name]",
    )
    tag = (str(tags[0]) if tags else "") if isinstance(tags, list) else None
    notes += [note] if note else []
    return hook, tag, notes


def version_tuple(v: object) -> tuple[int, ...] | None:
    m = re.fullmatch(r"v?(\d+(?:\.\d+)*)", str(v).strip())
    return tuple(int(x) for x in m.group(1).split(".")) if m else None


def older(have: tuple[int, ...], latest: tuple[int, ...]) -> bool:
    width = max(len(have), len(latest))
    return have + (0,) * (width - len(have)) < latest + (0,) * (width - len(latest))


def orcid_ok(orcid: str) -> bool:
    """ISO 7064 11-2 check digit, as ORCID computes it."""
    digits = orcid.replace("-", "")
    total = 0
    for d in digits[:-1]:
        total = (total + int(d)) * 2
    check = (12 - total % 11) % 11
    return digits[-1] == ("X" if check == 10 else str(check))


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
    return [f"keywords not lowercase strings: {', '.join(map(str, bad))}"] if bad else []


def author_gaps(authors: object) -> tuple[list[str], list[Person]]:
    """(gaps, people) for the person authors; an entity author needs only a name."""
    if not isinstance(authors, list) or not authors:
        return ["no authors"], []
    gaps: list[str] = []
    people: list[Person] = []
    for i, a in enumerate(authors, 1):
        if not isinstance(a, dict):
            gaps.append(f"author {i} is not a mapping")
            continue
        if "family-names" not in a and "given-names" not in a:
            if not str(a.get("name") or "").strip():
                gaps.append(f"author {i} has no name")
            continue
        who = f"{a.get('given-names', '?')} {a.get('family-names', '?')}"
        for key in ("given-names", "family-names", "affiliation"):
            if not str(a.get(key) or "").strip():
                gaps.append(f"{who}: no {key}")
        m = ORCID_URL.match(str(a.get("orcid") or ""))
        if not m:
            gaps.append(f"{who}: no ORCID URL")
        elif not orcid_ok(m.group(1)):
            gaps.append(f"{who}: ORCID {m.group(1)} fails its checksum")
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
    if not sep or head.strip() not in names or not tagline.strip():
        shown = " or ".join(sorted(names)) or "<name>"
        return [f'title "{title}" is not "<name>: <tagline>" with <name> spelled {shown}']
    if title.rstrip().endswith("."):
        return ["title ends with a period"]
    return []


def zenodo_record(record_id: str) -> tuple[dict | None, str | None, str | None]:
    """(record, gap, note) for the record a DOI's id resolves to (a concept id gives the latest)."""
    url = f"{ZENODO_API}/records/{record_id}"
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:
            record = json.load(resp)
    except urllib.error.HTTPError as exc:
        if exc.code in (404, 410):
            return None, f"DOI 10.5281/zenodo.{record_id} resolves to no Zenodo record", None
        return None, None, f"Zenodo record {record_id} not read (HTTP {exc.code})"
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return None, None, f"Zenodo record {record_id} not read ({type(exc).__name__})"
    if not isinstance(record, dict):
        return None, None, f"Zenodo record {record_id} not read (not a record)"
    return record, None, None


def creator_rows(cff: dict) -> list[tuple[object, object, object]]:
    """(name, orcid, affiliation) per author, in the form Zenodo's API lists creators."""
    rows = []
    for a in cff.get("authors") or []:
        if not isinstance(a, dict):
            continue
        if "family-names" in a or "given-names" in a:
            m = ORCID_URL.match(str(a.get("orcid") or ""))
            name = f"{a.get('family-names', '')}, {a.get('given-names', '')}".strip(", ")
            rows.append((name, m.group(1) if m else None, a.get("affiliation")))
        else:
            rows.append((a.get("name"), None, a.get("affiliation")))
    return rows


def record_gaps(cff: dict, record: dict, record_id: str) -> list[str]:
    meta = record.get("metadata") or {}
    rid = str(record.get("id", record_id))
    concept = str(record.get("conceptrecid") or "")
    gaps: list[str] = []
    if rid == record_id and concept and concept != record_id:
        gaps.append(f"doi is version DOI {record_id}, not the concept DOI 10.5281/zenodo.{concept}")
    if meta.get("title") != cff.get("title"):
        gaps.append(f'Zenodo {rid} title "{meta.get("title")}" differs')
    have = [
        (c.get("name"), c.get("orcid"), c.get("affiliation")) for c in meta.get("creators") or []
    ]
    if creator_rows(cff) != have:
        shown = "; ".join(f"{n} [{o or 'no ORCID'}, {a or 'no affiliation'}]" for n, o, a in have)
        gaps.append(f"Zenodo {rid} creators differ ({shown})")
    want_kw = sorted(map(str, cff.get("keywords") or []))
    if sorted(map(str, meta.get("keywords") or [])) != want_kw:
        gaps.append(f"Zenodo {rid} keywords differ")
    return gaps


def line(repo: str, gaps: list[str], notes: list[str]) -> str:
    tail = f" ({'; '.join(notes)})" if notes else ""
    if not gaps:
        return f"{repo}: citation ✓{tail}"
    label = "citation gap" if len(gaps) == 1 else "citation gaps"
    return f"{repo}: {len(gaps)} {label}: {'; '.join(gaps)}{tail}"


def check(workspace: Path, repo: str) -> tuple[str, list[Person]]:
    root = workspace / repo
    if not root.is_dir():
        return f"{repo}: not cloned at {root}", []
    cff_text = read(root / "CITATION.cff")
    readme = read(root / "README.md") or ""
    name = slug(root)
    hook, tag, notes = github(name)
    doi_seen = bool(ZENODO_DOI.search(readme + (cff_text or "")))
    if hook is False or (hook is None and not doi_seen):
        if hook is None:
            notes.append("no Zenodo DOI in README or CITATION.cff")
            return f"{repo}: citation not checked ({'; '.join(notes)})", []
        return f"{repo}: Zenodo off (skipped)", []
    gaps: list[str] = []
    if (root / ".zenodo.json").exists():
        gaps.append(
            ".zenodo.json present (Zenodo then ignores CITATION.cff) → fold it in, delete it"
        )
    if cff_text is None:
        return line(repo, [*gaps, "no CITATION.cff"], notes), []
    try:
        import yaml
    except ImportError:
        notes.append("CITATION.cff not parsed: needs PyYAML (uv run --with pyyaml)")
        return f"{repo}: citation not checked ({'; '.join(notes)})", []
    try:
        cff = yaml.safe_load(cff_text)
    except yaml.YAMLError as exc:
        return line(repo, [*gaps, f"CITATION.cff is not YAML ({type(exc).__name__})"], notes), []
    if not isinstance(cff, dict):
        return line(repo, [*gaps, "CITATION.cff is not a mapping"], notes), []
    names = {repo, (name or "").rsplit("/", 1)[-1]}
    h1 = H1.search(readme)
    if h1:
        names.add(re.sub(r"^[^\w]+", "", h1.group(1)).strip())
    names.discard("")
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
    if "version" in cff:
        version = cff["version"]
        if isinstance(version, (int, float)):
            gaps.append(f'version {version} is a YAML number; quote it ("{version}")')
        elif tag:
            have, latest = version_tuple(version), version_tuple(tag)
            if have and latest:
                if older(have, latest):
                    gaps.append(f"version {version} older than release {tag}")
            else:
                notes.append(f"version {version} not compared with release {tag}")
    if doi:
        record, gap, note = zenodo_record(doi.group(1))
        gaps += [gap] if gap else []
        notes += [note] if note else []
        if record is not None:
            gaps += record_gaps(cff, record, doi.group(1))
    return line(repo, gaps, notes), people


def safe_check(workspace: Path, repo: str) -> tuple[str, list[Person]]:
    """One sister's failure never stops the others."""
    try:
        return check(workspace, repo)
    except Exception as exc:
        return f"{repo}: citation not checked ({type(exc).__name__}: {str(exc)[:80]})", []


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: citation.py WORKSPACE REPO [REPO ...]", file=sys.stderr)
        return 0
    workspace, repos = Path(argv[0]), argv[1:]
    with ThreadPoolExecutor(max_workers=min(8, len(repos))) as pool:
        results = list(pool.map(lambda r: safe_check(workspace, r), repos))
    seen: dict[str, dict[tuple[str, str, str], list[str]]] = {}
    for repo, (text, people) in zip(repos, results, strict=True):
        print(text)
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
