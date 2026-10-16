"""Who counts as "the device itself" (owner auto-sign-in, setup, approvals): loopback, plus
MIMI_LOCAL_PEERS for a container's bridge gateway - and nothing else."""

from __future__ import annotations

import pytest
from starlette.requests import Request

from mimi.app import MAIN_PORT, is_local

GATEWAY = "172.31.76.1"


def req(client: str, host: str = "localhost:7600", origin: str | None = None, port: int = MAIN_PORT) -> Request:
    headers = [(b"host", host.encode())]
    if origin:
        headers.append((b"origin", origin.encode()))
    return Request({"type": "http", "method": "GET", "path": "/api/bootstrap", "query_string": b"", "scheme": "http",
                    "server": ("172.31.76.2", port), "client": (client, 51515), "headers": headers})


@pytest.fixture(autouse=True)
def no_peers(monkeypatch):
    monkeypatch.delenv("MIMI_LOCAL_PEERS", raising=False)


def test_loopback_is_local_by_default():
    assert is_local(req("127.0.0.1"))
    assert is_local(req("::1", host="[::1]:7600"))


def test_gateway_is_not_local_unless_listed():
    assert not is_local(req(GATEWAY))


def test_listed_gateway_is_local(monkeypatch):
    monkeypatch.setenv("MIMI_LOCAL_PEERS", GATEWAY)
    assert is_local(req(GATEWAY))
    assert is_local(req(GATEWAY, host="127.0.0.1:7600"))


def test_listed_peer_still_needs_a_loopback_host_and_origin(monkeypatch):
    monkeypatch.setenv("MIMI_LOCAL_PEERS", GATEWAY)
    assert not is_local(req(GATEWAY, host="192.168.1.20:7600"))  # someone browsing to the machine's LAN address
    assert not is_local(req(GATEWAY, host="evil.example:7600"))  # DNS rebinding
    assert not is_local(req(GATEWAY, origin="https://evil.example"))  # another site's page
    assert is_local(req(GATEWAY, origin="http://localhost:7600"))


def test_other_addresses_are_never_local(monkeypatch):
    monkeypatch.setenv("MIMI_LOCAL_PEERS", GATEWAY)
    assert not is_local(req("172.31.76.3"))  # another container on the network
    assert not is_local(req("192.168.1.50"))  # a LAN client
    assert not is_local(req(GATEWAY, port=8443))  # the phone-sharing listener is never "the device"


def test_cidr_and_lists(monkeypatch):
    monkeypatch.setenv("MIMI_LOCAL_PEERS", "10.0.0.1, 172.31.76.0/30")
    assert is_local(req("172.31.76.1")) and is_local(req("10.0.0.1"))
    assert not is_local(req("172.31.76.5"))


def test_garbage_is_ignored(monkeypatch):
    monkeypatch.setenv("MIMI_LOCAL_PEERS", "not-an-ip, ,")
    assert not is_local(req(GATEWAY))
    assert is_local(req("127.0.0.1"))
