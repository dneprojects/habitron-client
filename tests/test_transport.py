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
    HabitronProtocolError,
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


def test_short_acknowledgement_returns_sentinel_not_payload() -> None:
    # A sub-header response is a payload-less ack: the transport must report the
    # b"OK" sentinel, NOT the raw bytes. Returning the raw partial made callers
    # that parse the payload (e.g. the router firmware-file version) treat ack
    # bytes as data. Use a distinctive short payload so the two cases differ.
    async def scenario() -> bytes:
        async with running(Reply(data=b"FN\nXY", close=True)) as sim:
            async with HabitronClient("127.0.0.1", sim.port) as client:
                return await client.get_global_descriptions()

    assert asyncio.run(scenario()) == b"OK"


def test_each_command_uses_a_fresh_connection() -> None:
    # Variant A: one short-lived socket per command. Issuing three requests must
    # open three separate connections to the hub. A persistent connection would
    # show a single connection — and could carry an orphaned response from one
    # command into the next (the off-by-one desync). Per-command sockets make
    # that structurally impossible: every command starts on a clean stream.
    async def scenario() -> int:
        async with running(
            replies=[
                Reply(data=build_response(b"A")),
                Reply(data=build_response(b"B")),
                Reply(data=build_response(b"C")),
            ]
        ) as sim:
            bus = BusConnection("127.0.0.1", sim.port)
            assert await bus.request(b"\x01", timeout=2.0) == b"A"
            assert await bus.request(b"\x02", timeout=2.0) == b"B"
            assert await bus.request(b"\x03", timeout=2.0) == b"C"
            await bus.close()
            return sim.connections

    assert asyncio.run(scenario()) == 3


def test_bad_marker_raises_protocol_error() -> None:
    # A response that does not start with the 0xA8 marker is garbled / misframed.
    # The transport must reject it as a protocol error instead of handing the
    # bytes to the parsers (where a leading control byte crashed yaml.safe_load).
    async def scenario() -> bytes:
        frame = bytearray(build_response(b"hardware:\n"))
        frame[0] = 0x01  # corrupt the marker, as a desynced read would surface
        async with running(Reply(data=bytes(frame))) as sim:
            async with HabitronClient("127.0.0.1", sim.port) as client:
                return await client.get_global_descriptions()

    with pytest.raises(HabitronProtocolError, match="marker"):
        asyncio.run(scenario())


def test_inconsistent_length_raises_protocol_error() -> None:
    # Total length (bytes 1/2) must match payload length (bytes 28/29). A
    # mismatch means a misframed read; reject it rather than read the wrong
    # number of bytes.
    async def scenario() -> bytes:
        frame = bytearray(build_response(b"PAYLOAD"))
        frame[1] = (frame[1] + 5) & 0xFF  # declared total length now too large
        async with running(Reply(data=bytes(frame))) as sim:
            async with HabitronClient("127.0.0.1", sim.port) as client:
                return await client.get_global_descriptions()

    with pytest.raises(HabitronProtocolError, match="length"):
        asyncio.run(scenario())


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
