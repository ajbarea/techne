"""Wire contract: Mailbox through the real googleapiclient and bundled Gmail discovery doc."""

import base64
import json
from urllib.parse import parse_qs, urlsplit

import pytest
from epistole import gmail
from googleapiclient.discovery import build
from googleapiclient.http import HttpMockSequence

OK = {"status": "200"}


class Recorder(HttpMockSequence):
    def __init__(self, responses):
        super().__init__(responses)
        self.seen = []

    def request(
        self, uri, method="GET", body=None, headers=None, redirections=1, connection_type=None
    ):
        parts = urlsplit(uri)
        query = {k: v for k, v in parse_qs(parts.query).items() if k != "alt"}
        self.seen.append(
            (
                method,
                parts.path,
                query,
                json.loads(body) if body and isinstance(body, str | bytes) else None,
            )
        )
        return super().request(uri, method, body, headers, redirections, connection_type)


def mailbox(*bodies):
    http = Recorder([(OK, json.dumps(b)) for b in bodies])
    service = build("gmail", "v1", http=http, static_discovery=True)
    return gmail.Mailbox("school", "user@example.edu", service, sleep=lambda s: None), http


P = "/gmail/v1/users/me"


def test_search_wire():
    box, http = mailbox(
        {"messages": [{"id": "a", "threadId": "t"}], "nextPageToken": "P2"}, {"id": "a"}
    )
    assert box.search("from:x", 5, None) == ([{"id": "a"}], "P2")
    assert http.seen == [
        ("GET", f"{P}/messages", {"q": ["from:x"], "maxResults": ["5"]}, None),
        (
            "GET",
            f"{P}/messages/a",
            {"format": ["metadata"], "metadataHeaders": gmail.HEADERS},
            None,
        ),
    ]


def test_search_next_page_wire():
    box, http = mailbox({})
    box.search("q", 5, "P2")
    assert http.seen == [
        ("GET", f"{P}/messages", {"q": ["q"], "maxResults": ["5"], "pageToken": ["P2"]}, None)
    ]


@pytest.mark.parametrize(
    "call, expected",
    [
        (lambda b: b.thread("t"), ("GET", f"{P}/threads/t", {"format": ["full"]}, None)),
        (lambda b: b.message("m"), ("GET", f"{P}/messages/m", {"format": ["full"]}, None)),
        (lambda b: b.get_draft("d"), ("GET", f"{P}/drafts/d", {"format": ["full"]}, None)),
        (
            lambda b: b.create_draft("cmF3", None),
            ("POST", f"{P}/drafts", {}, {"message": {"raw": "cmF3"}}),
        ),
        (
            lambda b: b.create_draft("cmF3", "t"),
            ("POST", f"{P}/drafts", {}, {"message": {"raw": "cmF3", "threadId": "t"}}),
        ),
        (
            lambda b: b.update_draft("d", "cmF3", "t"),
            ("PUT", f"{P}/drafts/d", {}, {"id": "d", "message": {"raw": "cmF3", "threadId": "t"}}),
        ),
        (lambda b: b.get_raw_draft("d"), ("GET", f"{P}/drafts/d", {"format": ["raw"]}, None)),
        (
            lambda b: b.send_draft("d", "cmF3", "t"),
            (
                "POST",
                f"{P}/drafts/send",
                {},
                {"id": "d", "message": {"raw": "cmF3", "threadId": "t"}},
            ),
        ),
        (lambda b: b.attachment("m", "att"), ("GET", f"{P}/messages/m/attachments/att", {}, None)),
        (lambda b: b.sender(), ("GET", f"{P}/settings/sendAs", {}, None)),
    ],
)
def test_method_wire(call, expected):
    box, http = mailbox({"id": "x", "data": "aGk", "sendAs": []})
    call(box)
    assert http.seen == [expected]


def test_large_send_goes_to_the_upload_endpoint():
    http = Recorder(
        [({"status": "200", "location": "https://up.example/u1"}, ""), (OK, '{"id": "s"}')]
    )
    service = build("gmail", "v1", http=http, static_discovery=True)
    box = gmail.Mailbox("school", "user@example.edu", service, sleep=lambda s: None)
    data = b"x" * (gmail.UPLOAD_ABOVE + 1)
    assert box.send_draft("d", base64.urlsafe_b64encode(data).decode(), "t") == {"id": "s"}
    method, path, query, body = http.seen[0]
    assert (method, path) == ("POST", "/upload/gmail/v1/users/me/drafts/send")
    assert query == {"uploadType": ["resumable"]} and body == {
        "id": "d",
        "message": {"threadId": "t"},
    }
    assert http.seen[1][1] == "/u1"
