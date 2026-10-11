import json
import stat

import pytest
from epistole import audit, gmail
from epistole_fake import FakeService
from googleapiclient.errors import HttpError


def make(**kw):
    svc = FakeService()
    svc.messages["m1"] = {
        "id": "m1",
        "threadId": "t1",
        "snippet": "hi",
        "payload": {"headers": [{"name": "Subject", "value": "Plan"}]},
    }
    svc.search_hits = ["m1"]
    return svc, gmail.Mailbox("school", "user@example.edu", svc, sleep=lambda s: None, **kw)


def test_search_returns_metadata():
    _, box = make()
    hits, nxt = box.search("from:x", 10, None)
    assert hits[0]["id"] == "m1" and hits[0]["threadId"] == "t1"
    assert nxt is None


def test_create_and_send_draft():
    svc, box = make()
    d = box.create_draft("cmF3", "t1")
    assert svc.drafts[d["id"]]["message"] == {"raw": "cmF3", "threadId": "t1"}
    box.send_draft(d["id"])
    assert svc.sent == [d["id"]]


def http_error(status, reason="", headers=None):
    resp = {"status": status, **(headers or {})}
    resp = type("R", (dict,), {"status": status, "reason": "x"})(resp)
    body = {"error": {"errors": [{"reason": reason}]}} if reason else {}
    return HttpError(resp, json.dumps(body).encode())


class Flaky:
    def __init__(self, n, error):
        self.n = n
        self.error = error
        self.calls = 0

    def execute(self):
        self.calls += 1
        if self.n:
            self.n -= 1
            raise self.error
        return {"ok": True}


def timed(**kw):
    slept = []
    box = gmail.Mailbox("school", "user@example.edu", FakeService(), sleep=slept.append, **kw)
    return box, slept


def test_sender_is_default_send_as_and_cached():
    svc, box = make()
    svc.send_as = [
        {"sendAsEmail": "user@g.example.edu", "isPrimary": True},
        {"sendAsEmail": "user@example.edu", "isDefault": True},
    ]
    assert box.sender() == "user@example.edu"
    assert box.sender() == "user@example.edu"
    assert svc.send_as_calls == 1


def test_sender_falls_back_to_login_address():
    _, box = make()
    assert box.sender() == "user@example.edu"


def test_backoff_retries_429():
    _, box = make()
    assert box._run(Flaky(2, http_error(429))) == {"ok": True}


@pytest.mark.parametrize("reason", ["rateLimitExceeded", "userRateLimitExceeded"])
def test_retries_403_rate_limit(reason):
    _, box = make()
    req = Flaky(1, http_error(403, reason))
    assert box._run(req) == {"ok": True} and req.calls == 2


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"not json",
        b"[1]",
        b'{"error": 5}',
        b'{"error": {"errors": [{"reason": "forbidden"}]}}',
    ],
)
def test_403_other_or_unparseable_is_not_retried(content):
    _, box = make()
    resp = type("R", (dict,), {"status": 403, "reason": "x"})()
    req = Flaky(1, HttpError(resp, content))
    with pytest.raises(HttpError):
        box._run(req)
    assert req.calls == 1


def test_non_retryable_status_raises_immediately():
    _, box = make()
    req = Flaky(1, http_error(404))
    with pytest.raises(HttpError):
        box._run(req)
    assert req.calls == 1


def test_gives_up_after_tries():
    _, box = make()
    req = Flaky(10, http_error(503))
    with pytest.raises(HttpError):
        box._run(req)
    assert req.calls == 4


def test_full_jitter_sleeps_within_exponential_window():
    seen = []

    def rand(lo, hi):
        seen.append((lo, hi))
        return hi / 2

    box, slept = timed(rand=rand)
    box._run(Flaky(3, http_error(429)))
    assert seen == [(0, 1), (0, 2), (0, 4)]
    assert slept == [0.5, 1.0, 2.0]


def test_retry_after_header_honoured_and_capped():
    box, slept = timed(rand=lambda lo, hi: 0)
    box._run(Flaky(1, http_error(429, headers={"retry-after": "7"})))
    box._run(Flaky(1, http_error(429, headers={"retry-after": "999"})))
    assert slept == [7.0, 32.0]


@pytest.mark.parametrize("hint", ["nan", "inf", "-5"])
def test_unusable_retry_after_falls_back_to_jitter(hint):
    box, slept = timed(rand=lambda lo, hi: hi)
    box._run(Flaky(1, http_error(429, headers={"retry-after": hint})))
    assert slept == [1]


def test_non_numeric_retry_after_falls_back_to_jitter():
    box, slept = timed(rand=lambda lo, hi: hi)
    box._run(Flaky(1, http_error(429, headers={"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"})))
    assert slept == [1]


def test_audit_is_metadata_only_and_private(tmp_path):
    audit.record(
        tmp_path,
        "send",
        account="school",
        id="school:d1",
        to=["b@x"],
        subject="Plan",
        body="SECRET",
    )
    line = (tmp_path / "audit.jsonl").read_text().strip()
    data = json.loads(line)
    assert "body" not in data and data["subject"] == "Plan"
    assert stat.S_IMODE((tmp_path / "audit.jsonl").stat().st_mode) == 0o600


def test_audit_strips_crlf_from_fields(tmp_path):
    audit.record(tmp_path, "draft", subject='a\r\n{"event": "send"}\nb', to=["x\ny@example.com"])
    text = (tmp_path / "audit.jsonl").read_text()
    assert len(text.splitlines()) == 1
    data = json.loads(text)
    assert "\n" not in data["subject"] and "\r" not in data["subject"]
    assert "\n" not in data["to"][0]


def test_audit_never_raises_on_os_error(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    audit.record(blocker / "sub", "send", account="school")
    audit.record(tmp_path / "ro-missing" / "x", "send")


def test_audit_drops_entry_when_write_fails(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise PermissionError("denied")

    monkeypatch.setattr(audit.os, "open", boom)
    audit.record(tmp_path, "send", account="school")
    assert not (tmp_path / "audit.jsonl").exists()
