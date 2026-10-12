"""Account-qualified ids, so a thread or draft can never be used in the wrong mailbox."""

from __future__ import annotations

from collections.abc import Iterable


def qualify(alias: str, raw: str) -> str:
    return f"{alias}:{raw}"


def parse(qid: str, aliases: Iterable[str]) -> tuple[str, str]:
    alias, sep, raw = qid.partition(":")
    if not sep or not alias or not raw:
        raise ValueError(f"{qid!r} is not an account-qualified id like 'alias:id'.")
    if alias not in set(aliases):
        raise ValueError(f"{qid!r} names unknown account {alias!r}.")
    return alias, raw


def require(qid: str, account: str, aliases: Iterable[str]) -> str:
    alias, raw = parse(qid, aliases)
    if alias != account:
        raise ValueError(f"{qid!r} belongs to {alias!r}, not {account!r}.")
    return raw


def resolve(qid: str, account: str | None, aliases: Iterable[str]) -> tuple[str, str]:
    """The (alias, raw id) of qid; an account other than None or "" must match the id's alias."""
    aliases = list(aliases)
    if account:
        return account, require(qid, account, aliases)
    return parse(qid, aliases)
