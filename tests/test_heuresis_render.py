"""Closest work and product evidence sections."""

from __future__ import annotations

from heuresis import render

RECORDS = {
    "r1": {"title": "Rival", "url": "https://r.example", "source": "openalex", "date": "2025"},
    "r2": {"title": "Other", "url": "https://o.example", "source": "github", "date": ""},
    "r3": {"title": "Gone", "url": "https://g.example", "source": "web", "date": ""},
}
JUDGE = {
    "closest": {
        "ref": "r1",
        "quote": "a quoted passage long enough",
        "differs": {"domain": "d", "purpose": "p", "mechanism": "m", "evaluation": "e"},
    },
    "others": [
        {"ref": "r2", "quote": "q2", "differs": "smaller scope"},
        {"ref": "r3", "quote": "q3", "differs": "x"},
    ],
}


def test_closest_section_lists_rival_facets_and_skips_dropped():
    text = render.closest_section(JUDGE, RECORDS, dropped={"r3"})
    assert text.startswith("**Closest:** [Rival](https://r.example) (openalex, 2025)")
    assert "> a quoted passage long enough" in text
    assert "- Mechanism: m" in text
    assert "[Other](https://o.example)" in text and "Gone" not in text


def test_closest_section_says_none_verified_when_the_closest_is_dropped():
    text = render.closest_section(JUDGE, RECORDS, dropped={"r1"})
    assert text.startswith("**Closest:** none verified.")


def test_product_section_leaves_unknowns_blank():
    evidence = {
        "rivals": ["[A](https://a.example): $9/mo"],
        "demand": [],
        "riskiest_assumption": "people pay",
        "cheapest_test": "",
    }
    text = render.product_section({"product_evidence": evidence})
    assert "- [A](https://a.example): $9/mo" in text
    assert "**Demand:** unknown" in text
    assert "**Cheapest test:** unknown" in text


def test_product_section_is_empty_without_evidence():
    assert render.product_section({}) == ""
