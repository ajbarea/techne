"""A tiny stand-in for the googleapiclient Gmail service: chained calls ending in .execute().

Error injection: `svc.fail["drafts.send"] = [HttpError(...), TimeoutError()]` makes the next
executions of that method raise those, one per call, then behave normally. Names are
`messages.list`, `messages.get`, `messages.attachments.get`, `threads.get`, `drafts.create`,
`drafts.update`, `drafts.get`, `drafts.send`, `settings.sendAs.list`. Every execution is
recorded in `svc.calls`.
"""

from __future__ import annotations

import json

from googleapiclient.errors import HttpError

FORMATS = {"full", "metadata", "minimal", "raw"}
THREAD_FORMATS = {"full", "metadata", "minimal"}


def http_error(status: int, reason: str = "", headers: dict | None = None) -> HttpError:
    resp = type("R", (dict,), {"status": status, "reason": "x"})(headers or {})
    body = {"error": {"errors": [{"reason": reason}]}} if reason else {}
    return HttpError(resp, json.dumps(body).encode())


def _check_format(value: str, allowed: set[str]) -> None:
    if value not in allowed:
        raise TypeError(
            f'Parameter "format" value "{value}" is not an allowed value in "{sorted(allowed)}"'
        )


class _Req:
    def __init__(self, svc, name, fn):
        self.svc = svc
        self.name = name
        self.fn = fn

    def execute(self):
        self.svc.calls.append(self.name)
        queue = self.svc.fail.get(self.name)
        if queue:
            raise queue.pop(0)
        return self.fn()


class _Messages:
    def __init__(self, svc):
        self.svc = svc

    def list(self, userId, q, maxResults, pageToken=None):
        def run():
            start = int(pageToken or 0)
            ids = self.svc.search_hits[start : start + maxResults]
            out = {
                "messages": [
                    {"id": m, "threadId": self.svc.messages.get(m, {}).get("threadId", "t-" + m)}
                    for m in ids
                ]
            }
            if start + maxResults < len(self.svc.search_hits):
                out["nextPageToken"] = str(start + maxResults)
            return out

        return _Req(self.svc, "messages.list", run)

    def get(self, userId, id, format="full", metadataHeaders=None):
        _check_format(format, FORMATS)

        def run():
            if id not in self.svc.messages:
                raise http_error(404)
            return self.svc.messages[id]

        return _Req(self.svc, "messages.get", run)

    def attachments(self):
        svc = self.svc

        class _A:
            def get(self, userId, messageId, id):
                return _Req(svc, "messages.attachments.get", lambda: {"data": svc.attachment_data})

        return _A()


class _Threads:
    def __init__(self, svc):
        self.svc = svc

    def get(self, userId, id, format="full"):
        _check_format(format, THREAD_FORMATS)
        return _Req(self.svc, "threads.get", lambda: self.svc.threads[id])


class _Drafts:
    def __init__(self, svc):
        self.svc = svc

    def create(self, userId, body):
        def run():
            did = f"d{len(self.svc.drafts) + 1}"
            self.svc.drafts[did] = body
            return {"id": did, "message": {"id": "m-" + did}}

        return _Req(self.svc, "drafts.create", run)

    def update(self, userId, id, body):
        def run():
            self.svc.drafts[id] = body
            return {"id": id}

        return _Req(self.svc, "drafts.update", run)

    def get(self, userId, id, format="full"):
        _check_format(format, FORMATS)
        return _Req(self.svc, "drafts.get", lambda: self.svc.draft_views[id])

    def send(self, userId, body):
        def run():
            self.svc.sent.append(body["id"])
            return {"id": "sent-" + body["id"]}

        return _Req(self.svc, "drafts.send", run)


class _SendAs:
    def __init__(self, svc):
        self.svc = svc

    def list(self, userId):
        def run():
            self.svc.send_as_calls += 1
            return {"sendAs": self.svc.send_as}

        return _Req(self.svc, "settings.sendAs.list", run)


class _Settings:
    def __init__(self, svc):
        self.svc = svc

    def sendAs(self):
        return _SendAs(self.svc)


class _Users:
    def __init__(self, svc):
        self.svc = svc

    def settings(self):
        return _Settings(self.svc)

    def messages(self):
        return _Messages(self.svc)

    def threads(self):
        return _Threads(self.svc)

    def drafts(self):
        return _Drafts(self.svc)


class FakeService:
    def __init__(self):
        self.messages: dict[str, dict] = {}
        self.threads: dict[str, dict] = {}
        self.drafts: dict[str, dict] = {}
        self.draft_views: dict[str, dict] = {}
        self.search_hits: list[str] = []
        self.sent: list[str] = []
        self.attachment_data = ""
        self.send_as: list[dict] = []
        self.send_as_calls = 0
        self.fail: dict[str, list[BaseException]] = {}
        self.calls: list[str] = []

    def users(self):
        return _Users(self)
