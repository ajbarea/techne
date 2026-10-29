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

# The maintainer's rule (10-29): at most about 150 visible words for a PR, 300
# for an issue; a comment is held to a PR's. "About" allows a tenth more.
BUDGET = {"PR": 150, "issue": 300, "comment": 150}
SLACK = 1.1
LONG_SENTENCE = 25

_FOLD_TAG = re.compile(r"<(/?)(details|summary)\b([^>]*)>", re.I)
_COMMENT = re.compile(r"<!--.*?-->", re.S)
# As graphe's prose_check.MD_FENCE: a fence may be indented (a list item's).
_FENCE = re.compile(r"^[ \t]*(`{3,}|~{3,})[^\n]*\n.*?^[ \t]*\1[`~]*[ \t]*$", re.M | re.S)
_INLINE_CODE = re.compile(r"`[^`\n]*`")
_LINK_URL = re.compile(r"\]\([^)]*\)")
# HTML tags a GitHub body uses; anything else in angle brackets is text.
_TAG = re.compile(
    r"</?(?:details|summary|br|hr|img|sub|sup|b|i|em|strong|code|kbd|p|a|span|div|ul|ol|li|table|tr|td|th)\b[^>]*>",
    re.I,
)
_ENTITY = re.compile(r"&(?:[A-Za-z]{2,8}|#\d{1,6}|#x[0-9A-Fa-f]{1,6});")
_WORD = re.compile(r"[^\W_]")
_MARKER = re.compile(r"<!--\s*budget\s*:|^\s*%+\s*budget\s*:", re.I | re.M)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+|\n\s*\n|\n(?=\s*(?:[-*+]|\d+\.|\||#))")


def blank_code(body: str) -> str:
    """BODY with its fenced and inline code blanked: a tag or a marker shown as
    code is text, not markup."""
    return _INLINE_CODE.sub(" ", _FENCE.sub(" ", body))


def visible(body: str) -> str:
    """What GitHub shows of BODY folded: its text outside folded <details>
    blocks (nested ones too; an unclosed one hides the rest, as GitHub renders
    it), each folded block's <summary> line, an open block's content, and no
    HTML comment or code."""
    body = _COMMENT.sub(" ", blank_code(body))
    out: list[str] = []
    shown: list[bool] = []  # one per open <details>: whether its content shows
    summary = False
    pos = 0
    for m in _FOLD_TAG.finditer(body):
        if all(shown) or summary:
            out.append(body[pos : m.start()])
        closing, tag, attrs = m.group(1), m.group(2).lower(), m.group(3)
        if tag == "details":
            if closing:
                if shown:
                    shown.pop()
            else:
                shown.append(re.search(r"\bopen\b", attrs, re.I) is not None)
        else:
            # A folded block's summary shows when the blocks around it do.
            summary = not closing and bool(shown) and all(shown[:-1])
        pos = m.end()
    if all(shown) or summary:
        out.append(body[pos:])
    return " ".join(out)


def prose(text: str) -> str:
    """TEXT without code, link targets and HTML tags."""
    text = _FENCE.sub(" ", text)
    text = _INLINE_CODE.sub(" ", text)
    text = _LINK_URL.sub("]", text)
    return _ENTITY.sub(" ", _TAG.sub(" ", text))


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
    if _MARKER.search(blank_code(body)):
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
