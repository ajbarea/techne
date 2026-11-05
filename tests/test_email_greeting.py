"""Tests for email_greeting.py, the opt-in guard on email drafts' opening greeting."""

from __future__ import annotations

import json
import pathlib
import re
import subprocess

import pytest
from conftest import HOOK_PYTHON, _load, hook_env, hook_handlers, run_hook_handler

ROOT = pathlib.Path(__file__).resolve().parent.parent
GUARD = ROOT / "plugins" / "phylax" / "hooks" / "email_greeting.py"
g = _load("email_greeting", GUARD)

TOOLS = (
    "mcp__plugin_epistole_epistole__create_draft",
    "mcp__plugin_epistole_epistole__update_draft",
    "mcp__claude_ai_Gmail__create_draft",
    "mcp__claude_ai_Gmail__update_draft",
    "mcp__claude_ai_Gmail__send_message",
    "mcp__claude_ai_Gmail__reply",
    "mcp__claude_ai_Gmail_f2a0fc77__create_draft",
    "mcp__claude_ai_Gmail_2__reply",
)
# Tools sharing a word with the drafts that the guard must leave alone.
OTHERS = (
    "mcp__plugin_epistole_epistole__send_draft",
    "mcp__plugin_epistole_epistole__create_draft_extra",
    "mcp__claude_ai_Gmail__get_draft",
    "mcp__other__create_draft",
    "mcp__claude_ai_Gmail__forward",
    "mcp__claude_ai_Gmailx__create_draft",
    "mcp__claude_ai_Gmail_a-b__create_draft",
)


def at(hh: int, mm: int = 0) -> int:
    return hh * 60 + mm


@pytest.mark.parametrize(
    ("minutes", "want"),
    [
        (at(0), ["Good morning"]),
        (at(9), ["Good morning"]),
        (at(11, 49), ["Good morning"]),
        (at(11, 50), ["Good morning", "Good afternoon"]),
        (at(12), ["Good afternoon", "Good morning"]),
        (at(12, 10), ["Good afternoon", "Good morning"]),
        (at(12, 11), ["Good afternoon"]),
        (at(16, 50), ["Good afternoon", "Good evening"]),
        (at(17), ["Good evening", "Good afternoon"]),
        (at(17, 11), ["Good evening"]),
        (at(23, 59), ["Good evening"]),
    ],
)
def test_allowed_by_clock(minutes, want):
    assert g.allowed(minutes) == want


@pytest.mark.parametrize(
    ("line", "minutes", "ok"),
    [
        ("Good morning Dr. Sahin,", at(9), True),
        ("good Morning Dima,", at(9), True),
        ("Good afternoon Dr. Sahin,", at(9), False),
        ("Good evening,", at(20), True),
        ("Good morning,", at(20), False),
        ("Good afternoon Ben,", at(11, 55), True),
        ("Hi Dr. Golen,", at(9), False),
        ("Hello team,", at(14), False),
        ("Hey Ben,", at(14), False),
        ("Dear Professor,", at(14), False),
        ("Thanks for the notes.", at(14), False),
        ("Goodmorning,", at(9), False),
        ("Buenos días Marta,", at(9), True),
        ("Hola Juan,", at(9), True),
        ("Buenas tardes Juan,", at(9), True),
        ("Bonjour Marie,", at(20), True),
        ("Guten Tag Herr Schmidt,", at(9), True),
        ("Querida Ana,", at(9), True),
        ("Prezado Carlos,", at(9), True),
        ("Cher Paul,", at(9), True),
        ("Caro Marco,", at(9), True),
        ("Buon pomeriggio Marco,", at(9), True),
        ("Careful: the build broke.", at(9), False),
        ("Cheers Ben,", at(9), False),
        ("Holistic review attached.", at(9), False),
        ("I\u2019m writing to follow up", at(9), False),
        ("Greetings \u2014 Bob", at(9), False),
        ("Thanks \U0001f600", at(9), False),
        ("Hi José,", at(9), False),
        ("Good evening Zoë,", at(9), False),
    ],
)
def test_verdict(line, minutes, ok):
    reason = g.verdict(line, minutes)
    assert (reason is None) == ok
    if not ok:
        assert "Good" in reason and "never Hi or Dear" in reason


