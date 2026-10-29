"""The length budget for issue, PR and comment bodies (techne#229).

git_guards.py calls `check` with a body headed for GitHub. Only the visible
text counts: what sits outside <details> blocks, HTML comments, code and link
targets, counted as graphe's length_budget.markdown_words counts a markdown
page (a token holding a letter or digit), so table bars and bullets do not
count. A body over its budget, or one carrying a `budget:` marker (a file-only
convention: GitHub shows the raw text in mail and notifications), is refused;
long sentences are reported without refusing.
"""

from __future__ import annotations

import re

# AJ 10-29: at most about 150 visible words for a PR, 300 for an issue; a
# comment is held to a PR's. "About" allows a tenth more.
BUDGET = {"PR": 150, "issue": 300, "comment": 150}
SLACK = 1.1
LONG_SENTENCE = 25

_DETAILS_OPEN = re.compile(r"<details\b[^>]*>", re.I)
_DETAILS_TAG = re.compile(r"<(/?)details\b[^>]*>", re.I)
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_FENCE = re.compile(r"^(?P<fence>`{3,}|~{3,})[^\n]*\n.*?(?:^(?P=fence)[ \t]*$|\Z)", re.S | re.M)
_INLINE_CODE = re.compile(r"`[^`\n]*`")
_LINK_URL = re.compile(r"\]\([^)]*\)")
_TAG = re.compile(r"</?[A-Za-z][^>]*>")
_WORD = re.compile(r"[^\W_]")
_MARKER = re.compile(r"<!--\s*budget\s*:|^\s*%+\s*budget\s*:", re.I | re.M)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+|\n\s*\n|\n(?=\s*(?:[-*+]|\d+\.|\||#))")


def visible(body: str) -> str:
    """BODY without its <details> blocks (nested ones too) and HTML comments.
    An unclosed <details> hides the rest, as GitHub renders it."""
    body = _COMMENT.sub(" ", body)
    out: list[str] = []
    depth = 0
    pos = 0
    for m in _DETAILS_TAG.finditer(body):
        if depth == 0:
            out.append(body[pos : m.start()])
        depth = max(depth - 1, 0) if m.group(1) else depth + 1
        pos = m.end()
    if depth == 0:
        out.append(body[pos:])
    return "".join(out)


def prose(text: str) -> str:
    """TEXT without code, link targets and HTML tags."""
    text = _FENCE.sub(" ", text)
    text = _INLINE_CODE.sub(" ", text)
    text = _LINK_URL.sub("]", text)
    return _TAG.sub(" ", text)


def words(text: str) -> int:
    return sum(1 for token in text.split() if _WORD.search(token))


def visible_words(body: str) -> int:
    return words(prose(visible(body)))


def long_sentences(body: str) -> list[str]:
    """Sentences of the visible prose over LONG_SENTENCE words; table rows are not sentences."""
    text = "\n".join(
        line for line in prose(visible(body)).splitlines() if not line.lstrip().startswith("|")
    )
    found = []
    for s in _SENTENCE_END.split(text):
        s = " ".join(s.split())
        if words(s) > LONG_SENTENCE:
            found.append(s)
    return found


def check(kind: str, body: str) -> tuple[list[str], list[str]]:
    """The refusals and the warnings for a body of KIND (PR, issue or comment)."""
    denies: list[str] = []
    warnings: list[str] = []
    if _MARKER.search(body):
        denies.append(
            f"phylax: this {kind} body carries a `budget:` marker. GitHub shows the raw text "
            "in mail and notifications, so a body never carries one: remove it and retry."
        )
    budget = BUDGET[kind]
    ceiling = int(budget * SLACK)
    n = visible_words(body)
    if n > ceiling:
        denies.append(
            f"phylax: this {kind} body has {n} visible words (outside <details>); the budget "
            f"is about {budget}. Keep the short top (why, what in a small table, status) and "
            "fold the depth into <details> sections, or cut it; keep the evidence. A PR links "
            "its issue instead of restating it."
        )
    long = long_sentences(body)
    if long:
        shown = "; ".join(f"{s[:90]}..." if len(s) > 90 else s for s in long[:3])
        warnings.append(
            f"phylax: {len(long)} sentence(s) in this {kind} body run over {LONG_SENTENCE} "
            f"words; split them: {shown}"
        )
    return denies, warnings
