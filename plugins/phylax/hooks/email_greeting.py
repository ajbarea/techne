#!/usr/bin/env python3
"""Guard on email drafts: the body opens with the greeting for the local time of day.

The hooks.json PreToolUse hook runs this when the email_greeting option is on, for
epistole's create_draft and update_draft and the claude.ai Gmail connector's create_draft,
update_draft, send_message and reply (a second Gmail connector's name carries a suffix,
which the matcher allows). The first line of the body must start "Good morning" before 12:00,
"Good afternoon" from 12:00 to 17:00 and "Good evening" after, by the clock in
email_timezone (an IANA name such as America/New_York; empty means the system's local
time). Within GRACE minutes of 12:00 or 17:00 either neighbour is accepted, since the draft
was written a moment before the call. A body that opens with Hi, Hello, Hey or Dear is
refused with the greeting to use. The rule is for English mail: a first line opening with a
common Spanish, Portuguese, French, Italian or German greeting (FOREIGN), or holding a
letter outside ASCII, is left alone. Both the plain-text body and the HTML one's visible
text (no style, script, title or comments) are checked, with invisible format characters
(Unicode Cf) dropped. A call with neither (an update that keeps the body) is
allowed. A payload that cannot be read is reported on stderr and allowed: the guard
enforces a house style, not data safety. An email_timezone the system does not know
refuses the call and names the option, so a typo cannot silently switch the clock.
Runs on the system python3, so it stays compatible with 3.9 (macOS's).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import unicodedata
from html.parser import HTMLParser

BODY_FIELDS = ("body",)
HTML_FIELDS = ("html", "htmlBody")
GRACE = 10
NOON, EVENING = 12 * 60, 17 * 60
GREETINGS = ("Good morning", "Good afternoon", "Good evening")
# Greetings in other languages open mail the rule does not cover.
FOREIGN = re.compile(
    r"^(hola|buen[oa]s?|saludos|estimad[oa]s?|querid[oa]s?|bom dia|boa (tarde|noite)|ol[aá]"
    r"|prezad[oa]s?|bonjour|bonsoir|salut|cher|ch[eè]re|guten (morgen|tag|abend)|hallo|moin"
    r"|liebe[r]?|sehr geehrte[r]?|ciao|salve|car[oa]|buon\w*|buona\s+sera|gentile)\b",
    re.I,
)
INFORMAL = re.compile(r"^(hi|hello|hey|dear)\b", re.I)
GREETING = re.compile(r"^good\s+(morning|afternoon|evening)\b", re.I)
BLOCKS = {"br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "blockquote"}
HIDDEN = {"style", "script", "title", "template"}


class _Text(HTMLParser):
    """The visible text of an HTML body, one line per block."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in HIDDEN:
            self.hidden += 1
        elif tag in BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in HIDDEN:
            self.hidden = max(0, self.hidden - 1)
        elif tag in BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def visible_text(raw: str) -> str:
    parser = _Text()
    parser.feed(raw)
    parser.close()
    return "".join(parser.parts)


def now(tz_name: str) -> dt.datetime:
    if not tz_name:
        return dt.datetime.now().astimezone()
    from zoneinfo import ZoneInfo

    return dt.datetime.now(ZoneInfo(tz_name))


def allowed(minutes: int) -> list[str]:
    """The greetings that fit a time of day, in minutes after midnight."""

    def part(m: int) -> str:
        return GREETINGS[0] if m < NOON else GREETINGS[1] if m < EVENING else GREETINGS[2]

    fits = [part(minutes)]
    for edge in (NOON, EVENING):
        if abs(minutes - edge) <= GRACE:
            fits += [p for p in (part(edge - 1), part(edge)) if p not in fits]
    return fits


def opening(text: str) -> str | None:
    """The first non-empty line, with invisible format characters (Unicode Cf) dropped."""
    text = "".join(c for c in text if unicodedata.category(c) != "Cf")
    return next((line.strip() for line in text.splitlines() if line.strip()), None)


def first_lines(tool_input: dict) -> list[str]:
    """The opening line of each body the call carries: plain text and HTML's visible text.

    A rich client shows the HTML body and a plain one shows the text, so both are checked.
    """
    found = []
    for keys, read in ((BODY_FIELDS, str), (HTML_FIELDS, visible_text)):
        for key in keys:
            raw = tool_input.get(key)
            if isinstance(raw, str) and raw.strip():
                line = opening(read(raw))
                if line:
                    found.append(line)
                break
    return found


def first_line(tool_input: dict) -> str | None:
    lines = first_lines(tool_input)
    return lines[0] if lines else None


def verdict(line: str, minutes: int) -> str | None:
    """The refusal reason for a body's first line, or None when it fits."""
    if FOREIGN.match(line) or (
        any(c.isalpha() and not c.isascii() for c in line)
        and not INFORMAL.match(line)
        and not GREETING.match(line)
    ):
        return None  # another language's greeting; the rule is for English mail
    fits = allowed(minutes)
    clock = f"{minutes // 60:02d}:{minutes % 60:02d}"
    use = " or ".join(f'"{g} <Name>,"' for g in fits)
    m = GREETING.match(line)
    if m and f"Good {m.group(1).lower()}" in fits:
        return None
    found = m or INFORMAL.match(line)
    what = f'opens with "{found.group(0)}"' if found else "has no time-of-day greeting"
    return f"The email body {what}, but it is {clock} here: open it with {use}, never Hi or Dear."


def deny(reason: str) -> None:
    out = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    print(json.dumps(out))


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        tool_input = payload["tool_input"]
        if not isinstance(tool_input, dict):
            raise TypeError("tool_input is not an object")
    except (ValueError, KeyError, TypeError) as exc:
        print(f"phylax email_greeting: cannot read the call ({exc}); allowed", file=sys.stderr)
        return 0
    lines = first_lines(tool_input)
    if not lines:
        return 0
    tz_name = os.environ.get("CLAUDE_PLUGIN_OPTION_EMAIL_TIMEZONE", "").strip()
    try:
        t = now(tz_name)
    except Exception as exc:  # zoneinfo raises several types for a bad key
        deny(
            f"phylax's email_timezone is {tz_name!r}, which this system does not know "
            f"({type(exc).__name__}); set an IANA name such as America/New_York in /config, "
            "or leave it empty for the local time."
        )
        return 0
    minutes = t.hour * 60 + t.minute
    reason = next((r for r in (verdict(line, minutes) for line in lines) if r), None)
    if reason:
        deny(reason)
    return 0


if __name__ == "__main__":
    sys.exit(main())
