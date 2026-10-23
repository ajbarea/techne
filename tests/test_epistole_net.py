import socket
import time

import pytest
from epistole import login, net, server

V4 = socket.AF_INET
V6 = socket.AF_INET6
TCP = socket.SOCK_STREAM
BLACKHOLE = ("192.0.2.1", 9)  # TEST-NET-1 (RFC 5737): never answers, or is unreachable at once


@pytest.fixture(autouse=True)
def restore_getaddrinfo(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", socket.getaddrinfo)


@pytest.fixture
def listener():
    sock = socket.socket(V4, TCP)
    sock.bind(("127.0.0.1", 0))
    sock.listen(8)
    yield sock.getsockname()
    sock.close()


@pytest.fixture
def refused():
    sock = socket.socket(V4, TCP)
    sock.bind(("127.0.0.1", 0))
    addr = sock.getsockname()
    sock.close()  # nothing listens on this port now
    return addr


def info(addr, family=V4, kind=TCP):
    return (family, kind, 6, "", addr)


def test_interleave_alternates_families_in_resolver_order():
    rows = [info(("a",), V6), info(("b",), V6), info(("c",), V6), info(("x",), V4)]
    assert [r[4][0] for r in net.interleave(rows)] == ["a", "x", "b", "c"]
    assert net.interleave([]) == []


def test_race_skips_a_hanging_address_within_the_attempt_delay(listener):
    start = time.monotonic()
    winner = net.race([info(BLACKHOLE), info(listener)], timeout=3)
    assert winner == listener
    assert time.monotonic() - start < 2  # trying each address in turn would wait the full 3s


def test_race_moves_past_a_refused_address(refused, listener):
    assert net.race([info(refused), info(listener)], delay=5, timeout=3) == listener


def test_race_starts_the_next_address_at_once_when_one_fails(refused, listener):
    # The blackhole is still open when the refusal lands, so only an immediate restart wins.
    rows = [info(BLACKHOLE), info(refused), info(listener)]
    assert net.race(rows, delay=1, timeout=1.8) == listener


def test_race_with_no_reachable_address_is_none(refused):
    assert net.race([info(refused), info(refused)], timeout=2) is None
    assert net.race([], timeout=1) is None


def test_getaddrinfo_lists_the_reachable_address_first(monkeypatch, listener):
    rows = [info(BLACKHOLE), info(BLACKHOLE, kind=socket.SOCK_DGRAM), info(listener)]
    monkeypatch.setattr(net, "_original", lambda *a: list(rows))
    out = net.getaddrinfo("gmail.googleapis.com", 443, 0, TCP)
    assert out[0] == info(listener) and sorted(out) == sorted(rows)


@pytest.mark.parametrize(
    ("host", "port", "flags", "rows"),
    [
        ("example.com", 443, 0, [info(BLACKHOLE)]),
        ("example.com", 443, socket.AI_PASSIVE, [info(BLACKHOLE), info(("192.0.2.2", 9))]),
        (None, 443, 0, [info(BLACKHOLE), info(("192.0.2.2", 9))]),
        ("example.com", 0, 0, [info(BLACKHOLE), info(("192.0.2.2", 9))]),
        ("example.com", 443, 0, [info(BLACKHOLE), info(BLACKHOLE, kind=socket.SOCK_DGRAM)]),
    ],
)
def test_getaddrinfo_does_not_race_what_it_cannot_reorder(monkeypatch, host, port, flags, rows):
    monkeypatch.setattr(net, "_original", lambda *a: list(rows))
    monkeypatch.setattr(net, "race", lambda *a, **k: pytest.fail("raced"))
    assert net.getaddrinfo(host, port, 0, 0, 0, flags) == rows


def test_getaddrinfo_keeps_the_resolver_order_when_nothing_connects(monkeypatch):
    rows = [info(BLACKHOLE), info(("192.0.2.2", 9))]
    monkeypatch.setattr(net, "_original", lambda *a: list(rows))
    monkeypatch.setattr(net, "race", lambda *a, **k: None)
    assert net.getaddrinfo("example.com", 443) == rows


def test_login_entry_point_installs_the_resolver(tmp_path, monkeypatch):
    monkeypatch.setenv("EPISTOLE_HOME", str(tmp_path))
    login.main(["--status"])
    assert socket.getaddrinfo is net.getaddrinfo


def test_server_entry_point_installs_the_resolver(monkeypatch):
    class App:
        def run(self, transport):
            assert socket.getaddrinfo is net.getaddrinfo

    monkeypatch.setattr(server, "build", lambda: App())
    server.main()
    assert socket.getaddrinfo is net.getaddrinfo


@pytest.mark.parametrize("exc", [TimeoutError(), ConnectionResetError(), socket.gaierror()])
def test_network_failure_after_the_browser_names_the_network(monkeypatch, exc):
    monkeypatch.delenv("EPISTOLE_LOGIN", raising=False)
    msg = login._explain(exc, "rit")
    assert "could not reach Google" in msg and "`!epistole-login rit` in Claude Code" in msg


def test_retry_hint_gives_a_terminal_the_full_path(monkeypatch):
    monkeypatch.setenv("EPISTOLE_LOGIN", "/opt/epistole/bin/epistole-login")
    msg = login._explain(ValueError(), "rit")
    assert "`/opt/epistole/bin/epistole-login rit` in a terminal" in msg
    assert "sign-in failed (ValueError)" in msg
