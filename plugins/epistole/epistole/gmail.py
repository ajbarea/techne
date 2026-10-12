"""One Gmail mailbox: the API calls epistole makes, retried on rate limits and server errors."""

from __future__ import annotations

import base64
import errno
import json
import math
import random
import socket
import ssl
import time
from collections.abc import Callable
from typing import Any

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaInMemoryUpload

try:
    import httplib2
except ImportError:  # pragma: no cover
    httplib2 = None


class SendOutcomeUnknown(RuntimeError):
    """The send request failed after Gmail may have accepted it."""


class DraftOutcomeUnknown(RuntimeError):
    """The create-draft request failed after Gmail may have accepted it."""


RETRY = {429, 500, 502, 503, 504}
RATE_REASONS = {"rateLimitExceeded", "userRateLimitExceeded"}
MAX_RETRY_AFTER = 32.0
SLEEP_BUDGET = 60.0
DRAFT_UNKNOWN = "draft may exist; check Drafts before retrying"
UPLOAD_ABOVE = 5 * 1024 * 1024  # bytes; Google suggests simple upload only up to 5 MB
SEND_UNKNOWN = "send outcome unknown; check Sent before retrying"
KNOWN_NETWORK: tuple[type[BaseException], ...] = (
    TimeoutError,
    ConnectionError,
    ssl.SSLError,
    socket.gaierror,
)
if httplib2 is not None:
    KNOWN_NETWORK += (httplib2.HttpLib2Error,)
NETWORK_ERRNOS = frozenset(
    {
        errno.ENETUNREACH,
        errno.ENETDOWN,
        errno.ENETRESET,
        errno.EHOSTUNREACH,
        errno.EHOSTDOWN,
        errno.ETIMEDOUT,
    }
)
# What a request's execute() can raise from the transport: any OSError (TLS, DNS, routing) except
# the local-file errors it cannot get from the network.
NETWORK_ERRORS: tuple[type[BaseException], ...] = (OSError, *KNOWN_NETWORK)
LOCAL_FILE_ERRORS = (FileNotFoundError, FileExistsError, IsADirectoryError, NotADirectoryError)


def is_network(exc: BaseException) -> bool:
    """Whether exc may have come from the transport, so a send's outcome is unknown."""
    return isinstance(exc, NETWORK_ERRORS) and not isinstance(exc, LOCAL_FILE_ERRORS)


