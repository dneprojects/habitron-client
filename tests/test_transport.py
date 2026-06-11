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


def test_default_is_at_most_once() -> None:
    async def scenario() -> int:
        async with running(Reply(data=None, close=True)) as sim:
            async with HabitronClient("127.0.0.1", sim.port) as client:
                with pytest.raises(HabitronConnectionError):
                    await client.get_global_descriptions()
            return len(sim.requests)

    # Default max_attempts=1: a mid-request drop propagates with no retry.
    assert asyncio.run(scenario()) == 1


def test_max_attempts_retries_until_success() -> None:
    async def scenario() -> tuple[bytes, int]:
        replies = [
            Reply(data=None, close=True),  # attempt 1 dropped
            Reply(data=None, close=True),  # attempt 2 dropped
            Reply(data=build_response(b"AGAIN")),  # attempt 3 succeeds
        ]
        async with running(replies=replies) as sim:
            async with HabitronClient("127.0.0.1", sim.port, max_attempts=3) as client:
                result = await client.get_global_descriptions()
            return result, len(sim.requests)

    result, attempts = asyncio.run(scenario())
    assert result == b"AGAIN"
    assert attempts == 3


def test_max_attempts_zero_raises_value_error() -> None:
    with pytest.raises(ValueError, match="max_attempts"):
        HabitronClient("127.0.0.1", 1, max_attempts=0)


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
                # send_only closes the connection immediately after drain(); yield
                # so the simulator coroutine gets a turn to read the frame before
                # we inspect sim.requests (Linux epoll scheduling requires this).
                await asyncio.sleep(0)
            return sim.requests[-1]

    frame = asyncio.run(scenario())
    assert unwrap(frame) == b"\x1e\x01\x01\x01\x0c\x03\x00\x01\x0c\x03"


def test_send_only_swallows_connection_error() -> None:
    async def scenario() -> None:
        # An entered client whose hub is unreachable: send_only must swallow the
        # connection error and return None rather than raising.
        client = HabitronClient("127.0.0.1", _free_port(), connect_timeout=1.0)
        client._entered = True  # simulate post-enter state without a live hub
        await client.send_devregid(5, "ab")
        await client.close()

    asyncio.run(scenario())


def test_aenter_connects_eagerly_and_raises_on_dead_host() -> None:
    async def scenario() -> None:
        with pytest.raises(HabitronConnectionError):
            async with HabitronClient("127.0.0.1", _free_port(), connect_timeout=1.0):
                pass  # body must not run — __aenter__ raises eagerly

    asyncio.run(scenario())


def test_methods_work_after_enter_without_explicit_connect() -> None:
    async def scenario() -> bytes:
        async with running(Reply(data=build_response(b"PAYLOAD"))) as sim:
            async with HabitronClient("127.0.0.1", sim.port) as client:
                return await client.get_global_descriptions()

    assert asyncio.run(scenario()) == b"PAYLOAD"


def test_bus_connection_context_manager() -> None:
    async def scenario() -> bytes:
        async with running(Reply(data=build_response(b"OK"))) as sim:
            async with BusConnection("127.0.0.1", sim.port) as bus:
                return await bus.request(build_frame(GET_MODULES, ()), timeout=2.0)

    assert asyncio.run(scenario()) == b"OK"


def test_wrap_roundtrip_through_simulator() -> None:
    async def scenario() -> bytes:
        async with running(Reply(data=build_response(b"OK"))) as sim:
            async with HabitronClient("127.0.0.1", sim.port) as client:
                await client.hub_restart()
            return sim.requests[-1]

    frame = asyncio.run(scenario())
    assert frame == wrap_command(b"\x3c\x00\x02\x01\x00\x00\x00")
