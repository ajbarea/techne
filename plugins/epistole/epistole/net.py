"""Happy Eyeballs (RFC 8305) for epistole's HTTP clients.

httplib2 and urllib3 try each resolved address in turn and wait out every one that never
answers, so on a network whose IPv6 route is broken a sign-in or Gmail call hangs for minutes.
`install` makes `socket.getaddrinfo` race the addresses first and list the one that connected
first, so both clients connect to it straight away.
"""

from __future__ import annotations

import errno
import selectors
import socket
import time
from typing import Any

ATTEMPT_DELAY = 0.25  # RFC 8305 section 5: the recommended Connection Attempt Delay
RACE_TIMEOUT = 3.0  # past this with no winner, the addresses come back in resolver order

_IN_PROGRESS = {
    errno.EINPROGRESS,
    errno.EWOULDBLOCK,
    errno.EAGAIN,
    getattr(errno, "WSAEWOULDBLOCK", -1),
}
_original = socket.getaddrinfo


def interleave(infos: list[Any]) -> list[Any]:
    """Alternate address families, keeping the resolver's order within each (RFC 8305 4)."""
    queues: dict[int, list[Any]] = {}
    for info in infos:
        queues.setdefault(info[0], []).append(info)
    out: list[Any] = []
    rows = list(queues.values())
    while any(rows):
        for row in rows:
            if row:
                out.append(row.pop(0))
    return out


def race(infos: list[Any], *, delay: float = ATTEMPT_DELAY, timeout: float = RACE_TIMEOUT) -> Any:
    """The sockaddr of the first address to accept a TCP connection, or None.

    A new attempt starts every `delay` seconds, and at once when an open attempt fails.
    """
    pending = interleave(infos)
    sel = selectors.DefaultSelector()
    socks: list[socket.socket] = []
    deadline = time.monotonic() + timeout
    next_start = 0.0
    try:
        while True:
            now = time.monotonic()
            if now >= deadline:
                return None
            if pending and (now >= next_start or not sel.get_map()):
                family, kind, proto, _, addr = pending.pop(0)
                try:
                    sock = socket.socket(family, kind, proto)
                except OSError:
                    continue
                socks.append(sock)
                sock.setblocking(False)
                err = sock.connect_ex(addr)
                if err == 0:
                    return addr
                if err in _IN_PROGRESS:
                    sel.register(sock, selectors.EVENT_WRITE, (sock, addr))
                    next_start = now + delay
                continue
            if not sel.get_map():
                return None
            wait = deadline - now
            if pending:
                wait = min(wait, max(0.0, next_start - now))
            for key, _ in sel.select(wait):
                sock, addr = key.data
                sel.unregister(sock)
                if sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR) == 0:
                    return addr
                next_start = 0.0
    finally:
        sel.close()
        for sock in socks:
            sock.close()


def getaddrinfo(
    host: bytes | str | None,
    port: bytes | str | int | None,
    family: int = 0,
    type: int = 0,
    proto: int = 0,
    flags: int = 0,
) -> list[Any]:
    """socket.getaddrinfo, with the first address to accept a connection listed first."""
    infos = _original(host, port, family, type, proto, flags)
    if flags & socket.AI_PASSIVE or not host or not port:
        return infos
    candidates: dict[Any, Any] = {}
    for info in infos:
        if info[1] == socket.SOCK_STREAM:
            candidates.setdefault(info[4], info)
    if len(candidates) < 2:
        return infos
    winner = race(list(candidates.values()))
    if winner is None:
        return infos
    return sorted(infos, key=lambda info: info[4] != winner)


def install() -> None:
    """Route this process's address lookups through `getaddrinfo`. Safe to call twice."""
    socket.getaddrinfo = getaddrinfo  # ty: ignore[invalid-assignment]
