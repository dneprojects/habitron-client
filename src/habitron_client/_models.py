"""Typed views over the YAML payloads returned by the SmartHub.

The SmartHub answers ``GET_SMHUB_INFO`` and ``GET_SMHUB_UPDATE`` with a YAML
document that carries many more keys than the integration consumes. The
``TypedDict`` definitions below describe only the subset that is actually read;
the runtime validators guarantee that subset is present and correctly shaped,
raising :class:`HabitronProtocolError` otherwise. Parsing always uses
``yaml.safe_load`` so a manipulated payload can never execute code.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, NotRequired, TypedDict, cast

from .exceptions import HabitronProtocolError
from .model import Diagnostic, HostDiagnostics, Sensor, SmartHub, normalise_mac

# --- GET_SMHUB_INFO -------------------------------------------------------

# Functional syntax required: keys contain spaces.
#
# ``lan mac`` is the hub's identity: the LAN interface exists on every SmartHub
# (a Raspberry Pi), so it is reported whichever interface currently carries the
# traffic. ``mac`` is that *active* interface's address -- it flips when the hub
# moves between LAN and WLAN and must never be used to identify the device.
# Both it and ``wlan mac`` are optional: only ``lan mac`` is contractually
# present.
SmhubNetwork = TypedDict(
    "SmhubNetwork",
    {
        "ip": str,
        "host": str,
        "lan mac": str,
        "wlan mac": NotRequired[str],
        "mac": NotRequired[str],
    },
)


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
    #: Ingress slug of the hub's own add-on. Only a hub running as a Home
    #: Assistant add-on has one; the others either omit the key or report the
    #: literal sentinel "none", so it is not part of the validated contract.
    slug: NotRequired[str]


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


def hub_mac_addresses(info: SmhubInfo) -> list[str]:
    """Return every MAC the hub reports, in the order it reports them.

    A SmartHub can be reached over its LAN or its WLAN interface, and Home
    Assistant matches devices by MAC connection -- so a consumer registering
    that device wants all of them, or the hub stays unrecognised on whichever
    interface it is not currently identified by. Blanks and duplicates are
    dropped; the values keep the notation the hub used, since the consumer
    normalises them for its own registry.

    This is *not* the identity: that is ``lan mac`` alone (see ``SmhubNetwork``).
    """
    network = info["hardware"]["network"]
    seen: list[str] = []
    for key in ("lan mac", "wlan mac", "mac"):
        value = str(network.get(key, "") or "").strip()
        if value and value not in seen:
            seen.append(value)
    return seen


def validate_smhub_info(data: object) -> SmhubInfo:
    """Validate a parsed ``GET_SMHUB_INFO`` payload, or raise."""
    _require_paths(data, _INFO_PATHS, "SmartHub info")
    return cast(SmhubInfo, data)


def validate_smhub_update(data: object) -> SmhubUpdate:
    """Validate a parsed ``GET_SMHUB_UPDATE`` payload, or raise."""
    _require_paths(data, _UPDATE_PATHS, "SmartHub update")
    return cast(SmhubUpdate, data)


def _number(value: object, unit: str, label: str) -> float:
    """Return a hub reading as a float, dropping the unit it carries."""
    try:
        return float(str(value).rstrip(unit))
    except (TypeError, ValueError) as err:
        raise HabitronProtocolError(
            f"SmartHub update: '{label}' is not a number: {value!r}"
        ) from err


def parse_host_diagnostics(update: SmhubUpdate) -> HostDiagnostics:
    """Turn a validated hub update into typed host readings.

    The hub reports its readings as strings carrying the unit ("1500MHz",
    "12%", "55.5°C") and its log levels as either ints or numeric strings.
    Undoing that is wire-format knowledge and belongs here, not in a consumer.

    Raises ``HabitronProtocolError`` when a value cannot be read as a number;
    the paths themselves are already guaranteed by ``validate_smhub_update``.
    """
    hardware = update["hardware"]
    software = update["software"]
    return HostDiagnostics(
        cpu_frequency=_number(
            hardware["cpu"]["frequency current"], "MHz", "cpu.frequency"
        ),
        cpu_load=_number(hardware["cpu"]["load"], "%", "cpu.load"),
        cpu_temperature=_number(
            hardware["cpu"]["temperature"], "°C", "cpu.temperature"
        ),
        memory_usage=_number(hardware["memory"]["percent"], "%", "memory.percent"),
        disk_usage=_number(hardware["disk"]["percent"], "%", "disk.percent"),
        log_level_console=int(
            _number(software["loglevel"]["console"], "", "loglevel.console")
        ),
        log_level_file=int(_number(software["loglevel"]["file"], "", "loglevel.file")),
    )


# --- the hub itself -------------------------------------------------------

# Role codes stamped on the hub's host readings. These are not real bus members
# -- the hub has no descriptor for them -- but they are handed out as
# ``BusMember`` objects, so they carry the codes that make
# ``BusMember.is_diagnostic`` answer correctly: the diagnostic role for the CPU
# readings, the plain sensor role for memory/disk usage and the log levels.
_HOST_DIAG_ROLE: Final = 10
_HOST_SENSOR_ROLE: Final = 2

# Only Raspberry-Pi based hubs report host readings; other platforms answer
# without them. Matched on the prefix because the hub appends its board
# revision ("Raspberry Pi 4", "Raspberry Pi 5", ...).
_HOST_DIAG_PLATFORM: Final = "Raspberry Pi"


@dataclass(frozen=True)
class _HostReading:
    """One host reading: which list it belongs in and how to read its value."""

    group: str
    name: str
    value_of: Callable[[HostDiagnostics], float]


# Single source of truth for the hub's host readings: both the member creation
# in ``parse_smhub_info`` and the value update in ``apply_host_diagnostics`` run
# off this table, so the two cannot drift apart. The names are part of the
# public model -- a consumer keys its entity descriptions by them.
_HOST_READINGS: Final[tuple[_HostReading, ...]] = (
    _HostReading("diags", "CPU Frequency", lambda host: host.cpu_frequency),
    _HostReading("diags", "CPU load", lambda host: host.cpu_load),
    _HostReading("diags", "CPU Temperature", lambda host: host.cpu_temperature),
    _HostReading("sensors", "Memory usage", lambda host: host.memory_usage),
    _HostReading("sensors", "Disk usage", lambda host: host.disk_usage),
    _HostReading(
        "loglevels", "Logging level console", lambda host: host.log_level_console
    ),
    _HostReading("loglevels", "Logging level file", lambda host: host.log_level_file),
)


def _readings_in(group: str) -> tuple[_HostReading, ...]:
    """Return the table rows belonging to one member list."""
    return tuple(reading for reading in _HOST_READINGS if reading.group == group)


def parse_smhub_info(info: SmhubInfo) -> SmartHub:
    """Turn a validated ``GET_SMHUB_INFO`` payload into a :class:`SmartHub`.

    Assembling the hub's own data into one object is wire-format work, the same
    as :func:`parse_host_diagnostics`: the payload spreads it over three
    sections, reports "no add-on" as a sentinel string and may answer ``null``
    for an address. A consumer should receive a hub, not a nested mapping.

    The host readings are created empty here and filled by
    :func:`apply_host_diagnostics` on the first poll; ``SmartHub.host_valid``
    says which of the two states the values are in.
    """
    hardware = info["hardware"]
    software = info["software"]
    network = hardware["network"]

    # Present by contract, but null on a hub with no LAN interface configured.
    # "" is the "no identity" case a consumer expects; None would break every
    # string operation it performs on the value.
    lan_mac = str(network["lan mac"] or "").strip()
    # The firmware reports the literal sentinel "none" (or omits the key) when
    # the hub does not run as an add-on. Undoing that is wire knowledge and
    # belongs here rather than in every consumer.
    slug = str(software.get("slug", "") or "").strip()
    if slug == "none":
        slug = ""

    hub = SmartHub(
        lan_mac=lan_mac,
        # Filtered to real addresses: the consumer registers these directly as
        # device connections, and a redaction or a firmware placeholder would
        # match every other device reporting the same thing.
        macs=[mac for mac in hub_mac_addresses(info) if normalise_mac(mac)],
        hostname=network["host"],
        platform=hardware["platform"]["type"],
        version=software["version"],
        slug=slug,
    )
    if hub.platform.startswith(_HOST_DIAG_PLATFORM):
        hub.diags = [
            Diagnostic(name=reading.name, nmbr=nmbr, type=_HOST_DIAG_ROLE)
            for nmbr, reading in enumerate(_readings_in("diags"))
        ]
        hub.sensors = [
            Sensor(name=reading.name, nmbr=nmbr, type=_HOST_SENSOR_ROLE)
            for nmbr, reading in enumerate(_readings_in("sensors"))
        ]
        hub.loglevels = [
            Sensor(name=reading.name, nmbr=nmbr, type=_HOST_SENSOR_ROLE)
            for nmbr, reading in enumerate(_readings_in("loglevels"))
        ]
    return hub


def apply_host_diagnostics(hub: SmartHub, host: HostDiagnostics) -> None:
    """Write host readings into the hub's members, firing their listeners.

    The per-member notification is the same contract the bus members have, so a
    consumer subscribes to a hub reading exactly as it subscribes to a module
    sensor.

    On the first successful poll *every* member is notified, not just the ones
    whose value moved: the members start at their dataclass defaults, and a
    reading that happens to match its default (an unchanged CPU frequency, a log
    level of 0) would otherwise never fire -- leaving a consumer that renders an
    unread member as "unknown" stuck on it until some other value moves.
    """
    first_poll = not hub.host_valid
    hub.host_valid = True
    by_name = {member.name: member for member in hub.host_members}
    for reading in _HOST_READINGS:
        member = by_name.get(reading.name)
        if member is None:
            # A platform that exposes only a subset of the readings.
            continue
        value = reading.value_of(host)
        changed = member.value != value
        member.value = value
        if changed or first_poll:
            member.notify()
