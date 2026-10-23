"""`epistole-login`: import the Google client, sign accounts in, and report status."""

from __future__ import annotations

import argparse
import os
import shlex
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from google.auth.exceptions import TransportError

from epistole import auth, config, net
from epistole.gmail import is_known_network

USAGE = "usage: epistole-login --status | epistole-login [--client FILE] [alias]"


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="epistole-login", usage=USAGE, add_help=True)
    p.add_argument("alias", nargs="?", help="account name; a new name adds the account")
    p.add_argument("--client", metavar="FILE", help="import the downloaded Desktop app client JSON")
    p.add_argument("--status", action="store_true", help="show client and sign-in state")
    return p


def _again(alias: str | None) -> str:
    """The retry command. A shell reads a leading `!` as history, so a terminal gets the path."""
    name = alias or "<alias>"
    path = os.environ.get("EPISTOLE_LOGIN")
    terminal = f", or `{shlex.quote(path)} {name}` in a terminal" if path else ""
    return f"run `!epistole-login {name}` in Claude Code{terminal}"


def _explain(exc: Exception, alias: str | None) -> str:
    again = _again(alias)
    kind = type(exc).__name__
    if isinstance(exc, Warning):  # oauthlib: the granted scopes differ from the requested ones
        return (
            f"a permission box was unticked, so nothing was saved; {again} "
            "and keep both Gmail boxes ticked."
        )
    if kind == "WSGITimeoutError":
        return f"timed out after 5 minutes waiting for the browser sign-in; {again}."
    if kind == "AccessDeniedError":
        return f"access was denied in the browser, so nothing was saved; {again} and allow access."
    if isinstance(exc, TransportError) or is_known_network(exc):
        return (
            f"the browser step finished, but this computer could not reach Google ({kind}), "
            f"so nothing was saved. Check the network, VPN or firewall, then {again}."
        )
    return f"sign-in failed ({kind}); {again}. Nothing was saved."


def main(
    argv: list[str] | None = None,
    *,
    flow_factory: Callable[[], Any] | None = None,
    profile_email: Callable[[Any], str] | None = None,
) -> int:
    try:
        args = _parser().parse_args(sys.argv[1:] if argv is None else argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    given = args.alias is not None or args.client is not None
    if args.status == given or not (args.status or given):
        print(USAGE, file=sys.stderr)
        return 2
    net.install()
    try:
        base = config.home()
        if args.status:
            report = auth.status(base)
            print("\n".join(auth.status_lines(report)))
            return 0 if report.all_ok else 1
        if args.client:
            auth.import_client(base, config.caller_dir() / Path(args.client).expanduser())
            print("epistole: Google OAuth client saved.")
        if args.alias is not None:
            cfg = (
                config.load(base, allow_empty=True) if (base / "accounts.toml").is_file() else None
            )
            email = auth.login(
                base, cfg, args.alias, flow_factory=flow_factory, profile_email=profile_email
            )
            print(f"epistole: {args.alias} signed in as {email}.")
    except (auth.LoginRequired, config.ConfigError) as exc:
        print(f"epistole: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # one line and the fix, never a traceback or a payload
        print(f"epistole: {_explain(exc, args.alias)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
