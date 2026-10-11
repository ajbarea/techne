"""A tiny stand-in for the googleapiclient Gmail service: chained calls ending in .execute()."""

from __future__ import annotations


class _Req:
    def __init__(self, fn):
        self.fn = fn

    def execute(self):
        return self.fn()


class _Messages:
    def __init__(self, svc):
        self.svc = svc

    def list(self, userId, q, maxResults, pageToken=None):
        return _Req(
            lambda: {
                "messages": [
                    {"id": m, "threadId": self.svc.messages[m]["threadId"]}
                    for m in self.svc.search_hits[:maxResults]
                ]
            }
        )

    def get(self, userId, id, format="full", metadataHeaders=None):
        return _Req(lambda: self.svc.messages[id])

    def attachments(self):
        svc = self.svc

        class _A:
            def get(self, userId, messageId, id):
                return _Req(lambda: {"data": svc.attachment_data})

        return _A()


class _Threads:
    def __init__(self, svc):
        self.svc = svc

    def get(self, userId, id, format="full"):
        return _Req(lambda: self.svc.threads[id])


class _Drafts:
    def __init__(self, svc):
        self.svc = svc

    def create(self, userId, body):
        def run():
            did = f"d{len(self.svc.drafts) + 1}"
            self.svc.drafts[did] = body
            return {"id": did, "message": {"id": "m-" + did}}

        return _Req(run)

    def update(self, userId, id, body):
        def run():
            self.svc.drafts[id] = body
            return {"id": id}

        return _Req(run)

    def get(self, userId, id, format="full"):
        return _Req(lambda: self.svc.draft_views[id])

    def send(self, userId, body):
        def run():
            self.svc.sent.append(body["id"])
            return {"id": "sent-" + body["id"]}

        return _Req(run)


class _SendAs:
    def __init__(self, svc):
        self.svc = svc

    def list(self, userId):
        def run():
            self.svc.send_as_calls += 1
            return {"sendAs": self.svc.send_as}

        return _Req(run)


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

    def users(self):
        return _Users(self)