def test_reason_names_the_greeting_to_use():
    assert '"Good afternoon <Name>,"' in g.verdict("Hi Ben,", at(14))


@pytest.mark.parametrize(
    ("tool_input", "want"),
    [
        ({"body": "\n\n  Good morning Ben,\nText"}, "Good morning Ben,"),
        ({"body": "﻿Hi Ben,"}, "Hi Ben,"),
        ({"body": "", "html": "<p>Good evening Ben,</p><p>x</p>"}, "Good evening Ben,"),
        ({"htmlBody": "<div>Dear&nbsp;Ben,<br>x</div>"}, "Dear\xa0Ben,"),
        ({"body": "Good morning,", "html": "<p>Hi,</p>"}, "Good morning,"),
        ({"draftId": "r1", "subject": "New subject"}, None),
        ({"body": "   ", "html": "<p></p>"}, None),
        ({"body": 5}, None),
        (
            {"htmlBody": "<head><style>p{margin:0}</style></head><p>Good morning Ben,</p>"},
            "Good morning Ben,",
        ),
        ({"htmlBody": "<title>Note</title><p>Good morning Ben,</p>"}, "Good morning Ben,"),
        ({"htmlBody": "<!-- a > b --><p>Good morning Ben,</p>"}, "Good morning Ben,"),
        ({"htmlBody": "<p>&#8203;Good morning Ben,</p>"}, "Good morning Ben,"),
        ({"body": "\u200bHi Ben,"}, "Hi Ben,"),
        ({"body": "\u00ad\u200eHi Ben,"}, "Hi Ben,"),
        ({"htmlBody": "<head><meta charset=utf-8><body><p>Hi Bob</p>"}, "Hi Bob"),
        ({"htmlBody": "<script>x()</script><div>Hi&nbsp;<b>Ben</b>,</div>"}, "Hi\xa0Ben,"),
    ],
)
def test_first_line(tool_input, want):
    assert g.first_line(tool_input) == want


def payload(tool: str, **tool_input) -> str:
    return json.dumps({"tool_name": tool, "tool_input": tool_input})


def decision(proc: subprocess.CompletedProcess) -> str | None:
    assert proc.returncode == 0, proc.stderr
    if not proc.stdout.strip():
        return None
    out = json.loads(proc.stdout)["hookSpecificOutput"]
    assert out["hookEventName"] == "PreToolUse"
    assert out["permissionDecision"] == "deny"
    return out["permissionDecisionReason"]


def handler() -> tuple[str, dict]:
    groups = json.loads((ROOT / "plugins" / "phylax" / "hooks" / "hooks.json").read_text())
    for group in groups["hooks"]["PreToolUse"]:
        for h in group["hooks"]:
            if "email_greeting.py" in h["command"]:
                return group["matcher"], h
    raise AssertionError("no email_greeting handler")


def run_handler(stdin: str, on: str = "true", tz: str = "Etc/GMT+3"):
    env = hook_env({"email_greeting": on, "email_timezone": tz})
    return run_hook_handler("phylax", handler()[1], stdin, env)


@pytest.mark.parametrize("tool", TOOLS)
def test_matcher_covers_the_draft_tools(tool):
    assert re.search(handler()[0], tool)


@pytest.mark.parametrize("tool", OTHERS)
def test_matcher_leaves_other_tools(tool):
    assert not re.search(handler()[0], tool)


def test_handler_is_gated_on_the_option():
    assert hook_handlers("phylax", "PreToolUse", handler()[0])
    proc = run_handler(payload(TOOLS[0], body="Hi Ben,"), on="false")
    assert proc.returncode == 0 and proc.stdout == ""


