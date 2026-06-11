"""Tests for network discovery and connectivity helpers."""

from __future__ import annotations

import asyncio
import socket

import pytest

from habitron_client import discovery
from habitron_client.exceptions import HabitronConnectionError
from sim import Reply, build_response, running


def _descriptor() -> bytes:
    data = bytearray(30)
    data[0:4] = b"\x00\x00\x00\xf7"
    data[5], data[6], data[7] = 3, 4, 5  # version "5.4.3"
    data[8], data[9] = ord("A"), ord("1")  # type "A-1"
    data[20:24] = b"1234"  # serial
    data[24:30] = bytes.fromhex("aabbccddeeff")  # mac
    return bytes(data)


class _FakeHub(asyncio.DatagramProtocol):
    def __init__(self, response: bytes) -> None:
        self._response = response
        self._transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        assert isinstance(transport, asyncio.DatagramTransport)
        self._transport = transport

    def datagram_received(self, data: bytes, addr: tuple[str | int, ...]) -> None:
        assert self._transport is not None
        self._transport.sendto(self._response, addr)


def test_get_own_ip_returns_ipv4() -> None:
    ip = discovery.get_own_ip()
    assert ip.count(".") == 3


def test_get_host_ip_resolves_localhost() -> None:
    assert asyncio.run(discovery.get_host_ip("localhost")) in {"127.0.0.1"}


def test_get_host_ip_unknown_host_raises() -> None:
    with pytest.raises(HabitronConnectionError):
        asyncio.run(discovery.get_host_ip("nonexistent.invalid."))


def test_test_connection_invalid_host_raises_connection_error() -> None:
    with pytest.raises(HabitronConnectionError):
        asyncio.run(discovery.test_connection("nonexistent.invalid."))


def test_parse_descriptor_valid() -> None:
    parsed = discovery._parse_descriptor(_descriptor(), "10.0.0.5")
    assert parsed == {
        "type": "A-1",
        "version": "5.4.3",
        "serial": "1234",
        "mac": "AA:BB:CC:DD:EE:FF",
        "ip": "10.0.0.5",
    }


def test_parse_descriptor_rejects_bad_header() -> None:
    assert discovery._parse_descriptor(b"\x00" * 30, "10.0.0.5") is None
    assert discovery._parse_descriptor(_descriptor(), "0.0.0.0") is None
    assert discovery._parse_descriptor(b"short", "10.0.0.5") is None


def test_query_smarthub_success(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> dict[str, str]:
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: _FakeHub(_descriptor()), local_addr=("127.0.0.1", 0)
        )
        sock = transport.get_extra_info("socket")
        monkeypatch.setattr(discovery, "_DISCOVERY_PORT", sock.getsockname()[1])
        try:
            return await discovery.query_smarthub("127.0.0.1")
        finally:
            transport.close()

    info = asyncio.run(scenario())
    assert info["name"] == "SmartHub_AABBCCDDEEFF"
    assert info["mac"] == "AA:BB:CC:DD:EE:FF"
    assert info["ip"] == "127.0.0.1"


def test_query_smarthub_no_response_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> dict[str, str]:
        # Point at a port with no responder; expect a timeout -> {}.
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("127.0.0.1", 0))
        dead_port = sock.getsockname()[1]
        sock.close()
        monkeypatch.setattr(discovery, "_DISCOVERY_PORT", dead_port)
        monkeypatch.setattr(discovery, "_QUERY_TIMEOUT", 0.2)
        return await discovery.query_smarthub("127.0.0.1")

    assert asyncio.run(scenario()) == {}


def test_discover_smarthubs_timeout_returns_empty() -> None:
    assert asyncio.run(discovery.discover_smarthubs(timeout=0.2)) == []


def test_test_connection_no_server_returns_false() -> None:
    # Nothing listening on the default SmartHub port -> (False, "").
    ok, name = asyncio.run(discovery.test_connection("localhost"))
    assert ok is False
    assert name == ""


class _FakeTransport:
    """Minimal datagram-transport stand-in for discover_smarthubs tests."""

    def sendto(self, *args: object, **kwargs: object) -> None:
        pass

    def close(self) -> None:
        pass