def is_known_network(exc: BaseException) -> bool:
    """Whether exc is certainly a network failure, not a local file error."""
    if isinstance(exc, KNOWN_NETWORK):
        return True
    return isinstance(exc, OSError) and exc.errno in NETWORK_ERRNOS


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
    def _retryable(exc: HttpError, idempotent: bool) -> bool:
        status = exc.resp.status
        if status == 429:
            return True
        if status in RETRY:
            return idempotent
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

    def _pause(self, exc: BaseException, delay: float, budget: list[float]) -> None:
        if budget[0] + delay > SLEEP_BUDGET:
            raise exc
        self.sleep(delay)
        budget[0] += delay

    def _run(
        self,
        request: Any,
        tries: int = 4,
        idempotent: bool = True,
        budget: list[float] | None = None,
    ) -> Any:
        """Execute with backoff. Non-idempotent requests retry only when Gmail rejected them.

        `budget` is the seconds slept so far; pass one list to share a sleep cap across the
        requests of a single operation. Without it the request gets its own.
        """
        if tries < 1:
            raise ValueError("tries must be at least 1")
        budget = [0.0] if budget is None else budget
        for attempt in range(tries):
            try:
                return request.execute()
            except HttpError as exc:
                if not self._retryable(exc, idempotent) or attempt == tries - 1:
                    raise
                self._pause(exc, self._delay(exc, attempt), budget)
            except NETWORK_ERRORS as exc:
                if not is_network(exc) or not idempotent or attempt == tries - 1:
                    raise
                self._pause(exc, self.rand(0, 2**attempt), budget)
        raise AssertionError("unreachable")

    def search(
        self, query: str, max_results: int, page_token: str | None
    ) -> tuple[list[dict], str | None]:
        """List, then fetch metadata per hit.

        Quota: list 5 units, each get 20 units, 6,000 units/min/user.
        """
        budget = [0.0]
        res = self._run(
            self.users.messages().list(
                userId="me", q=query, maxResults=max_results, pageToken=page_token
            ),
            budget=budget,
        )
        out = []
        for m in res.get("messages", []):
            req = self.users.messages().get(
                userId="me", id=m["id"], format="metadata", metadataHeaders=HEADERS
            )
            try:
                out.append(self._run(req, budget=budget))
            except HttpError as exc:
                if exc.resp.status != 404:
                    raise
        return out, res.get("nextPageToken")

    def fetch_sender(self, tries: int = 1) -> str:
        """Gmail's default send-as address. Raises if Gmail does not say."""
        res = self._run(self.users.settings().sendAs().list(userId="me"), tries=tries)
        default = [a.get("sendAsEmail") for a in res.get("sendAs", []) if a.get("isDefault")]
        found = next((d for d in default if d), None)
        if found is None:
            raise LookupError("Gmail lists no default send-as address")
        return found

    def sender(self) -> str:
        """Default send-as address; the login address when Gmail will not say."""
        if self._sender is None:
            try:
                self._sender = self.fetch_sender(tries=4)
            except (HttpError, LookupError, KeyError, TypeError, AttributeError, *NETWORK_ERRORS):
                self._sender = self.address
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
        req = self.users.drafts().create(userId="me", body=self._body(raw, thread_id))
        try:
            return self._run(req, idempotent=False)
        except HttpError as exc:
            if exc.resp.status < 500:
                raise
            raise DraftOutcomeUnknown(DRAFT_UNKNOWN) from exc
        except NETWORK_ERRORS as exc:
            if not is_network(exc):
                raise
            raise DraftOutcomeUnknown(DRAFT_UNKNOWN) from exc

    def update_draft(self, draft_id: str, raw: str, thread_id: str | None) -> dict:
        body = {"id": draft_id, **self._body(raw, thread_id)}
        return self._run(self.users.drafts().update(userId="me", id=draft_id, body=body))

    def get_draft(self, draft_id: str) -> dict:
        return self._run(self.users.drafts().get(userId="me", id=draft_id, format="full"))

    def get_raw_draft(self, draft_id: str) -> dict:
        """The draft's message: its id, threadId and the base64url RFC 822 bytes in raw."""
        res = self._run(self.users.drafts().get(userId="me", id=draft_id, format="raw"))
        return res.get("message", {})

    def send_draft(self, draft_id: str, raw: str, thread_id: str | None) -> dict:
        """Send raw as the draft's content. drafts.send sends the message supplied in the body,
        so what goes out is raw, whatever the stored draft holds by then.

        A 404 is an unknown outcome: httplib2 resends a POST after a dropped connection, and the
        resend finds the draft gone if the first one was sent.
        """
        body: dict[str, Any] = {"id": draft_id, **self._body(raw, thread_id)}
        data = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
        if len(data) > UPLOAD_ABOVE:
            # Large messages go through the media-upload endpoint (message/*, up to 35 MB).
            del body["message"]["raw"]
            if not body["message"]:
                del body["message"]
            media = MediaInMemoryUpload(data, mimetype="message/rfc822", resumable=True)
            req = self.users.drafts().send(userId="me", body=body, media_body=media)
        else:
            req = self.users.drafts().send(userId="me", body=body)
        try:
            return self._run(req, idempotent=False)
        except HttpError as exc:
            if exc.resp.status < 500 and exc.resp.status != 404:
                raise
            raise SendOutcomeUnknown(SEND_UNKNOWN) from exc
        except NETWORK_ERRORS as exc:
            if not is_network(exc):
                raise
            raise SendOutcomeUnknown(SEND_UNKNOWN) from exc

    def attachment(self, message_id: str, attachment_id: str) -> bytes:
        res = self._run(
            self.users.messages()
            .attachments()
            .get(userId="me", messageId=message_id, id=attachment_id)
        )
        data = res.get("data", "")
        return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