def greeting_now(tz: str) -> str:
    """The greeting the guard expects right now in TZ, computed the way it does."""
    t = g.now(tz)
    return g.allowed(t.hour * 60 + t.minute)[0]


@pytest.mark.parametrize("tool", TOOLS)
def test_handler_refuses_hi_and_allows_the_right_greeting(tool):
    body_key = "htmlBody" if "Gmail" in tool else "html"
    reason = decision(run_handler(payload(tool, body="Hi Ben,\nx")))
    assert reason and "never Hi or Dear" in reason
    right = greeting_now("Etc/GMT+3")
    assert decision(run_handler(payload(tool, **{body_key: f"<p>{right} Ben,</p>"}))) is None


def test_unknown_timezone_names_the_option():
    reason = decision(run_handler(payload(TOOLS[0], body="Good morning,"), tz="Mars/Olympus"))
    assert reason and "email_timezone" in reason and "Mars/Olympus" in reason


def test_empty_timezone_uses_local_time():
    right = greeting_now("")
    assert decision(run_handler(payload(TOOLS[0], body=f"{right} Ben,"), tz="")) is None


@pytest.mark.parametrize("stdin", ["", "not json", "[]", '{"tool_input": "x"}'])
def test_unreadable_payload_is_allowed_and_reported(stdin):
    proc = subprocess.run(
        [HOOK_PYTHON, str(GUARD)],
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
        env=hook_env(["email_greeting"]),
    )
    assert proc.returncode == 0 and proc.stdout == ""
    assert "cannot read the call" in proc.stderr


def test_both_bodies_are_checked():
    lines = g.first_lines({"body": "Good afternoon Bob,", "htmlBody": "<p>Hi Bob</p>"})
    assert lines == ["Good afternoon Bob,", "Hi Bob"]
    right = greeting_now("Etc/GMT+3")
    reason = decision(
        run_handler(payload(TOOLS[2], body=f"{right} Bob,", htmlBody="<p>Hi Bob</p>"))
    )
    assert reason and '"Hi"' in reason


def _opening_full(text: str) -> str | None:
    """The opening line read the slow way, as the reference: Cf dropped from the whole text,
    then the first non-empty line."""
    import unicodedata

    text = "".join(c for c in text if unicodedata.category(c) != "Cf")
    return next((line.strip() for line in text.splitlines() if line.strip()), None)


_LONG_DEC = "&#" + "0" * 40 + "10;"  # a character reference longer than HTMLParser's lookahead
_LONG_HEX = "&#x" + "0" * 40 + "a;"
_PIECES = (
    "<p>", "</p>", "<div>", "</div>", "<br>", "<br/>", "<li>", "<span>", "</span>", "<b>",
    "<style>p{x:y}</style>", "<script>Good morning,</script>", "<title>Hi</title>", "<template>",
    "</template>", "<!-- Hi -->", "Good morning,", "Hi Dana,", "Dear all", "x", " ", "  ",
    "\n", "\r", "\r\n", "\u2028", "\u200b", "\ufeff", "\u200e", "&amp;", "&#8203;", "&nbsp;",
    "&#x200B;", "&", "<", "Ünïcödé", "\t", _LONG_DEC, _LONG_HEX, "<!-->", "<!--->", "<!--",
    "-->", "&#10;", "<![CDATA[Hi]]>", " " * 9000, "\x1f", "\x0b", "\x1c", "\x85",
)  # fmt: skip


def test_html_opening_matches_reading_the_whole_body():
    # The early stop must name the line the full parse names: HTMLParser's output depends on
    # where its input is split, so the body is fed whole and only the handlers stop early.
    import random

    rng = random.Random(277)
    for _ in range(3000):
        raw = "".join(rng.choice(_PIECES) for _ in range(rng.randint(1, 30)))
        assert g.html_opening(raw) == _opening_full(g.visible_text(raw)), repr(raw)


