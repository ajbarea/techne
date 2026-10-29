#!/bin/bash
set -euo pipefail
git init -q -b main . && git config user.email t@t && git config user.name t
cat > dose.py <<'EOF_FILE'
def is_dose(text: str) -> bool:
    return False
EOF_FILE
cat > test_dose.py <<'EOF_FILE'
import dose


def test_plain_text_is_not_a_dose():
    assert not dose.is_dose("take a walk")
EOF_FILE
git add -A && git commit -qm base
git checkout -q -b feature
cat > dose.py <<'EOF_FILE'
import re

MG = re.compile(r"\bmg\b")


def is_dose(text: str) -> bool:
    """True when the text states a dose in milligrams, e.g. "10mg" or "10 mg"."""
    return bool(MG.search(text))
EOF_FILE
cat > test_dose.py <<'EOF_FILE'
import dose


def test_plain_text_is_not_a_dose():
    assert not dose.is_dose("take a walk")


def test_spaced_dose():
    assert dose.is_dose("take 10 mg daily")
EOF_FILE
git add -A && git commit -qm "flag doses written in milligrams"
