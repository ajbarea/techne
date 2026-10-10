"""OAuth for each account: the one-time browser login, and loading or refreshing its token."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from epistole.config import Config

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
]


class LoginRequired(Exception):
    pass


def token_path(base: Path, alias: str) -> Path:
    return base / "tokens" / f"{alias}.json"


def client_secret_path(base: Path) -> Path:
    return base / "client_secret.json"


def save_token(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(data)
    path.chmod(0o600)


def _hint(alias: str) -> str:
    return f"run `!epistole-login {alias}` in Claude Code to sign in"


def load_credentials(base: Path, alias: str) -> Credentials:
    path = token_path(base, alias)
    if not path.is_file():
        raise LoginRequired(f"account {alias!r} is not signed in: {_hint(alias)}.")
    creds = Credentials.from_authorized_user_file(str(path), SCOPES)
    if not creds.valid:
        try:
            creds.refresh(Request())
        except RefreshError as exc:
            raise LoginRequired(
                f"account {alias!r} sign-in expired ({exc}): {_hint(alias)}."
            ) from exc
        save_token(path, creds.to_json())
    return creds


def _default_flow(base: Path) -> Any:
    from google_auth_oauthlib.flow import InstalledAppFlow

    secret = client_secret_path(base)
    if not secret.is_file():
        raise LoginRequired(f"{secret} not found; download the Desktop OAuth client JSON there.")
    return InstalledAppFlow.from_client_secrets_file(str(secret), SCOPES)


def _default_profile_email(creds: Any) -> str:
    from googleapiclient.discovery import build

    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    return service.users().getProfile(userId="me").execute()["emailAddress"]


def login(
    base: Path,
    cfg: Config,
    alias: str,
    *,
    flow_factory: Callable[[], Any] | None = None,
    profile_email: Callable[[Any], str] | None = None,
) -> str:
    if alias not in cfg.accounts:
        raise LoginRequired(f"no account {alias!r} in accounts.toml.")
    flow = flow_factory() if flow_factory else _default_flow(base)
    creds = flow.run_local_server(
        host="127.0.0.1",
        port=0,
        open_browser=True,
        authorization_prompt_message="If no browser opens, visit this URL to sign in:\n{url}",
        success_message="epistole is signed in. You can close this tab.",
    )
    email = (profile_email or _default_profile_email)(creds).lower()
    expected = cfg.accounts[alias].address
    if email != expected:
        raise LoginRequired(
            f"signed in as {email}, but {alias!r} is {expected} in accounts.toml; "
            "nothing was saved. Sign in with the right account."
        )
    save_token(token_path(base, alias), creds.to_json())
    return email
