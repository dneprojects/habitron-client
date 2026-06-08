"""Tests for the async transport: framing, reconnect, timeouts, errors."""

from __future__ import annotations

import asyncio
import socket

import pytest

from habitron_client import HabitronClient
from habitron_client._protocol import build_frame, wrap_command
from habitron_client._transport import BusConnection
from habitron_client.const import GET_MODULES
from habitron_client.exceptions import (
    HabitronBusError,
    HabitronConnectionError,
    HabitronTimeoutError,
)
from sim import Reply, build_response, running, unwrap


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def test_request_returns_payload() -> None:
    async def scenario() -> bytes:
        async with running(Reply(data=build_response(b"PAYLOAD"))) as sim:
            async with HabitronClient("127.0.0.1", sim.port) as client:
                return await client.get_global_descriptions()

    assert asyncio.run(scenario()) == b"PAYLOAD"


def test_request_crc_returns_payload_and_crc() -> None:
    async def scenario() -> tuple[bytes, int]:
        async with running(Reply(data=build_response(b"DATA", crc=0x1234))) as sim:
            async with HabitronClient("127.0.0.1", sim.port) as client:
                return await client.get_compact_status()

    assert asyncio.run(scenario()) == (b"DATA", 0x1234)


def test_short_acknowledgement_returns_partial() -> None:
    async def scenario() -> bytes:
        async with running(Reply(data=b"OK", close=True)) as sim:
            async with HabitronClient("127.0.0.1", sim.port) as client:
                return await client.get_global_descriptions()

    assert asyncio.run(scenario()) == b"OK"


def test_bus_error_is_raised() -> None:
    async def scenario() -> bytes:
        async with running(Reply(data=build_response(b"Error 17"))) as sim:
            async with HabitronClient("127.0.0.1", sim.port) as client:
                return await client.get_smr()

    with pytest.raises(HabitronBusError, match="Error 17"):
        asyncio.run(scenario())


def test_reconnect_after_drop_then_succeeds() -> None:
    async def scenario() -> tuple[bytes, int]:
        replies = [
            Reply(data=None, close=True),  # drop the first attempt mid-exchange
            Reply(data=build_response(b"AGAIN")),
        ]
        async with running(replies=replies) as sim:
            async with HabitronClient("127.0.0.1", sim.port) as client:
                result = await client.get_global_descriptions()
            return result, len(sim.requests)

    result, attempts = asyncio.run(scenario())
    assert result == b"AGAIN"
    assert attempts == 2


def test_persistent_drop_raises_connection_error() -> None:
    async def scenario() -> int:
        async with running(Reply(data=None, close=True)) as sim:
            async with HabitronClient("127.0.0.1", sim.port) as client:
                with pytest.raises(HabitronConnectionError):
                    await client.get_global_descriptions()
            return len(sim.requests)

    assert asyncio.run(scenario()) == 2


def test_timeout_raises_timeout_error() -> None:
    async def scenario() -> None:
        async with running(Reply(data=None, close=False)) as sim:
            bus = BusConnection("127.0.0.1", sim.port, connect_timeout=2.0)
            with pytest.raises(HabitronTimeoutError):
                await bus.request(build_frame(GET_MODULES, ()), timeout=0.3)
            await bus.close()

    asyncio.run(scenario())


def test_connection_refused_raises_connection_error() -> None:
    async def scenario() -> None:
        bus = BusConnection("127.0.0.1", _free_port(), connect_timeout=1.0)
        with pytest.raises(HabitronConnectionError):
            await bus.request(build_frame(GET_MODULES, ()), timeout=1.0)

    asyncio.run(scenario())


def test_send_only_transmits_frame_without_response() -> None:
    async def scenario() -> bytes:
        async with running(Reply(data=None, close=True)) as sim:
            async with HabitronClient("127.0.0.1", sim.port) as client:
                await client.set_output(12, 3, True)
            return sim.requests[-1]

    frame = asyncio.run(scenario())
    assert unwrap(frame) == b"\x1e\x01\x01\x01\x0c\x03\x00\x01\x0c\x03"


def test_send_only_swallows_connection_error() -> None:
    async def scenario() -> None:
        # No server: send_only must not raise.
        client = HabitronClient("127.0.0.1", _free_port(), connect_timeout=1.0)
        await client.send_devregid(5, "ab")
        await client.close()

    asyncio.run(scenario())


def test_wrap_roundtrip_through_simulator() -> None:
    async def scenario() -> bytes:
        async with running(Reply(data=build_response(b"OK"))) as sim:
            async with HabitronClient("127.0.0.1", sim.port) as client:
                await client.hub_restart()
            return sim.requests[-1]

    frame = asyncio.run(scenario())
    assert frame == wrap_command(b"\x3c\x00\x02\x01\x00\x00\x00")
