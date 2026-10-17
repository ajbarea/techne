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
) -> tuple[list[tuple[str, Record]], list[Coverage]]:
    """Each record paired with the query that found it, and one coverage line per source."""
    records: list[tuple[str, Record]] = []
    coverage: list[Coverage] = []
    for source in sources:
        try:
            ok, why = source.available()
        except Exception as exc:  # a broken availability probe is a coverage line, not a crash
            coverage.append(Coverage(source.name, "failed", note=f"{type(exc).__name__}: {exc}"))
            continue
        if not ok:
            coverage.append(Coverage(source.name, "skipped", note=why))
            continue
        hits, error, attempted = 0, "", 0
        for query in queries:
            attempted += 1
            try:
                found = source.search(query, limit)
            except Exception as exc:  # any adapter bug or API change is reported, not raised
                known = type(exc).__name__ in ("SourceError", "ScholarlyError")
                error = str(exc) if known else f"{type(exc).__name__}: {exc}"
                break
            hits += len(found)
            records.extend((query, r) for r in found)
        if error and hits:
            # The records already found are in the pool, so the source counts as answering.
            status, note = "ok", f"partial: {error}"
        else:
            status, note = ("failed" if error else ("ok" if hits else "empty")), error
        coverage.append(Coverage(source.name, status, attempted, hits, note))
    return records, coverage


def _load_adapters() -> None:
    from heuresis.sources import papers, patents, products  # noqa: F401  # register on import


_load_adapters()
