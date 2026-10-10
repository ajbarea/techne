"""`epistole-login <alias>`: sign one account in through the browser."""

from __future__ import annotations

import sys

from epistole import auth, config


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: epistole-login <alias>", file=sys.stderr)
        return 2
    base = config.home()
    try:
        email = auth.login(base, config.load(base), args[0])
    except (auth.LoginRequired, config.ConfigError) as exc:
        print(f"epistole: {exc}", file=sys.stderr)
        return 1
    print(f"epistole: {args[0]} signed in as {email}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
