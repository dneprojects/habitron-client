"""Async TCP transport for the Habitron SmartHub.

A single :class:`BusConnection` owns one persistent ``StreamReader``/
``StreamWriter`` pair. The SmartHub protocol is strictly request/response with
no multiplexing, so a lock serialises every exchange. Connection loss is handled
centrally: a failed exchange is retried once on a fresh connection.

Short-acknowledgement assumption
--------------------------------
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
    HabitronTimeoutError,
)

_LOGGER = logging.getLogger(__name__)

DEFAULT_PORT: int = 7777
DEFAULT_CONNECT_TIMEOUT: float = 10.0


class BusConnection:
    """A serialised, self-healing TCP connection to a SmartHub."""

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
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
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
        """Open the connection eagerly (also done lazily on first request)."""
        async with self._lock:
            await self._ensure_connection()

    async def close(self) -> None:
        """Close the connection and release the socket."""
        async with self._lock:
            await self._reset()

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
            try:
                await self._ensure_connection()
                assert self._writer is not None
                self._writer.write(frame)
                await self._writer.drain()
            except (OSError, HabitronError) as exc:
                _LOGGER.warning("send_only failed: %s", exc)
            finally:
                # Drop the connection so a possible unread reply cannot pollute
                # the next request's read.
                await self._reset()

    async def _round_trip(
        self, frame: bytes, timeout: float, *, with_crc: bool
    ) -> tuple[bytes, int]:
        async with self._lock:
            last_exc: BaseException | None = None
            for attempt in range(self._max_attempts):
                await self._ensure_connection()
                try:
                    async with asyncio.timeout(timeout):
                        return await self._exchange(frame, with_crc=with_crc)
                except TimeoutError as exc:
                    await self._reset()
                    raise HabitronTimeoutError(
                        f"no response from {self._host}:{self._port} "
                        f"within {timeout:g}s"
                    ) from exc
                except (ConnectionError, EOFError, OSError) as exc:
                    last_exc = exc
                    await self._reset()
                    _LOGGER.debug("bus error on attempt %d: %s", attempt + 1, exc)
            raise HabitronConnectionError(
                f"lost connection to {self._host}:{self._port} during exchange"
            ) from last_exc

    async def _exchange(self, frame: bytes, *, with_crc: bool) -> tuple[bytes, int]:
        reader = self._reader
        writer = self._writer
        assert reader is not None and writer is not None
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
                await self._reset()
                return b"OK", 0
            raise  # empty read -> connection drop, retried by _round_trip
        body_len = header[LEN_LO_INDEX] | (header[LEN_HI_INDEX] << 8)
        rest = await reader.readexactly(body_len + TRAILER_SIZE)
        payload = rest[:body_len]
        crc = (rest[body_len + 1] << 8) | rest[body_len] if with_crc else 0
        return payload, crc

    async def _ensure_connection(self) -> None:
        if self._writer is not None and not self._writer.is_closing():
            return
        _LOGGER.debug("opening connection to %s:%s", self._host, self._port)
        try:
            async with asyncio.timeout(self._connect_timeout):
                self._reader, self._writer = await asyncio.open_connection(
                    self._host, self._port
                )
        except (OSError, TimeoutError) as exc:
            await self._reset()
            raise HabitronConnectionError(
                f"cannot connect to {self._host}:{self._port}"
            ) from exc
        _LOGGER.debug("connected to %s:%s", self._host, self._port)

    async def _reset(self) -> None:
        writer = self._writer
        self._reader = None
        self._writer = None
        if writer is not None and not writer.is_closing():
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()
