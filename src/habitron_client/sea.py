"""Client for the Smart Energy Agent (SEA) add-on API, version 1.

SEA serves ``/api/v1/info``, ``/api/v1/state`` and ``/api/v1/command`` over HTTP
and pushes its values over the WebSocket ``/api/v1/ws``: a ``snapshot`` with all
keys right after connecting, then ``update`` messages with the changed keys.
Every request carries the add-on's token as a Bearer token.
"""

import json
import logging
from collections.abc import AsyncIterator
from typing import Any, Final

import aiohttp

from .exceptions import HabitronError

_LOGGER = logging.getLogger(__name__)

SEA_DEFAULT_PORT: Final = 7790
_TIMEOUT: Final = aiohttp.ClientTimeout(total=10)
_HEARTBEAT: Final = 30


class SeaError(HabitronError):
    """SEA could not be reached or answered unusably."""


class SeaCommandError(SeaError):
    """SEA refused a command (HTTP 400)."""


class SeaClient:
    """HTTP and WebSocket access to the SEA add-on."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        port: int,
        token: str,
    ) -> None:
        """Initialize the client; the session is owned by the caller."""
        self._session = session
        self._base = f"http://{host}:{port}/api/v1"
        self._headers = {"Authorization": f"Bearer {token}"}

    async def _get_object(self, path: str) -> dict[str, Any]:
        try:
            async with self._session.get(
                f"{self._base}/{path}", headers=self._headers, timeout=_TIMEOUT
            ) as response:
                response.raise_for_status()
                data = await response.json()
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise SeaError(f"{path}: {err!r}") from err
        if not isinstance(data, dict):
            raise SeaError(f"{path}: not an object")
        return data

    async def get_info(self) -> dict[str, Any]:
        """Return ``api_version``, ``version``, ``name`` and ``url``."""
        return await self._get_object("info")

    async def get_state(self) -> dict[str, Any]:
        """Return all current values by key."""
        return await self._get_object("state")

    async def command(self, key: str, value: str | bool) -> None:
        """Set a writable key; SEA pushes the new state as an update."""
        try:
            async with self._session.post(
                f"{self._base}/command",
                headers=self._headers,
                json={"key": key, "value": value},
                timeout=_TIMEOUT,
            ) as response:
                if response.status == 400:
                    raise SeaCommandError(f"{key}: {await response.text()}")
                response.raise_for_status()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise SeaError(f"command {key}: {err!r}") from err

    async def messages(self) -> AsyncIterator[dict[str, Any]]:
        """Yield the push messages; raise ``SeaError`` when the connection ends."""
        try:
            async with self._session.ws_connect(
                f"{self._base}/ws", headers=self._headers, heartbeat=_HEARTBEAT
            ) as ws:
                async for msg in ws:
                    if msg.type is not aiohttp.WSMsgType.TEXT:
                        break
                    try:
                        message = json.loads(msg.data)
                    except ValueError:
                        _LOGGER.debug("Ignoring unreadable SEA message")
                        continue
                    if isinstance(message, dict):
                        yield message
        except aiohttp.ClientError as err:
            raise SeaError(f"ws: {err!r}") from err
        raise SeaError("ws: connection closed")
