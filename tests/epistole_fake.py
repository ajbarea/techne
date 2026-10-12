"""A tiny stand-in for the googleapiclient Gmail service: chained calls ending in .execute().

Error injection: `svc.fail["drafts.send"] = [HttpError(...), TimeoutError()]` makes the next
executions of that method raise those, one per call, then behave normally. A None entry lets
that call succeed. Method names: messages.list, messages.get, messages.attachments.get,
threads.get, drafts.create, drafts.update, drafts.get, drafts.send, settings.sendAs.list.
Every execution is recorded in `svc.calls`. `svc.after[name] = fn` runs fn once, after that
method has computed its result (a concurrent edit landing between two calls).

Drafts: `drafts.get(format="raw")` and `drafts.send` work on `svc.drafts`, as Gmail does;
`format="full"` returns `svc.draft_views`. `drafts.send` delivers the supplied `message.raw`
if the body has one, else the stored draft, records it in `svc.delivered`, and deletes the draft.
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
            err = queue.pop(0)
            if err is not None:
                raise err
        result = self.fn()
        hook = self.svc.after.pop(self.name, None)
        if hook is not None:
            hook()
        return result


class _Messages:
    def __init__(self, svc):
        self.svc = svc

    def list(self, userId, q, maxResults, pageToken=None):
        def run():
            try:
                start = int(pageToken or 0)
            except ValueError:
                raise http_error(400, "invalidArgument") from None
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

        def run():
            if format != "raw":
                return self.svc.draft_views[id]
            if id not in self.svc.drafts:
                raise http_error(404)
            stored = self.svc.drafts[id]["message"]
            message = {"id": "m-" + id, "raw": stored["raw"]}
            if stored.get("threadId"):
                message["threadId"] = stored["threadId"]
            return {"id": id, "message": message}

        return _Req(self.svc, "drafts.get", run)

    def send(self, userId, body):
        def run():
            did = body["id"]
            if did not in self.svc.drafts:
                raise http_error(404)
            supplied = body.get("message", {}).get("raw")
            self.svc.delivered.append(supplied or self.svc.drafts[did]["message"]["raw"])
            self.svc.sent.append(did)
            del self.svc.drafts[did]
            return {"id": "sent-" + did}

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
        self.delivered: list[str] = []
        self.after: dict = {}
        self.attachment_data = ""
        self.send_as: list[dict] = []
        self.send_as_calls = 0
        self.fail: dict[str, list[BaseException]] = {}
        self.calls: list[str] = []

    def users(self):
        return _Users(self)
