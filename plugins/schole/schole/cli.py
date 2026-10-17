"""schole-login and schole-sweep: sign in once in a real browser, then read the site headless."""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
import time
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from schole import config, d2l

LOGIN_WAIT = 600  # seconds the login window waits for the user to finish signing in
POLL = 3
ARGS = ["--password-store=basic"]  # one cookie store for the headed and headless runs
NEEDS_LOGIN = "needs login: run !schole-login in Claude Code, or schole-login in a terminal"
SESSION = "session-cookies.json"  # in the profile; Chromium drops session cookies on close
CHROMIUM = "uv run --no-project --with playwright==1.63.0 playwright install chromium"


def browser_failure(exc: Exception) -> str:
    """A Playwright failure as one line naming the fix."""
    text = str(exc)
    if "Executable doesn't exist" in text:
        return f"Chromium is not installed for schole; run: {CHROMIUM}"
    if "ProcessSingleton" in text or "SingletonLock" in text:
        return "the browser profile is in use; close the schole-login window and try again"
    if "closed" in text.lower():
        return "the browser window closed before the site answered"
    return f"the browser failed: {text.splitlines()[0][:200] if text else type(exc).__name__}"


def is_browser_error(exc: Exception) -> bool:
    return type(exc).__module__.startswith("playwright")


@contextlib.contextmanager
def browser(base: Path, site: str, headless: bool) -> Iterator[Any]:
    from playwright.sync_api import sync_playwright  # ty: ignore[unresolved-import]

    profile = config.profile(base)
    saved = profile / SESSION
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(profile), headless=headless, channel="chromium", args=ARGS
        )
        try:
            restored = restore_session(ctx, saved, site)
            yield ctx
        finally:
            try:
                if restored:
                    keep_session(ctx, saved, site)
            finally:
                ctx.close()


def site_session(cookies: Any, site: str) -> list[dict]:
    """The cookies that end with the browser and that the site itself receives."""
    host = urlsplit(site).hostname or ""
    out = []
    for c in cookies if isinstance(cookies, list) else []:
        if not isinstance(c, dict) or c.get("expires", -1) != -1:
            continue
        domain = str(c.get("domain", "")).lstrip(".")
        if domain and (host == domain or host.endswith("." + domain)):
            out.append(c)
    return out


def restore_session(ctx: Any, path: Path, site: str) -> bool:
    """Add back the site's session cookies the last run kept. False when the browser refused
    them, so the caller keeps the file rather than overwrite it with an empty session."""
    try:
        cookies = site_session(json.loads(path.read_text()), site)
    except (OSError, ValueError):
        return True
    if not cookies:
        return True
    try:
        ctx.add_cookies(cookies)
    except Exception as exc:
        if not is_browser_error(exc):
            raise
        print(
            f"schole: could not restore the saved sign-in: {browser_failure(exc)}", file=sys.stderr
        )
        return False
    return True


def keep_session(ctx: Any, path: Path, site: str) -> None:
    """Save the site's session cookies, readable by the user only. A closed browser saves none."""
    try:
        cookies = site_session(ctx.cookies(), site)
    except Exception as exc:
        if not is_browser_error(exc):
            raise
        return
    try:
        config.write_private(path, json.dumps(cookies))
    except OSError as exc:
        print(f"schole: could not save the sign-in to {path}: {exc}", file=sys.stderr)


def getter(ctx: Any, site: str) -> d2l.Get:
    def get(path: str) -> tuple[int, str]:
        r = ctx.request.get(site + path, max_redirects=0, timeout=30_000)
        return r.status, r.text()

    return d2l.guarded(get)


def signed_in(ctx: Any, site: str) -> bool:
    try:
        d2l.courses(getter(ctx, site), "")
    except d2l.NoSession:
        return False
    return True


def update_config(base: Path, args: argparse.Namespace) -> None:
    """Save any of --site, --term and --timezone, keeping the saved values for the rest."""
    if not (args.site or args.term is not None or args.timezone):
        return
    old = None
    with contextlib.suppress(config.ConfigError):
        old = config.load(base)
    if args.site:
        site = config.check_site(args.site)
    elif old is not None:
        site = old.site
    else:
        raise config.ConfigError("give --site the first time, with --term.")
    cfg = config.Config(
        site,
        args.term if args.term is not None else (old.term if old else ""),
        config.check_zone(args.timezone) if args.timezone else (old.timezone if old else None),
    )
    config.save(base, cfg)


def login(args: argparse.Namespace) -> int:
    base = config.home()
    update_config(base, args)
    cfg = config.load(base)
    if args.status:
        with browser(base, cfg.site, headless=True) as ctx:
            ok = signed_in(ctx, cfg.site)
        print(f"{cfg.site}  term {cfg.term or '(all)'}  {'signed in' if ok else NEEDS_LOGIN}")
        return 0 if ok else 3
    print(f"Sign in to {cfg.site} in the browser window that opens. schole never types into it.")
    print(f"This command waits up to {LOGIN_WAIT // 60} minutes, then closes the window.")
    with browser(base, cfg.site, headless=False) as ctx:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(cfg.site + "/d2l/home")
        deadline = time.monotonic() + LOGIN_WAIT
        while time.monotonic() < deadline:
            try:
                if signed_in(ctx, cfg.site):
                    print(f"signed in to {cfg.site}")
                    return 0
                if not ctx.pages:
                    print("the browser window closed before sign-in finished.", file=sys.stderr)
                    return 1
            except d2l.SiteError:
                pass
            time.sleep(POLL)
    print("not signed in before the wait ran out; run schole-login again.", file=sys.stderr)
    return 1


def sweep(args: argparse.Namespace) -> int:
    base = config.home()
    cfg = config.load(base)
    tz = config.zone(cfg)
    now = datetime.now(tz)
    since = datetime.fromtimestamp(args.since, tz) if args.since else now - timedelta(days=1)
    with browser(base, cfg.site, headless=True) as ctx:
        try:
            lines = d2l.sweep(getter(ctx, cfg.site), cfg.term, since, now, tz)
        except d2l.NoSession:
            print(NEEDS_LOGIN, file=sys.stderr)
            return 3
        except d2l.SiteError as exc:
            print(f"schole: the course site failed ({exc}); try again later.", file=sys.stderr)
            return 4
    courses = sum(1 for line in lines if line.startswith(("OK ", "APIFAIL ")))
    print(f"{cfg.site} since {since.strftime('%a %b %d %Y %H:%M %Z')}: {courses} courses")
    print("\n".join(lines))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="schole")
    sub = parser.add_subparsers(dest="cmd", required=True)
    lg = sub.add_parser("login", help="sign in once in a browser window")
    lg.add_argument("--site", help="the course site's https origin")
    lg.add_argument("--term", help="text every current course code contains, e.g. 2261")
    lg.add_argument("--timezone", help="IANA zone for printed times")
    lg.add_argument("--status", action="store_true", help="check the sign-in without a window")
    sw = sub.add_parser("sweep", help="what changed since a time, and what is due")
    sw.add_argument("--since", type=int, help="epoch seconds; default 24 hours ago")
    args = parser.parse_args(argv)
    try:
        return login(args) if args.cmd == "login" else sweep(args)
    except config.ConfigError as exc:
        print(f"schole: {exc}", file=sys.stderr)
        return 1
    except d2l.SiteError as exc:
        print(f"schole: the course site failed ({exc}); try again later.", file=sys.stderr)
        return 4
    except Exception as exc:
        if not is_browser_error(exc):
            raise
        print(f"schole: {browser_failure(exc)}", file=sys.stderr)
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