def test_discover_smarthubs_socket_error_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        loop = asyncio.get_running_loop()

        async def boom(*args: object, **kwargs: object) -> object:
            raise OSError("cannot open socket")

        monkeypatch.setattr(loop, "create_datagram_endpoint", boom)
        with pytest.raises(HabitronConnectionError):
            await discovery.discover_smarthubs(timeout=0.1)

    asyncio.run(scenario())


def test_discover_smarthubs_zero_timeout_returns_empty() -> None:
    # Deadline already passed on the first loop iteration -> break, no results.
    assert asyncio.run(discovery.discover_smarthubs(timeout=0.0)) == []


def test_discover_smarthubs_collects_responses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> list[dict[str, str]]:
        loop = asyncio.get_running_loop()

        async def fake_endpoint(
            protocol_factory: object, **kwargs: object
        ) -> tuple[_FakeTransport, discovery._DiscoveryProtocol]:
            proto = protocol_factory()  # type: ignore[operator]
            # One valid hub, an exact duplicate (deduped), and junk (ignored).
            proto.queue.put_nowait((_descriptor(), ("10.0.0.7", 30718)))
            proto.queue.put_nowait((_descriptor(), ("10.0.0.7", 30718)))
            proto.queue.put_nowait((b"junk", ("10.0.0.8", 30718)))
            return _FakeTransport(), proto

        monkeypatch.setattr(discovery, "get_own_ip", lambda: "127.0.0.1")
        monkeypatch.setattr(loop, "create_datagram_endpoint", fake_endpoint)
        return await discovery.discover_smarthubs(timeout=0.3)

    found = asyncio.run(scenario())
    assert len(found) == 1
    assert found[0]["ip"] == "10.0.0.7"
    assert found[0]["mac"] == "AA:BB:CC:DD:EE:FF"


def test_query_smarthub_unresolvable_host_raises() -> None:
    with pytest.raises(HabitronConnectionError):
        asyncio.run(discovery.query_smarthub("nonexistent.invalid."))


def test_query_smarthub_bad_descriptor_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> dict[str, str]:
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: _FakeHub(b"not-a-descriptor"), local_addr=("127.0.0.1", 0)
        )
        sock = transport.get_extra_info("socket")
        monkeypatch.setattr(discovery, "_DISCOVERY_PORT", sock.getsockname()[1])
        try:
            return await discovery.query_smarthub("127.0.0.1")
        finally:
            transport.close()

    assert asyncio.run(scenario()) == {}


def test_query_smarthub_hostname_lookup_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> dict[str, str]:
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: _FakeHub(_descriptor()), local_addr=("127.0.0.1", 0)
        )
        sock = transport.get_extra_info("socket")
        monkeypatch.setattr(discovery, "_DISCOVERY_PORT", sock.getsockname()[1])

        async def no_ptr(*args: object, **kwargs: object) -> object:
            raise socket.gaierror("no reverse record")

        monkeypatch.setattr(loop, "getnameinfo", no_ptr)
        try:
            return await discovery.query_smarthub("127.0.0.1")
        finally:
            transport.close()

    info = asyncio.run(scenario())
    assert info["hostname"] == ""
    assert info["name"] == "SmartHub_AABBCCDDEEFF"


def test_test_connection_success(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> tuple[bool, str]:
        async with running(Reply(data=build_response(b"OK"), close=False)) as sim:
            real_client = discovery.HabitronClient
            monkeypatch.setattr(
                discovery,
                "HabitronClient",
                lambda host: real_client(host, sim.port),
            )

            async def fake_query(ip: str) -> dict[str, str]:
                return {"name": "SmartHub_X"}

            monkeypatch.setattr(discovery, "query_smarthub", fake_query)
            return await discovery.test_connection("localhost")

    ok, name = asyncio.run(scenario())
    assert ok is True
    assert name == "SmartHub_X"


def test_test_connection_status_not_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> tuple[bool, str]:
        async with running(Reply(data=build_response(b"NO"), close=False)) as sim:
            real_client = discovery.HabitronClient
            monkeypatch.setattr(
                discovery,
                "HabitronClient",
                lambda host: real_client(host, sim.port),
            )
            return await discovery.test_connection("localhost")

    ok, name = asyncio.run(scenario())
    assert ok is False
    assert name == ""
