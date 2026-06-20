"""Asynchronous, typed API client for the Habitron SmartHub."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from ._events import apply_event
from ._models import SmhubInfo, SmhubUpdate
from ._protocol import calc_crc, check_crc, format_block_output
from ._setup import async_build_system, async_refresh_system
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
    HabitronConnectionError,
    HabitronError,
    HabitronProtocolError,
    HabitronTimeoutError,
)
from .model import (
    Area,
    BusMember,
    ColorLed,
    Cover,
    Diagnostic,
    Dimmer,
    Finger,
    Flag,
    HbtnCommand,
    Input,
    Led,
    Logic,
    Module,
    Output,
    Router,
    Sensor,
    SetValue,
    SmartController,
)

try:
    __version__ = version("habitron-client")
except PackageNotFoundError:  # pragma: no cover - only during local source runs
    __version__ = "0.0.0"

__all__ = [
    "Area",
    "BusMember",
    "ColorLed",
    "Command",
    "Cover",
    "Diagnostic",
    "Dimmer",
    "Finger",
    "Flag",
    "HabitronBusError",
    "HabitronClient",
    "HabitronConnectionError",
    "HabitronError",
    "HabitronProtocolError",
    "HabitronTimeoutError",
    "HbtnCommand",
    "Input",
    "Led",
    "Logic",
    "Module",
    "Output",
    "Router",
    "Sensor",
    "SetValue",
    "SmartController",
    "SmhubInfo",
    "SmhubUpdate",
    "__version__",
    "apply_event",
    "async_build_system",
    "async_refresh_system",
    "calc_crc",
    "check_crc",
    "discover_smarthubs",
    "format_block_output",
    "get_host_ip",
    "get_own_ip",
    "query_smarthub",
    "test_connection",
]
