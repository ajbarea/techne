"""Build draft messages and read message bodies, keeping attachments to allowed folders."""

from __future__ import annotations

import base64
import codecs
import mimetypes
import os
import re
from collections.abc import Iterable
from email.message import EmailMessage
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import NamedTuple

MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024
MAX_FILENAME_BYTES = 255

QUOTE_START = re.compile(r"^On .+wrote:[ \t]*$", re.MULTILINE)
_REPLY_PREFIX = re.compile(r"(?i)re(\[\d+\])?:")
_WRAP_TAG = re.compile(r"<(\s*/?\s*)untrusted-email", re.IGNORECASE)
_CONTROLS = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_BIDI = re.compile("[\u202a-\u202e\u2066-\u2069]")
_RESERVED = {"CON", "PRN", "AUX", "NUL"}
_RESERVED |= {f"COM{n}" for n in range(1, 10)} | {f"LPT{n}" for n in range(1, 10)}
_CHARSET = re.compile(r"charset\s*=\s*[\"']?([\w.:-]+)", re.IGNORECASE)


class Reply(NamedTuple):
    message_id: str
    references: str
    subject: str
    in_reply_to: str = ""


def reply_subject(original: str) -> str:
    original = original.strip()
    return original if _REPLY_PREFIX.match(original) else f"Re: {original}"


def _is_home(real: Path, home: Path) -> bool:
    home_real = home.resolve()
    if not home_real.exists():
        return False
    return any(p.exists() and os.path.samefile(p, home_real) for p in (real, *real.parents))


def check_attachment(path: str, allowed: tuple[Path, ...], home: Path) -> Path:
    given = Path(path).expanduser()
    if not given.is_absolute():
        raise ValueError(f"{path}: give an absolute path.")
    if any(part.startswith(".") for part in given.parts[1:]):
        raise ValueError(f"{path}: hidden files and folders cannot be attached.")
    real = given.resolve()
    if any(part.startswith(".") for part in real.parts[1:]):
        raise ValueError(f"{path}: hidden files and folders cannot be attached.")
    if _is_home(real, home):
        raise ValueError(f"{path}: epistole's own files cannot be attached.")
    if not any(real.is_relative_to(d) for d in allowed):
        raise ValueError(f"{path}: not inside an allowed attach_dirs folder.")
    if not real.is_file():
        raise ValueError(f"{path}: not a file.")
    if real.stat().st_size > MAX_ATTACHMENT_BYTES:
        raise ValueError(f"{path}: over the {MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB limit.")
    return real


def _ids(*values: str) -> list[str]:
    return list(dict.fromkeys(i for v in values for i in v.split()))


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
    if isinstance(to, str) or isinstance(cc, str):
        raise TypeError("to and cc must be lists of addresses, not a string.")
    attachments = list(attachments)
    total = sum(p.stat().st_size for p in attachments)
    if total > MAX_ATTACHMENT_BYTES:
        raise ValueError(
            f"attachments total over the {MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB limit."
        )
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = ", ".join(to)
    cc = list(cc)
    if cc:
        msg["Cc"] = ", ".join(cc)
    if reply:
        msg["Subject"] = reply_subject(reply.subject)
        parent = reply.message_id.strip()
        refs = _ids(reply.references) or _ids(reply.in_reply_to)
        refs = [r for r in refs if r != parent] + ([parent] if parent else [])
        if parent:
            msg["In-Reply-To"] = parent
        if refs:
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


_BLOCKS = {"br", "p", "div", "li", "tr", "table", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6"}
_SKIPPED = ("script", "style", "title")


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.out: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in _SKIPPED:
            self.skip += 1
        elif tag in _BLOCKS:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in _SKIPPED:
            self.skip = max(0, self.skip - 1)
        elif tag in _BLOCKS:
            self.out.append("\n")
        elif tag in ("td", "th"):
            self.out.append(" ")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def _drop_unclosed(html: str) -> str:
    for tag in _SKIPPED:
        html = re.sub(rf"(?is)<{tag}\b[^>]*>(?!.*?</{tag}\s*>)[^<]*", "", html)
    return html


def _html_to_text(html: str) -> str:
    parser = _Text()
    parser.feed(_drop_unclosed(html))
    parser.close()
    text = "".join(parser.out).replace("\xa0", " ")
    return re.sub(r"\n[ \t]*\n(?:[ \t]*\n)+", "\n\n", re.sub(r"[ \t]+", " ", text)).strip()


def _decode(part: dict) -> str:
    data = part["body"]["data"]
    raw = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
    match = _CHARSET.search(headers(part).get("content-type", ""))
    charset = match.group(1) if match else "utf-8"
    try:
        codecs.lookup(charset)
    except LookupError:
        charset = "utf-8"
    return raw.decode(charset, "replace")


def _find(payload: dict, mime_type: str) -> str | None:
    if payload.get("filename") or payload.get("mimeType") == "message/rfc822":
        return None
    if payload.get("mimeType") == mime_type and payload.get("body", {}).get("data"):
        return _decode(payload)
    for part in payload.get("parts", []):
        found = _find(part, mime_type)
        if found is not None:
            return found
    return None


def body_text(payload: dict) -> str:
    plain = _find(payload, "text/plain")
    if plain is not None and plain.strip():
        return plain
    html = _find(payload, "text/html")
    return _html_to_text(html) if html is not None else ""


def _cut_at_attribution(text: str) -> str:
    for match in QUOTE_START.finditer(text):
        if not re.search(r"@|\d", match.group(0)):
            continue
        rest = text[match.end() :].split("\n")
        following = next((ln for ln in rest if ln.strip()), None)
        if following is None or following.lstrip().startswith(">"):
            return text[: match.start()]
    return text


def trim_quoted(text: str) -> str:
    text = _cut_at_attribution(text)
    lines = [ln for ln in text.splitlines() if not ln.startswith(">")]
    return "\n".join(lines).strip()


def wrap_untrusted(text: str, source: str) -> str:
    text = _WRAP_TAG.sub(r"&lt;\1untrusted-email", text)
    return f'<untrusted-email source="{source}">\n{text}\n</untrusted-email>'


def _cap_bytes(name: str) -> str:
    if len(name.encode()) <= MAX_FILENAME_BYTES:
        return name
    suffix = PurePosixPath(name).suffix
    if len(suffix.encode()) > 32:
        suffix = ""
    stem = name[: len(name) - len(suffix)] if suffix else name
    budget = MAX_FILENAME_BYTES - len(suffix.encode())
    return stem.encode()[:budget].decode("utf-8", "ignore") + suffix


def safe_filename(name: str) -> str:
    base = _BIDI.sub("", _CONTROLS.sub("", name))
    base = PurePosixPath(base.replace("\\", "/")).name.strip(" .")
    if base.split(".", 1)[0].strip().upper() in _RESERVED:
        base = f"_{base}"
    base = _cap_bytes(base).strip(" .")
    return base or "attachment"
