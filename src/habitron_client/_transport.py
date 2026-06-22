"""Async TCP transport for the Habitron SmartHub.

Each command runs on its **own short-lived TCP connection**: connect, send,
read the response, close. The SmartHub protocol is strictly request/response
with no multiplexing, and the hub serves one connection at a time. Opening a
fresh socket per command — exactly as the original synchronous client did —
makes a desynchronised read stream *structurally impossible*: every command
starts on a clean stream, and any unread bytes die with the closed socket. A
lock still serialises commands so overlapping callers cannot run two
connections against the single-client hub at once.

(The earlier design kept one persistent connection. A single command that was
written but whose response was never fully read — e.g. an exchange cancelled
from the outside — left the stream permanently shifted by one frame, so every
later read returned the *previous* command's response until the connection was
reset. Per-command sockets remove that failure mode entirely.)

Frame validation
----------------
A valid response begins with the marker byte ``0xA8``, followed by a
little-endian 2-byte total length (low byte first); the payload length is
carried at offsets 28/29. The marker and a length-consistency check turn a
garbled response into a clean :class:`HabitronProtocolError` instead of letting
unexpected bytes reach the parsers.

Short-acknowledgement handling
------------------------------
When the hub answers a command with fewer than ``HEADER_SIZE`` bytes it closes
the connection immediately (surfacing as ``IncompleteReadError`` with a non-empty
``partial``). This is a payload-less acknowledgement, reported as the sentinel
``b"OK"`` exactly as the original synchronous client did. The raw partial bytes
are deliberately *not* returned: callers that parse the payload (e.g. the router
firmware-file version query, which short-acks when no update file is staged)
would otherwise treat acknowledgement bytes as data.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from types import TracebackType

from ._protocol import (
    HEADER_SIZE,
    LEN_HI_INDEX,
    LEN_LO_INDEX,
    TRAILER_SIZE,
    wrap_command,
)
from .exceptions import (
    HabitronConnectionError,
    HabitronError,
    HabitronProtocolError,
    HabitronTimeoutError,
)

_LOGGER = logging.getLogger(__name__)

DEFAULT_PORT: int = 7777
DEFAULT_CONNECT_TIMEOUT: float = 10.0

#: First byte of every valid SmartHub response frame.
RESPONSE_MARKER: int = 0xA8


class BusConnection:
    """A serialised bus client that uses a fresh socket per command."""

    def __init__(
        self,
        host: str,
        port: int = DEFAULT_PORT,
        *,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        max_attempts: int = 1,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        self._host = host
        self._port = port
        self._connect_timeout = connect_timeout
        self._max_attempts = max_attempts
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> BusConnection:
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()

    async def connect(self) -> None:
        """Probe reachability by opening and immediately closing a socket.

        There is no persistent connection to keep open; this exists so callers
        (and ``async with``) can fail fast on an unreachable host, preserving
        the test-before-setup behaviour.
        """
        async with self._lock:
            _, writer = await self._open()
            await self._close(writer)

    async def close(self) -> None:
        """No-op: each command owns and closes its own socket."""

    async def request(self, payload: bytes, *, timeout: float) -> bytes:
        """Send a command and return the response payload bytes."""
        body, _ = await self._round_trip(wrap_command(payload), timeout, with_crc=False)
        return body

    async def request_crc(self, payload: bytes, *, timeout: float) -> tuple[bytes, int]:
        """Send a command and return the response payload and its trailing CRC."""
        return await self._round_trip(wrap_command(payload), timeout, with_crc=True)

    async def send_only(self, payload: bytes) -> None:
        """Fire-and-forget a command without awaiting a response."""
        frame = wrap_command(payload)
        async with self._lock:
            writer: asyncio.StreamWriter | None = None
            try:
                _, writer = await self._open()
                writer.write(frame)
                await writer.drain()
            except (OSError, HabitronError) as exc:
                _LOGGER.warning("send_only failed: %s", exc)
            finally:
                if writer is not None:
                    await self._close(writer)

    async def _round_trip(
        self, frame: bytes, timeout: float, *, with_crc: bool
    ) -> tuple[bytes, int]:
        async with self._lock:
            last_exc: BaseException | None = None
            for attempt in range(self._max_attempts):
                writer: asyncio.StreamWriter | None = None
                try:
                    reader, writer = await self._open()
                    async with asyncio.timeout(timeout):
                        return await self._exchange(
                            reader, writer, frame, with_crc=with_crc
                        )
                except TimeoutError as exc:
                    raise HabitronTimeoutError(
                        f"no response from {self._host}:{self._port} "
                        f"within {timeout:g}s"
                    ) from exc
                except (ConnectionError, EOFError, OSError) as exc:
                    last_exc = exc
                    _LOGGER.debug("bus error on attempt %d: %s", attempt + 1, exc)
                finally:
                    if writer is not None:
                        await self._close(writer)
            raise HabitronConnectionError(
                f"lost connection to {self._host}:{self._port} during exchange"
            ) from last_exc

    async def _exchange(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        frame: bytes,
        *,
        with_crc: bool,
    ) -> tuple[bytes, int]:
        writer.write(frame)
        await writer.drain()
        try:
            header = await reader.readexactly(HEADER_SIZE)
        except asyncio.IncompleteReadError as exc:
            if exc.partial:
                # Short-acknowledgement frame (see module docstring): the hub
                # answered with fewer than HEADER_SIZE bytes and closed the
                # connection. This carries no payload — it must NOT be returned
                # as data. The original synchronous client reported it as the
                # sentinel b"OK"; returning the raw partial bytes instead made
                # callers that parse the payload treat ack bytes as data (e.g.
                # the router firmware-file query, which short-acks when no update
                # file is staged, surfaced as a garbled "version").
                return b"OK", 0
            raise  # empty read -> connection drop, retried by _round_trip
        if header[0] != RESPONSE_MARKER:
            raise HabitronProtocolError(
                f"bad response marker 0x{header[0]:02x} from "
                f"{self._host}:{self._port} (expected 0x{RESPONSE_MARKER:02x})"
            )
        body_len = header[LEN_LO_INDEX] | (header[LEN_HI_INDEX] << 8)
        total_len = header[1] | (header[2] << 8)
        if total_len != HEADER_SIZE + body_len + TRAILER_SIZE:
            raise HabitronProtocolError(
                f"inconsistent frame length from {self._host}:{self._port}: "
                f"header total {total_len}, payload {body_len} implies "
                f"{HEADER_SIZE + body_len + TRAILER_SIZE}"
            )
        rest = await reader.readexactly(body_len + TRAILER_SIZE)
        payload = rest[:body_len]
        crc = (rest[body_len + 1] << 8) | rest[body_len] if with_crc else 0
        return payload, crc

    async def _open(
        self,
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        try:
            async with asyncio.timeout(self._connect_timeout):
                return await asyncio.open_connection(self._host, self._port)
        except (OSError, TimeoutError) as exc:
            raise HabitronConnectionError(
                f"cannot connect to {self._host}:{self._port}"
            ) from exc

    async def _close(self, writer: asyncio.StreamWriter) -> None:
        if not writer.is_closing():
            writer.close()
        with contextlib.suppress(OSError):
            await writer.wait_closed()
