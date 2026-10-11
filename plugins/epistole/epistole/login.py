"""`epistole-login`: import the Google client, sign accounts in, and report status."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from epistole import auth, config

USAGE = "usage: epistole-login --status | epistole-login [--client FILE] [alias]"


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="epistole-login", usage=USAGE, add_help=True)
    p.add_argument("alias", nargs="?", help="account name; a new name adds the account")
    p.add_argument("--client", metavar="FILE", help="import the downloaded Desktop app client JSON")
    p.add_argument("--status", action="store_true", help="show client and sign-in state")
    return p


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
    if args.status == bool(args.alias or args.client) or not (
        args.status or args.alias or args.client
    ):
        print(USAGE, file=sys.stderr)
        return 2
    base = config.home()
    try:
        if args.status:
            report = auth.status(base)
            print("\n".join(auth.status_lines(report)))
            return 0 if report.all_ok else 1
        if args.client:
            auth.import_client(base, Path(args.client).expanduser())
            print("epistole: Google OAuth client saved.")
        if args.alias:
            cfg = config.load(base) if (base / "accounts.toml").is_file() else None
            email = auth.login(
                base, cfg, args.alias, flow_factory=flow_factory, profile_email=profile_email
            )
            print(f"epistole: {args.alias} signed in as {email}.")
    except (auth.LoginRequired, config.ConfigError) as exc:
        print(f"epistole: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
