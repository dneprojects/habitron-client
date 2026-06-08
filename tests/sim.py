"""Async bus simulator and frame helpers for the test suite.

The simulator is a small ``asyncio`` TCP server that reads each wrapped command
frame a client sends and answers with a scripted :class:`Reply`. Responses are
built from the library's own framing primitives, so the fixtures are valid wire
frames rather than recorded captures (which would require real hardware).
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass, field

from habitron_client._protocol import (
    HEADER_SIZE,
    TRAILER_SIZE,
    calc_crc,
    wrap_command,
)

#: Length of the fixed prefix that :func:`wrap_command` prepends.
PREFIX_LEN = len(wrap_command(b"")) - TRAILER_SIZE


def unwrap(frame: bytes) -> bytes:
    """Return the raw command payload from a wrapped request frame."""
    return frame[PREFIX_LEN:-TRAILER_SIZE]


def build_response(payload: bytes, crc: int | None = None) -> bytes:
    """Build a full response frame: header + payload + CRC trailer + postfix."""
    header = bytearray(HEADER_SIZE)
    header[28] = len(payload) & 0xFF
    header[29] = (len(payload) >> 8) & 0xFF
    if crc is None:
        crc = calc_crc(payload)
    trailer = bytes((crc & 0xFF, (crc >> 8) & 0xFF, 0x3F))
    return bytes(header) + payload + trailer


@dataclass
class Reply:
    """How the simulator should answer one request.

    Attributes:
        data: Bytes to send back, or ``None`` to send nothing.
        close: Whether to close the connection after handling the request.
        delay: Seconds to wait before replying (to trigger client timeouts).
    """

    data: bytes | None = None
    close: bool = True
    delay: float = 0.0


@dataclass
class BusSimulator:
    """A scripted asyncio TCP SmartHub stand-in."""

    default: Reply = field(default_factory=lambda: Reply(close=True))
    replies: list[Reply] = field(default_factory=list)
    requests: list[bytes] = field(default_factory=list)
    host: str = "127.0.0.1"
    port: int = 0
    _server: asyncio.AbstractServer | None = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, self.host, 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            while True:
                try:
                    frame = await _read_frame(reader)
                except asyncio.IncompleteReadError:
                    break
                self.requests.append(frame)
                reply = self.replies.pop(0) if self.replies else self.default
                if reply.delay:
                    await asyncio.sleep(reply.delay)
                if reply.data is not None:
                    try:
                        writer.write(reply.data)
                        await writer.drain()
                    except (ConnectionError, OSError):
                        break
                if reply.close:
                    break
        finally:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()


async def _read_frame(reader: asyncio.StreamReader) -> bytes:
    """Read one wrapped command frame (length byte lives at index 1)."""
    head = await reader.readexactly(2)
    total = head[1]
    rest = await reader.readexactly(total - 2) if total > 2 else b""
    return head + rest


@contextlib.asynccontextmanager
async def running(
    default: Reply | None = None, replies: Iterable[Reply] | None = None
) -> AsyncIterator[BusSimulator]:
    """Start a :class:`BusSimulator`, yield it, and stop it on exit."""
    sim = BusSimulator(
        default=default if default is not None else Reply(close=True),
        replies=list(replies or []),
    )
    await sim.start()
    try:
        yield sim
    finally:
        await sim.stop()
