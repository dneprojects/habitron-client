"""Asynchronous, typed API client for the Habitron SmartHub."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from ._models import SmhubInfo, SmhubUpdate
from ._protocol import calc_crc, check_crc, format_block_output
from .client import HabitronClient
from .const import Command
from .discovery import (
    discover_smarthubs,
    get_host_ip,
    get_own_ip,
    query_smarthub,
    test_connection,
)
from .exceptions import (
    HabitronBusError,
    HabitronChecksumError,
    HabitronConnectionError,
    HabitronError,
    HabitronProtocolError,
    HabitronTimeoutError,
)

try:
    __version__ = version("habitron-client")
except PackageNotFoundError:  # pragma: no cover - only during local source runs
    __version__ = "0.0.0"

__all__ = [
    "Command",
    "HabitronBusError",
    "HabitronChecksumError",
    "HabitronClient",
    "HabitronConnectionError",
    "HabitronError",
    "HabitronProtocolError",
    "HabitronTimeoutError",
    "SmhubInfo",
    "SmhubUpdate",
    "__version__",
    "calc_crc",
    "check_crc",
    "discover_smarthubs",
    "format_block_output",
    "get_host_ip",
    "get_own_ip",
    "query_smarthub",
    "test_connection",
]
