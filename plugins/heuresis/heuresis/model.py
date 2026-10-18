"""Data shapes shared by the store, the sources and the verdict rules."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

STATES = ("inbox", "trash", "later", "do", "building", "shipped", "merged")
TYPES = ("product", "tool", "research", "improve")
CAPTURED_VIA = ("terminal", "phone", "form", "import")
SECTIONS = (
    "Idea",
    "Restated",
    "Closest work",
    "Fit with your work",
    "Product evidence",
    "Verdict log",
    "Notes",
)
# Hand-written text heuresis does not own: stray lines and unknown sections, kept in file order.
NOTES = "Notes"
KINDS = ("paper", "patent", "product", "repo", "web", "idea", "context")
PAPER_SOURCES = ("openalex", "semantic_scholar", "arxiv")
PATENT_SOURCES = ("lens", "epo")
FACETS = ("domain", "purpose", "mechanism", "evaluation")
RECORD_REQUIRED = ("title", "url", "source", "kind")


@dataclass
class Idea:
    id: str
    title: str
    captured: str
    captured_via: str
    state: str = "inbox"
    type: str | None = None
    project: str | None = None
    duplicate_of: str | None = None
    revisit: str | None = None
    revisit_on: list[str] = field(default_factory=list)
    related: list[str] = field(default_factory=list)
    sections: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Record:
    title: str
    url: str
    source: str
    kind: str
    text: str = ""
    date: str = ""
    doi: str = ""
    evidence_url: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: object) -> Record:
        if not isinstance(data, dict):
            raise ValueError("record rejected: not a JSON object")
        known = {k: data[k] for k in cls.__dataclass_fields__ if k in data and data[k] is not None}
        missing = [k for k in RECORD_REQUIRED if k not in known]
        if missing:
            raise ValueError(f"record rejected: missing {', '.join(missing)}")
        return cls(**{k: str(v) for k, v in known.items()})


@dataclass(frozen=True)
class Coverage:
    source: str
    status: str  # ok | empty | failed | skipped
    queries: int = 0
    hits: int = 0
    note: str = ""

    def line(self) -> str:
        text = f"{self.source}: {self.status}, {self.queries} queries, {self.hits} hits"
        return f"{text} ({self.note})" if self.note else text

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Coverage:
        return cls(
            source=str(data["source"]),
            status=str(data["status"]),
            queries=int(data.get("queries", 0)),
            hits=int(data.get("hits", 0)),
            note=str(data.get("note", "")),
        )


@dataclass
class Verdict:
    date: str
    origin: str  # triage | override | declined
    state: str
    reason: str
    type: str | None = None
    project: str | None = None
    next_step: str = ""
    duplicate_of: str | None = None
    revisit: str | None = None
    coverage: list[Coverage] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
