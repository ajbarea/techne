"""OAuth for each account: the one-time browser login, and loading or refreshing its token."""

from __future__ import annotations

import functools
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple

from google.auth.exceptions import RefreshError, TransportError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from epistole import config
from epistole.config import Config, client_secret_path

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
]


CLIENT_KEYS = ("client_id", "client_secret", "auth_uri", "token_uri")
NO_CLIENT = (
    "No Google OAuth client yet. Create a Desktop app client (see the epistole setup guide), "
    "then run `!epistole-login --client <downloaded.json> {alias}`."
)


class LoginRequired(Exception):
    def __init__(self, message: str, reason: str | None = None):
        super().__init__(message)
        self.reason = reason or message


def token_path(base: Path, alias: str) -> Path:
    return base / "tokens" / f"{alias}.json"


def save_token(path: Path, data: str) -> None:
    config.write_private(path, data)


def _hint(alias: str) -> str:
    return f"run `!epistole-login {alias}` in Claude Code to sign in"


STATUS_TIMEOUT = 10  # seconds per account for the token refresh a status check may trigger
LOGIN_TIMEOUT = 30  # seconds for the address lookup that ends a sign-in


def load_credentials(base: Path, alias: str, *, timeout: float | None = None) -> Credentials:
    path = token_path(base, alias)
    if not path.is_file():
        if not client_secret_path(base).is_file():
            raise LoginRequired(NO_CLIENT.format(alias=alias), "no token")
        raise LoginRequired(f"account {alias!r} is not signed in: {_hint(alias)}.", "no token")
    try:
        creds = Credentials.from_authorized_user_file(str(path), SCOPES)
    except (ValueError, AttributeError, TypeError) as exc:
        raise LoginRequired(
            f"account {alias!r} token is unreadable: {_hint(alias)}.", "unreadable token"
        ) from exc
    if not creds.valid:
        try:
            creds.refresh(functools.partial(Request(), timeout=timeout) if timeout else Request())
        except RefreshError as exc:
            raise LoginRequired(
                f"account {alias!r} sign-in expired ({exc}): {_hint(alias)}.",
                "sign-in expired or revoked",
            ) from exc
        save_token(path, creds.to_json())
    return creds


def _default_flow(base: Path, alias: str) -> Any:
    from google_auth_oauthlib.flow import InstalledAppFlow

    secret = client_secret_path(base)
    if not secret.is_file():
        raise LoginRequired(NO_CLIENT.format(alias=alias), "no client")
    return InstalledAppFlow.from_client_secrets_file(str(secret), SCOPES)


def _default_profile_email(creds: Any) -> str:
    from epistole.gmail import service

    gmail = service(creds, timeout=LOGIN_TIMEOUT)
    return gmail.users().getProfile(userId="me").execute()["emailAddress"]


def login(
    base: Path,
    cfg: Config | None,
    alias: str,
    *,
    flow_factory: Callable[[], Any] | None = None,
    profile_email: Callable[[Any], str] | None = None,
) -> str:
    """Sign alias in. A known alias is verified against its address; a new one is recorded."""
    known = cfg.accounts.get(alias) if cfg else None
    if known is None:
        config.check_alias(alias)
    flow = flow_factory() if flow_factory else _default_flow(base, alias)
    hint = {"login_hint": known.address} if known else {}
    creds = flow.run_local_server(
        host="127.0.0.1",
        port=0,
        timeout_seconds=300,
        open_browser=True,
        prompt="select_account",
        **hint,
        authorization_prompt_message="If no browser opens, visit this URL to sign in:\n{url}",
        success_message="Sign-in received. Return to the terminal to confirm the account.",
    )
    email = (profile_email or _default_profile_email)(creds).lower()
    # The browser wait can be long and another login may have changed accounts.toml meanwhile.
    now = config.load(base, allow_empty=True) if (base / "accounts.toml").is_file() else None
    known = now.accounts.get(alias) if now else None
    if known:
        if email != known.address:
            raise LoginRequired(
                f"signed in as {email}, but {alias!r} is {known.address} in accounts.toml; "
                "nothing was saved. Sign in with the right account."
            )
        save_token(token_path(base, alias), creds.to_json())
        return email
    owner = next(
        (a for a, acc in (now.accounts if now else {}).items() if acc.address == email), None
    )
    if owner:
        raise LoginRequired(
            f"{email} is already recorded as {owner!r}; nothing was saved. "
            f"Sign in with a different Google account, or run `!epistole-login {owner}`."
        )
    # Record the alias first: it fails if the alias appeared, so no token lands under it.
    config.add_account(base, alias, email)
    save_token(token_path(base, alias), creds.to_json())
    return email


def import_client(base: Path, src: Path) -> None:
    """Validate a downloaded Desktop-app client JSON and keep a private copy. Never prints it."""
    if not src.is_file():
        raise LoginRequired(f"{src} not found; give the path of the downloaded client JSON.")
    if src.stat().st_size > 65_536:
        raise LoginRequired(f"{src} is too large to be a Google OAuth client file.")
    try:
        text = src.read_text()
        data = json.loads(text)
    except (ValueError, OSError):  # includes UnicodeDecodeError
        raise LoginRequired(f"{src} is not JSON; download the client's JSON file again.") from None
    if isinstance(data, dict) and "installed" not in data and "web" in data:
        raise LoginRequired(
            f"{src} is a Web application client. Create a Desktop app client "
            "(Clients, Create client, Application type: Desktop app) and download that JSON."
        )
    inner = data.get("installed") if isinstance(data, dict) else None
    if not isinstance(inner, dict) or not all(
        isinstance(inner.get(k), str) and inner[k] for k in CLIENT_KEYS
    ):
        raise LoginRequired(
            f"{src} is not a Desktop app client file: it needs an 'installed' entry with "
            f"{', '.join(CLIENT_KEYS)}. Google shows the client secret only in the dialog "
            "after the client is created: download the JSON from that dialog, or on the "
            "client's page add a new client secret and download from its dialog."
        )
    config.write_private(client_secret_path(base), text)


class Row(NamedTuple):
    alias: str
    address: str
    ok: bool
    detail: str
    creds: Any = None  # the loaded credentials when ok, so a caller need not load them again


class Report(NamedTuple):
    client: bool
    rows: list[Row]

    @property
    def all_ok(self) -> bool:
        return bool(self.rows) and all(r.ok for r in self.rows)


def status(base: Path) -> Report:
    """Client and per-account sign-in state. Loads each token (refreshing if needed); no browser."""
    client = client_secret_path(base).is_file()
    if not (base / "accounts.toml").is_file():
        return Report(client, [])
    rows: list[Row] = []
    for alias, acct in config.load(base, allow_empty=True).accounts.items():
        try:
            creds = load_credentials(base, alias, timeout=STATUS_TIMEOUT)
            rows.append(Row(alias, acct.address, True, "signed in", creds))
        except LoginRequired as exc:
            detail = f"needs login: {exc.reason}; {_hint(alias)}"
            rows.append(Row(alias, acct.address, False, detail))
        except TransportError:
            rows.append(Row(alias, acct.address, False, "could not check (network error)"))
    return Report(client, rows)


def status_lines(report: Report) -> list[str]:
    head = (
        "client: present"
        if report.client
        else "client: missing. " + NO_CLIENT.format(alias="<alias>")
    )
    if not report.rows:
        return [head, "no accounts yet; add one with `!epistole-login <alias>`."]
    return [head, *(f"{r.alias}  {r.address}  {r.detail}" for r in report.rows)]
