#!/usr/bin/env python3
"""Paper search over OpenAlex, Semantic Scholar and arXiv, shared by graphe:paper-review and
heuresis. Standard library only, Python 3.11 or newer.

Usage: scholarly.py {openalex,s2,arxiv,arxiv-id,crossref} QUERY [--limit N] [--semantic]
arxiv-id takes comma-separated arXiv ids; crossref takes a DOI. Both print the title, authors
and year to compare against a bibliography entry.
Keys: OPENALEX_API_KEY (optional, raises the daily budget), S2_API_KEY (required for s2).
OPENALEX_MAILTO (optional) is sent as `mailto` to OpenAlex and Crossref, never in the User-Agent.
Requests are paced per host across processes by polite_http.py, which sits beside this file.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import polite_http

TOOL = "techne-scholarly"
ATOM = "{http://www.w3.org/2005/Atom}"
OPENALEX_SELECT = "id,doi,title,publication_year,abstract_inverted_index,primary_location"

Fetch = Callable[[str, dict[str, str]], bytes]


class ScholarlyError(Exception):
    """A source answered with something other than a usable result."""


def _get(url: str, headers: dict[str, str]) -> bytes:
    """One paced GET: see polite_http for the per-host interval, retries and User-Agent."""
    try:
        return polite_http.fetch(
            url, tool=TOOL, headers=headers, mailto=os.environ.get("OPENALEX_MAILTO") or None
        )
    except polite_http.PoliteError as exc:
        raise ScholarlyError(str(exc)) from exc


def _json(body: bytes) -> dict:
    try:
        data = json.loads(body)
    except ValueError as exc:
        raise ScholarlyError("response was not JSON") from exc
    if not isinstance(data, dict):
        raise ScholarlyError("response JSON was not an object")
    return data


def reconstruct_abstract(index: dict[str, list[int]] | None) -> str:
    if not index:
        return ""
    words = sorted((pos, word) for word, positions in index.items() for pos in positions)
    return " ".join(word for _, word in words)


def arxiv_lookup(ids: list[str], *, fetch: Fetch = _get) -> list[dict]:
    """Resolve arXiv ids in one request: id, title, authors, year, abstract per entry found."""
    wanted = ",".join(urllib.parse.quote(i.strip()) for i in ids if i.strip())
    url = f"https://export.arxiv.org/api/query?id_list={wanted}&max_results={max(len(ids), 1)}"
    try:
        root = ET.fromstring(fetch(url, {}))
    except ET.ParseError as exc:
        raise ScholarlyError("arXiv response was not Atom XML") from exc
    out = []
    for entry in root.findall(f"{ATOM}entry"):
        link = entry.findtext(f"{ATOM}id", "")
        out.append(
            {
                "id": link.rsplit("/abs/", 1)[-1],
                "title": " ".join(entry.findtext(f"{ATOM}title", "").split()),
                "authors": [
                    " ".join(a.findtext(f"{ATOM}name", "").split())
                    for a in entry.findall(f"{ATOM}author")
                ],
                "year": entry.findtext(f"{ATOM}published", "")[:4],
                "abstract": " ".join(entry.findtext(f"{ATOM}summary", "").split()),
            }
        )
    return out


def crossref_lookup(doi: str, *, mailto: str | None = None, fetch: Fetch = _get) -> dict:
    """Resolve a DOI at Crossref: title, authors, year, venue. No redirect to a publisher page."""
    doi = doi.strip().removeprefix("https://doi.org/")
    url = "https://api.crossref.org/works/" + urllib.parse.quote(doi)
    if mailto:
        url += "?" + urllib.parse.urlencode({"mailto": mailto})
    message = _json(fetch(url, {})).get("message")
    if not isinstance(message, dict):
        raise ScholarlyError("Crossref response had no message")
    issued = ((message.get("issued") or {}).get("date-parts") or [[None]])[0]
    return {
        "doi": doi,
        "title": " ".join((message.get("title") or [""])[0].split()),
        "authors": [
            " ".join(filter(None, [a.get("given"), a.get("family")]))
            for a in message.get("author") or []
        ],
        "year": str(issued[0] or "") if issued else "",
        "venue": " ".join((message.get("container-title") or [""])[0].split()),
    }


def _record(title, url, source, date, text, evidence_url, doi) -> dict:
    return {
        "title": (title or "").strip(),
        "url": url or "",
        "source": source,
        "date": str(date or ""),
        "text": (text or "").strip(),
        "evidence_url": evidence_url or "",
        "doi": (doi or "").removeprefix("https://doi.org/"),
    }


def openalex_search(
    query: str,
    *,
    limit: int = 8,
    semantic: bool = False,
    api_key: str | None = None,
    mailto: str | None = None,
    fetch: Fetch = _get,
) -> list[dict]:
    # A comma separates OpenAlex filters, so one inside the query is answered with HTTP 400.
    query = " ".join(query.replace(",", " ").split())
    params = {"per-page": str(limit), "select": OPENALEX_SELECT}
    if semantic:
        params["search.semantic"] = query
    else:
        # title_and_abstract.search ANDs its terms: keep queries to 3-4 high-signal words.
        params["filter"] = f"title_and_abstract.search:{query}"
        params["sort"] = "relevance_score:desc"
    if api_key:
        params["api_key"] = api_key
    if mailto:
        params["mailto"] = mailto
    url = "https://api.openalex.org/works?" + urllib.parse.urlencode(
        params, quote_via=urllib.parse.quote, safe=":,"
    )
    data = _json(fetch(url, {}))
    out = []
    for work in data.get("results", []):
        work_id = str(work.get("id", "")).rsplit("/", 1)[-1]
        location = work.get("primary_location") or {}
        link = location.get("landing_page_url") or work.get("doi") or work.get("id")
        out.append(
            _record(
                work.get("title"),
                link,
                "openalex",
                work.get("publication_year"),
                reconstruct_abstract(work.get("abstract_inverted_index")),
                f"https://api.openalex.org/works/{work_id}?select=title,abstract_inverted_index",
                work.get("doi"),
            )
        )
    return out


def openalex_work(work_id: str, *, api_key: str | None = None, fetch: Fetch = _get) -> dict:
    params = {"select": "title,abstract_inverted_index"}
    if api_key:
        params["api_key"] = api_key
    url = f"https://api.openalex.org/works/{work_id}?" + urllib.parse.urlencode(params)
    return _json(fetch(url, {}))


def s2_search(query: str, *, api_key: str, limit: int = 8, fetch: Fetch = _get) -> list[dict]:
    params = {"query": query, "limit": str(limit), "fields": "title,year,abstract,url,externalIds"}
    url = "https://api.semanticscholar.org/graph/v1/paper/search?" + urllib.parse.urlencode(params)
    data = _json(fetch(url, {"x-api-key": api_key}))
    out = []
    for paper in data.get("data", []):
        pid = paper.get("paperId", "")
        out.append(
            _record(
                paper.get("title"),
                paper.get("url") or f"https://www.semanticscholar.org/paper/{pid}",
                "semantic_scholar",
                paper.get("year"),
                paper.get("abstract"),
                f"https://api.semanticscholar.org/graph/v1/paper/{pid}?fields=title,abstract",
                (paper.get("externalIds") or {}).get("DOI"),
            )
        )
    return out


def arxiv_search(query: str, *, limit: int = 8, fetch: Fetch = _get) -> list[dict]:
    terms = urllib.parse.quote(f'"{query}"')
    url = f"https://export.arxiv.org/api/query?search_query=all:{terms}&max_results={limit}"
    try:
        root = ET.fromstring(fetch(url, {}))
    except ET.ParseError as exc:
        raise ScholarlyError("arXiv response was not Atom XML") from exc
    out = []
    for entry in root.findall(f"{ATOM}entry"):
        link = entry.findtext(f"{ATOM}id", "")
        arxiv_id = link.rsplit("/abs/", 1)[-1]
        out.append(
            _record(
                " ".join(entry.findtext(f"{ATOM}title", "").split()),
                link,
                "arxiv",
                entry.findtext(f"{ATOM}published", "")[:10],
                " ".join(entry.findtext(f"{ATOM}summary", "").split()),
                f"https://export.arxiv.org/api/query?id_list={arxiv_id}",
                None,
            )
        )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scholarly.py")
    parser.add_argument("source", choices=["openalex", "s2", "arxiv", "arxiv-id", "crossref"])
    parser.add_argument(
        "query", help="a query; comma-separated arXiv ids for arxiv-id; a DOI for crossref"
    )
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--semantic", action="store_true", help="OpenAlex semantic search")
    args = parser.parse_args(argv)
    try:
        if args.source == "openalex":
            records = openalex_search(
                args.query,
                limit=args.limit,
                semantic=args.semantic,
                api_key=os.environ.get("OPENALEX_API_KEY"),
                mailto=os.environ.get("OPENALEX_MAILTO"),
                fetch=_get,
            )
        elif args.source == "s2":
            key = os.environ.get("S2_API_KEY")
            if not key:
                print("S2_API_KEY is not set; keyless S2 returns 429", file=sys.stderr)
                return 2
            records = s2_search(args.query, api_key=key, limit=args.limit, fetch=_get)
        elif args.source == "arxiv-id":
            records = arxiv_lookup(args.query.split(","), fetch=_get)
        elif args.source == "crossref":
            records = [crossref_lookup(args.query, mailto=os.environ.get("OPENALEX_MAILTO"))]
        else:
            records = arxiv_search(args.query, limit=args.limit, fetch=_get)
    except ScholarlyError as exc:
        print(f"{args.source}: {exc}", file=sys.stderr)
        return 1
    for record in records:
        print(json.dumps(record, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
