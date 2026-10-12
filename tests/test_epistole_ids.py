import pytest
from epistole import ids

ALIASES = ("school", "personal")


def test_round_trip():
    assert ids.parse(ids.qualify("school", "18f0a"), ALIASES) == ("school", "18f0a")


@pytest.mark.parametrize("bad", ["18f0a", "work:18f0a", ":18f0a", "school:"])
def test_rejects_unqualified_or_unknown(bad):
    with pytest.raises(ValueError):
        ids.parse(bad, ALIASES)


def test_require_refuses_account_mismatch():
    with pytest.raises(ValueError, match="belongs to 'school'"):
        ids.require("school:18f0a", "personal", ALIASES)
    assert ids.require("school:18f0a", "school", ALIASES) == "18f0a"


def test_resolve_treats_empty_account_like_none():
    assert ids.resolve("school:18f0a", "", ALIASES) == ("school", "18f0a")
    assert ids.resolve("school:18f0a", None, ALIASES) == ("school", "18f0a")
    with pytest.raises(ValueError, match="belongs to 'school'"):
        ids.resolve("school:18f0a", "personal", ALIASES)
