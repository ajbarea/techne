"""Paper sources over the shared scholarly.py."""

from __future__ import annotations

import importlib.util
import os
import urllib.parse
from pathlib import Path

from heuresis.model import Record
from heuresis.sources import register

_SHARED = Path(__file__).resolve().parents[2] / "_shared" / "scholarly.py"
_spec = importlib.util.spec_from_file_location("scholarly", _SHARED)
assert _spec and _spec.loader
S = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(S)


def _records(rows: list[dict]) -> list[Record]:
    return [Record.from_dict({**row, "kind": "paper"}) for row in rows]


class OpenAlex:
    name, group = "openalex", "papers"

    def available(self) -> tuple[bool, str]:
        return True, ""

    def search(self, query: str, limit: int) -> list[Record]:
        return _records(
            S.openalex_search(
                query,
                limit=limit,
                api_key=os.environ.get("OPENALEX_API_KEY"),
                mailto=os.environ.get("OPENALEX_MAILTO"),
            )
        )

    def evidence(self, record: Record) -> str | None:
        path = urllib.parse.urlsplit(record.evidence_url).path
        work = S.openalex_work(path.rsplit("/", 1)[-1], api_key=os.environ.get("OPENALEX_API_KEY"))
        abstract = S.reconstruct_abstract(work.get("abstract_inverted_index"))
        return f"{work.get('title', '')} {abstract}".strip()


class SemanticScholar:
    name, group = "semantic_scholar", "papers"

    def available(self) -> tuple[bool, str]:
        if os.environ.get("S2_API_KEY"):
            return True, ""
        return False, "no S2_API_KEY (keyless requests return 429)"

    def search(self, query: str, limit: int) -> list[Record]:
        return _records(S.s2_search(query, api_key=os.environ["S2_API_KEY"], limit=limit))

    def evidence(self, record: Record) -> str | None:
        return None  # the evidence_url is a plain GET JSON endpoint; verify fetches it


class Arxiv:
    name, group = "arxiv", "papers"

    def available(self) -> tuple[bool, str]:
        return True, ""

    def search(self, query: str, limit: int) -> list[Record]:
        return _records(S.arxiv_search(query, limit=limit))

    def evidence(self, record: Record) -> str | None:
        return None  # Atom XML at evidence_url; verify extracts its text


for _source in (OpenAlex(), SemanticScholar(), Arxiv()):
    register(_source)
