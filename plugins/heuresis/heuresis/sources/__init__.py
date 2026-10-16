"""Source protocol and registry. A source that fails becomes a coverage line, never a crash."""

from __future__ import annotations

from typing import Protocol

from heuresis.model import Coverage, Record


class Source(Protocol):
    name: str
    group: str

    def available(self) -> tuple[bool, str]: ...

    def search(self, query: str, limit: int) -> list[Record]: ...

    def evidence(self, record: Record) -> str | None: ...


REGISTRY: dict[str, list[Source]] = {"papers": [], "patents": [], "products": []}


def register(source: Source) -> None:
    REGISTRY[source.group].append(source)


def by_name(name: str) -> Source | None:
    return next((s for group in REGISTRY.values() for s in group if s.name == name), None)


def run_queries(
    sources: list[Source], queries: list[str], limit: int
) -> tuple[list[Record], list[Coverage]]:
    records: list[Record] = []
    coverage: list[Coverage] = []
    for source in sources:
        ok, why = source.available()
        if not ok:
            coverage.append(Coverage(source.name, "skipped", note=why))
            continue
        hits, error = 0, ""
        for query in queries:
            try:
                found = source.search(query, limit)
            except Exception as exc:  # any adapter bug or API change is reported, not raised
                known = type(exc).__name__ in ("SourceError", "ScholarlyError")
                error = str(exc) if known else f"{type(exc).__name__}: {exc}"
                break
            hits += len(found)
            records.extend(found)
        status = "failed" if error else ("ok" if hits else "empty")
        coverage.append(Coverage(source.name, status, len(queries), hits, error))
    return records, coverage


def _load_adapters() -> None:
    from heuresis.sources import papers, patents, products  # noqa: F401  # register on import


_load_adapters()
