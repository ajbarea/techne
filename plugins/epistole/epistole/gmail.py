"""One Gmail mailbox: the API calls epistole makes, retried on rate limits and server errors."""

from __future__ import annotations

import json
import math
import random
import time
from collections.abc import Callable
from typing import Any

from googleapiclient.errors import HttpError

RETRY = {429, 500, 502, 503}
RATE_REASONS = {"rateLimitExceeded", "userRateLimitExceeded"}
MAX_RETRY_AFTER = 32.0
HEADERS = ["From", "To", "Cc", "Subject", "Date", "Message-ID", "References"]


class Mailbox:
    def __init__(
        self,
        alias: str,
        address: str,
        service: Any,
        sleep: Callable[[float], None] = time.sleep,
        rand: Callable[[float, float], float] = random.uniform,
    ) -> None:
        self.alias = alias
        self.address = address
        self.users = service.users()
        self.sleep = sleep
        self.rand = rand
        self._sender: str | None = None

    @staticmethod
    def _retryable(exc: HttpError) -> bool:
        status = exc.resp.status
        if status in RETRY:
            return True
        if status != 403:
            return False
        try:
            errors = json.loads(exc.content)["error"]["errors"]
            return any(e.get("reason") in RATE_REASONS for e in errors)
        except (ValueError, KeyError, TypeError, AttributeError):
            return False

    def _delay(self, exc: HttpError, attempt: int) -> float:
        try:
            hinted = float(exc.resp.get("retry-after"))
        except (TypeError, ValueError, AttributeError):
            hinted = math.nan
        if math.isfinite(hinted) and hinted >= 0:
            return min(hinted, MAX_RETRY_AFTER)
        return self.rand(0, 2**attempt)

    def _run(self, request: Any, tries: int = 4) -> Any:
        for attempt in range(tries):
            try:
                return request.execute()
            except HttpError as exc:
                if not self._retryable(exc) or attempt == tries - 1:
                    raise
                self.sleep(self._delay(exc, attempt))
        raise AssertionError("unreachable")

    def search(self, query: str, max_results: int, page_token: str | None):
        res = self._run(
            self.users.messages().list(
                userId="me", q=query, maxResults=max_results, pageToken=page_token
            )
        )
        out = [
            self._run(
                self.users.messages().get(
                    userId="me", id=m["id"], format="metadata", metadataHeaders=HEADERS
                )
            )
            for m in res.get("messages", [])
        ]
        return out, res.get("nextPageToken")

    def sender(self) -> str:
        if self._sender is None:
            res = self._run(self.users.settings().sendAs().list(userId="me"))
            default = [a["sendAsEmail"] for a in res.get("sendAs", []) if a.get("isDefault")]
            self._sender = default[0] if default else self.address
        return self._sender

    def thread(self, thread_id: str) -> dict:
        return self._run(self.users.threads().get(userId="me", id=thread_id, format="full"))

    def message(self, message_id: str) -> dict:
        return self._run(self.users.messages().get(userId="me", id=message_id, format="full"))

    def _body(self, raw: str, thread_id: str | None) -> dict:
        message: dict[str, str] = {"raw": raw}
        if thread_id:
            message["threadId"] = thread_id
        return {"message": message}

    def create_draft(self, raw: str, thread_id: str | None) -> dict:
        return self._run(self.users.drafts().create(userId="me", body=self._body(raw, thread_id)))

    def update_draft(self, draft_id: str, raw: str, thread_id: str | None) -> dict:
        body = {"id": draft_id, **self._body(raw, thread_id)}
        return self._run(self.users.drafts().update(userId="me", id=draft_id, body=body))

    def get_draft(self, draft_id: str) -> dict:
        return self._run(self.users.drafts().get(userId="me", id=draft_id, format="full"))

    def send_draft(self, draft_id: str) -> dict:
        return self._run(self.users.drafts().send(userId="me", body={"id": draft_id}))

    def attachment(self, message_id: str, attachment_id: str) -> bytes:
        import base64

        res = self._run(
            self.users.messages()
            .attachments()
            .get(userId="me", messageId=message_id, id=attachment_id)
        )
        data = res["data"]
        return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