@pytest.mark.parametrize(
    "raw",
    [
        # A long reference across what was a chunk boundary: main denies "Dana,"; a chunked
        # parse merged the next line in and let the non-ASCII letter through.
        "<p>" + " " * 8141 + "Dana," + _LONG_DEC + "Grüße</p>",
        # A <!--> comment read whole runs to the later -->; read in pieces it closed at once.
        "<!-->Hi Dana,\n-->Good evening, Dana",
        "<!-->Good evening, Dana\n-->Hi Dana,",
    ],
    ids=["long-charref", "comment-hides-hi", "comment-hides-greeting"],
)
def test_html_opening_on_input_a_split_parse_got_wrong(raw):
    assert g.html_opening(raw) == _opening_full(g.visible_text(raw))
    tool_input = {"htmlBody": raw}
    assert g.first_lines(tool_input) == [_opening_full(g.visible_text(raw))]


@pytest.mark.parametrize(
    "text", ["\u200b\nGood morning,", "\r\u200b\nHi,", "  \n\t\n x \u200e", "\ufeff", "", "a\x85b"]
)
def test_opening_matches_dropping_format_characters_first(text):
    assert g.opening(text) == _opening_full(text)


def test_html_opening_stops_at_the_first_line(monkeypatch):
    # A long message is parsed only up to its first line, not to its end.
    seen: list[str] = []
    handle_data = g._Text.handle_data

    def counting(self, data):
        seen.append(data)
        handle_data(self, data)

    monkeypatch.setattr(g._Text, "handle_data", counting)
    raw = "<div><p>Good morning,</p>" + "<p>Line of the message.</p>" * 2000 + "</div>"
    assert g.html_opening(raw) == "Good morning,"
    assert seen == ["Good morning,"]


def test_html_opening_stops_inside_a_run_of_text(monkeypatch):
    # The first line ends at a break inside text, and inline tags follow: no block tag ends it.
    seen: list[str] = []
    handle_data = g._Text.handle_data

    def counting(self, data):
        seen.append(data)
        handle_data(self, data)

    monkeypatch.setattr(g._Text, "handle_data", counting)
    raw = "Good morning,\nrest" + "<span>x</span>" * 2000
    assert g.html_opening(raw) == "Good morning,"
    assert seen == ["Good morning,\nrest"]


def test_breaks_are_exactly_the_line_boundaries():
    # A character in _BREAKS that splitlines does not split on would end the line early.
    import sys

    boundaries = {
        chr(c) for c in range(sys.maxunicode + 1) if len(("a" + chr(c) + "b").splitlines()) > 1
    }
    assert set(g._BREAKS) == boundaries


def test_html_body_the_parser_rejects(monkeypatch, capsys):
    # Older CPython parsers raise on some markup (`<![foo[x]]>`); stand-in: a tag that raises.
    start = g._Text.handle_starttag

    def rejecting(self, tag, attrs):
        if tag == "bad":
            raise AssertionError("unknown status keyword")
        start(self, tag, attrs)

    monkeypatch.setattr(g._Text, "handle_starttag", rejecting)
    lines = g.first_lines({"body": "Good morning,", "htmlBody": "<bad><p>Hi Dana,</p>"})
    assert lines == ["Good morning,"]
    assert "cannot parse htmlBody (AssertionError" in capsys.readouterr().err
    # The first HTML field present is the body sent; a later one is not read in its place.
    assert g.first_lines({"html": "<bad>", "htmlBody": "<p>Hi Dana,</p>"}) == []
    # Markup past the first line is never read.
    assert g.first_lines({"htmlBody": "<p>Hi Dana,</p><bad>"}) == ["Hi Dana,"]


def test_html_opening_flushes_text_the_parser_holds_at_the_end():
    # Text after the last tag stays in the parser until close().
    assert g.html_opening("<p></p>  Good morning,") == "Good morning,"
    assert g.html_opening("<p></p>Hi&amp") == "Hi&"
