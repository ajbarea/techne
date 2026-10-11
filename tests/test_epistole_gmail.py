import json
import stat

import httplib2
import pytest
from epistole import audit, gmail
from epistole_fake import FakeService, http_error
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


# --- fix round 1 ---


def test_sender_falls_back_and_caches_when_send_as_list_fails():
    svc, box = make()
    svc.fail["settings.sendAs.list"] = [http_error(403, "insufficientPermissions")]
    svc.send_as = [{"sendAsEmail": "other@example.edu", "isDefault": True}]
    assert box.sender() == "user@example.edu"
    assert box.sender() == "user@example.edu"
    assert svc.calls.count("settings.sendAs.list") == 1


def test_sender_falls_back_after_persistent_503():
    svc, box = make()
    svc.fail["settings.sendAs.list"] = [http_error(503)] * 4
    assert box.sender() == "user@example.edu"


def test_sender_falls_back_on_missing_email_or_bad_payload():
    svc, box = make()
    svc.send_as = [{"isDefault": True}]
    assert box.sender() == "user@example.edu"
    svc2, box2 = make()
    svc2.send_as = None
    assert box2.sender() == "user@example.edu"


def test_send_draft_not_retried_on_5xx_and_reports_unknown_outcome():
    svc, box = make()
    svc.fail["drafts.send"] = [http_error(500), http_error(500)]
    with pytest.raises(gmail.SendOutcomeUnknown, match="check Sent before retrying"):
        box.send_draft("d1")
    assert svc.calls == ["drafts.send"] and svc.sent == []


def test_send_draft_network_error_reports_unknown_outcome():
    svc, box = make()
    svc.fail["drafts.send"] = [TimeoutError()]
    with pytest.raises(gmail.SendOutcomeUnknown):
        box.send_draft("d1")
    assert svc.calls == ["drafts.send"]


@pytest.mark.parametrize(
    "err",
    [
        http_error(429),
        http_error(403, "userRateLimitExceeded"),
    ],
)
def test_send_draft_retried_when_rejected_before_work(err):
    svc, box = make()
    svc.fail["drafts.send"] = [err]
    box.send_draft("d1")
    assert svc.calls == ["drafts.send", "drafts.send"] and svc.sent == ["d1"]


def test_create_draft_not_retried_on_5xx_but_retried_on_429():
    svc, box = make()
    svc.fail["drafts.create"] = [http_error(503)]
    with pytest.raises(HttpError):
        box.create_draft("cmF3", None)
    assert svc.calls == ["drafts.create"]
    svc.fail["drafts.create"] = [http_error(429)]
    box.create_draft("cmF3", None)
    assert svc.drafts and svc.calls.count("drafts.create") == 3


def test_504_retried_when_idempotent():
    _, box = make()
    req = Flaky(1, http_error(504))
    assert box._run(req) == {"ok": True} and req.calls == 2


@pytest.mark.parametrize(
    "err", [TimeoutError(), ConnectionResetError(), httplib2.ServerNotFoundError("dns")]
)
def test_network_errors_retried_when_idempotent(err):
    _, box = make()
    req = Flaky(1, err)
    assert box._run(req) == {"ok": True} and req.calls == 2


def test_network_error_gives_up_after_tries():
    _, box = make()
    req = Flaky(10, TimeoutError())
    with pytest.raises(TimeoutError):
        box._run(req)
    assert req.calls == 4


def test_network_and_5xx_not_retried_when_not_idempotent():
    _, box = make()
    for err in (TimeoutError(), http_error(500)):
        req = Flaky(1, err)
        with pytest.raises(type(err)):
            box._run(req, idempotent=False)
        assert req.calls == 1


def test_sleep_budget_raises_last_error_when_next_sleep_would_exceed():
    box, slept = timed(rand=lambda lo, hi: 0)
    req = Flaky(10, http_error(429, headers={"retry-after": "32"}))
    with pytest.raises(HttpError):
        box._run(req)
    assert slept == [32.0] and req.calls == 2


def test_sleep_budget_allows_exactly_sixty():
    box, slept = timed(rand=lambda lo, hi: 0)
    req = Flaky(10, http_error(429, headers={"retry-after": "30"}))
    with pytest.raises(HttpError):
        box._run(req, tries=5)
    assert slept == [30.0, 30.0] and req.calls == 3


def test_run_rejects_zero_tries():
    _, box = make()
    with pytest.raises(ValueError):
        box._run(Flaky(0, http_error(429)), tries=0)


def test_search_skips_message_deleted_between_list_and_get():
    svc, box = make()
    svc.search_hits = ["m1", "gone"]
    hits, _ = box.search("x", 10, None)
    assert [h["id"] for h in hits] == ["m1"]


def test_search_still_fails_on_other_errors():
    svc, box = make()
    svc.fail["messages.get"] = [http_error(400)]
    with pytest.raises(HttpError):
        box.search("x", 10, None)


def test_search_paginates():
    svc, box = make()
    for i in (2, 3):
        svc.messages[f"m{i}"] = {"id": f"m{i}", "threadId": "t1"}
    svc.search_hits = ["m1", "m2", "m3"]
    first, tok = box.search("x", 2, None)
    assert [h["id"] for h in first] == ["m1", "m2"] and tok
    second, tok = box.search("x", 2, tok)
    assert [h["id"] for h in second] == ["m3"] and tok is None


def test_attachment_without_data_is_empty():
    svc, box = make()
    svc.attachment_data = ""
    assert box.attachment("m1", "a") == b""


def test_fake_rejects_unknown_format():
    svc = FakeService()
    with pytest.raises(TypeError):
        svc.users().messages().get(userId="me", id="m1", format="metdata")
    with pytest.raises(TypeError):
        svc.users().threads().get(userId="me", id="t", format="raw")


def test_audit_refuses_symlinked_log(tmp_path):
    victim = tmp_path / "victim.txt"
    victim.write_text("keep")
    victim.chmod(0o644)
    base = tmp_path / "base"
    base.mkdir()
    (base / "audit.jsonl").symlink_to(victim)
    audit.record(base, "send", account="school")
    assert victim.read_text() == "keep"
    assert stat.S_IMODE(victim.stat().st_mode) == 0o644


def test_audit_tightens_existing_loose_file_before_writing(tmp_path):
    log = tmp_path / "audit.jsonl"
    log.write_text("")
    log.chmod(0o644)
    audit.record(tmp_path, "send", account="school")
    assert stat.S_IMODE(log.stat().st_mode) == 0o600 and log.read_text()


def test_audit_serialises_non_json_values(tmp_path):
    from pathlib import Path

    audit.record(tmp_path, "draft", attachments=[Path("/x/y.pdf")], to={"a@example.com"})
    data = json.loads((tmp_path / "audit.jsonl").read_text())
    assert data["attachments"] == ["/x/y.pdf"]
