"""Typed views over the YAML payloads returned by the SmartHub.

The SmartHub answers ``GET_SMHUB_INFO`` and ``GET_SMHUB_UPDATE`` with a YAML
document that carries many more keys than the integration consumes. The
``TypedDict`` definitions below describe only the subset that is actually read;
the runtime validators guarantee that subset is present and correctly shaped,
raising :class:`HabitronProtocolError` otherwise. Parsing always uses
``yaml.safe_load`` so a manipulated payload can never execute code.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TypedDict, cast

from .exceptions import HabitronProtocolError

# --- GET_SMHUB_INFO -------------------------------------------------------

# Functional syntax required: keys contain spaces.
SmhubNetwork = TypedDict("SmhubNetwork", {"ip": str, "host": str, "lan mac": str})


class SmhubPlatform(TypedDict):
    """SmartHub hardware platform descriptor."""

    type: str


class SmhubInfoHardware(TypedDict):
    """``hardware`` section of a ``GET_SMHUB_INFO`` payload."""

    platform: SmhubPlatform
    network: SmhubNetwork


class SmhubInfoSoftware(TypedDict):
    """``software`` section of a ``GET_SMHUB_INFO`` payload."""

    version: str


class SmhubInfo(TypedDict):
    """Validated subset of a ``GET_SMHUB_INFO`` payload."""

    hardware: SmhubInfoHardware
    software: SmhubInfoSoftware


# --- GET_SMHUB_UPDATE -----------------------------------------------------

# Functional syntax required: key "frequency current" contains a space.
SmhubCpu = TypedDict(
    "SmhubCpu", {"frequency current": str, "load": str, "temperature": str}
)


class SmhubUsage(TypedDict):
    """A memory/disk usage descriptor."""

    percent: str


class SmhubUpdateHardware(TypedDict):
    """``hardware`` section of a ``GET_SMHUB_UPDATE`` payload."""

    cpu: SmhubCpu
    memory: SmhubUsage
    disk: SmhubUsage


class SmhubLoglevel(TypedDict):
    """Console/file log levels.

    Levels arrive either as bare ints or numeric strings depending on firmware;
    both are accepted by the ``int()`` conversion at the call site.
    """

    console: int | str
    file: int | str


class SmhubUpdateSoftware(TypedDict):
    """``software`` section of a ``GET_SMHUB_UPDATE`` payload."""

    loglevel: SmhubLoglevel


class SmhubUpdate(TypedDict):
    """Validated subset of a ``GET_SMHUB_UPDATE`` payload."""

    hardware: SmhubUpdateHardware
    software: SmhubUpdateSoftware


_INFO_PATHS: tuple[tuple[str, ...], ...] = (
    ("software", "version"),
    ("hardware", "platform", "type"),
    ("hardware", "network", "ip"),
    ("hardware", "network", "host"),
    ("hardware", "network", "lan mac"),
)
_UPDATE_PATHS: tuple[tuple[str, ...], ...] = (
    ("hardware", "cpu", "frequency current"),
    ("hardware", "cpu", "load"),
    ("hardware", "cpu", "temperature"),
    ("hardware", "memory", "percent"),
    ("hardware", "disk", "percent"),
    ("software", "loglevel", "console"),
    ("software", "loglevel", "file"),
)


def _require_paths(data: object, paths: Sequence[tuple[str, ...]], label: str) -> None:
    """Verify every key path exists with mapping intermediates."""
    if not isinstance(data, Mapping):
        raise HabitronProtocolError(
            f"{label}: expected a mapping, got {type(data).__name__}"
        )
    for path in paths:
        node: object = data
        for depth, key in enumerate(path):
            if not isinstance(node, Mapping):
                trail = ".".join(path[:depth]) or label
                raise HabitronProtocolError(
                    f"{label}: expected mapping at '{trail}', got {type(node).__name__}"
                )
            if key not in node:
                raise HabitronProtocolError(
                    f"{label}: missing key '{'.'.join(path[: depth + 1])}'"
                )
            node = node[key]


def validate_smhub_info(data: object) -> SmhubInfo:
    """Validate a parsed ``GET_SMHUB_INFO`` payload, or raise."""
    _require_paths(data, _INFO_PATHS, "SmartHub info")
    return cast(SmhubInfo, data)


def validate_smhub_update(data: object) -> SmhubUpdate:
    """Validate a parsed ``GET_SMHUB_UPDATE`` payload, or raise."""
    _require_paths(data, _UPDATE_PATHS, "SmartHub update")
    return cast(SmhubUpdate, data)
