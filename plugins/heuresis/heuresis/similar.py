"""Earlier ideas that share words with a new one: candidates for the context scout to read."""

from __future__ import annotations

import re

from heuresis.model import Idea

STOPWORDS = frozenset(
    "the and for with that this from into over under about than then them they their there "
    "what when where which while would could should have has had are was were will can "
    "not but our you your its it's a an of to in on at by is be as or my me we i".split()
)


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2 and w not in STOPWORDS}


def similar(text: str, ideas: list[Idea], k: int = 5) -> list[tuple[str, float]]:
    target = _words(text)
    scored = []
    for idea in ideas:
        words = _words(idea.title + " " + idea.sections.get("Idea", ""))
        union = target | words
        if union:
            score = len(target & words) / len(union)
            if score > 0:
                scored.append((idea.id, round(score, 3)))
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:k]
