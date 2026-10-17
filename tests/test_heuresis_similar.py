"""Duplicate candidates by word overlap."""

from __future__ import annotations

from heuresis.model import Idea
from heuresis.similar import similar


def idea(i, text):
    return Idea(id=i, title=text, captured="x", captured_via="terminal", sections={"Idea": text})


def test_similar_ranks_overlap_and_ignores_stopwords():
    ideas = [
        idea("a", "A tool that triages research ideas against prior work"),
        idea("b", "Travel planner that works offline"),
        idea("c", "The and of with for"),
    ]
    out = similar("triage my research ideas against prior art", ideas, k=2)
    assert out[0][0] == "a"
    assert all(score > 0 for _, score in out)
    assert "c" not in [i for i, _ in out]


def test_two_letter_acronyms_count_and_two_letter_function_words_do_not():
    from heuresis.similar import _words

    assert _words("FL for EHR audit") == {"fl", "ehr", "audit"}
    assert _words("AI ML UI AR 3D") == {"ai", "ml", "ui", "ar", "3d"}
    assert _words("if it is so we do go up to me") == set()
    out = similar("FL for EHR audit", [idea("fl", "FL EHR anomaly detection")])
    assert out == [("fl", 0.4)] and out[0][1] > 0.15
