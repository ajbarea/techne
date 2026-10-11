"""Build draft messages and read message bodies, keeping attachments to allowed folders."""

from __future__ import annotations

import base64
import mimetypes
import re
from collections.abc import Iterable
from email.message import EmailMessage
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import NamedTuple

QUOTE_START = re.compile(r"^On .+wrote:\s*$", re.MULTILINE)


class Reply(NamedTuple):
    message_id: str
    references: str
    subject: str


def reply_subject(original: str) -> str:
    return original if re.match(r"(?i)re:", original.strip()) else f"Re: {original}"


def check_attachment(path: str, allowed: tuple[Path, ...], home: Path) -> Path:
    real = Path(path).expanduser().resolve()
    if any(part.startswith(".") for part in real.parts[1:]):
        raise ValueError(f"{path}: hidden files and folders cannot be attached.")
    if real.is_relative_to(home.resolve()):
        raise ValueError(f"{path}: epistole's own files cannot be attached.")
    if not any(real.is_relative_to(d) for d in allowed):
        raise ValueError(f"{path}: not inside an allowed attach_dirs folder.")
    if not real.is_file():
        raise ValueError(f"{path}: not a file.")
    return real


def build(
    *,
    sender: str,
    to: Iterable[str],
    subject: str,
    body: str,
    cc: Iterable[str] = (),
    html: str | None = None,
    attachments: Iterable[Path] = (),
    reply: Reply | None = None,
) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = ", ".join(to)
    cc = list(cc)
    if cc:
        msg["Cc"] = ", ".join(cc)
    if reply:
        msg["Subject"] = reply_subject(reply.subject)
        msg["In-Reply-To"] = reply.message_id
        refs = reply.references.split()
        if reply.message_id and reply.message_id not in refs:
            refs.append(reply.message_id)
        msg["References"] = " ".join(refs)
    else:
        msg["Subject"] = subject
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")
    for path in attachments:
        ctype, _ = mimetypes.guess_type(path.name)
        maintype, subtype = (ctype or "application/octet-stream").split("/", 1)
        msg.add_attachment(
            path.read_bytes(), maintype=maintype, subtype=subtype, filename=path.name
        )
    return msg


def encode(msg: EmailMessage) -> str:
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()


def headers(payload: dict) -> dict[str, str]:
    return {h["name"].lower(): h["value"] for h in payload.get("headers", [])}


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.out: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        elif tag in ("br", "p", "div", "li", "tr"):
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def _html_to_text(html: str) -> str:
    parser = _Text()
    parser.feed(html)
    text = "".join(parser.out)
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+", " ", text)).strip()


def _decode(data: str) -> str:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "replace")


def _find(payload: dict, mime_type: str) -> str | None:
    if payload.get("mimeType") == mime_type and payload.get("body", {}).get("data"):
        return _decode(payload["body"]["data"])
    for part in payload.get("parts", []):
        found = _find(part, mime_type)
        if found is not None:
            return found
    return None


def body_text(payload: dict) -> str:
    plain = _find(payload, "text/plain")
    if plain is not None:
        return plain
    html = _find(payload, "text/html")
    return _html_to_text(html) if html is not None else ""


def trim_quoted(text: str) -> str:
    match = QUOTE_START.search(text)
    if match:
        text = text[: match.start()]
    lines = [ln for ln in text.splitlines() if not ln.startswith(">")]
    return "\n".join(lines).strip()


def wrap_untrusted(text: str, source: str) -> str:
    return f'<untrusted-email source="{source}">\n{text}\n</untrusted-email>'


def safe_filename(name: str) -> str:
    base = PureWindowsPath(PurePosixPath(name).name).name.lstrip(".")
    base = re.sub(r"[\x00-\x1f]", "", base)
    return base or "attachment"
