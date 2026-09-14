"""Public, typed device model for a Habitron installation.

These dataclasses are the parsed representation of everything behind a
SmartHub: the router, its modules and every addressable member (outputs,
sensors, covers, ...). The protocol/parsing layer fills them in; consumers
(e.g. the Home Assistant integration) read typed attributes and subscribe to
**per-member** change notifications via :meth:`BusMember.add_listener`.

This module is intentionally free of any Home Assistant import — areas and
groups are exposed as plain data, and the consumer maps them to its own
registries.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import ClassVar, Final

Listener = Callable[[], None]


# Bus role code marking a diagnostic member; exposed through
# ``BusMember.is_diagnostic`` rather than as a constant, so the wire value stays
# inside this package.
_TYPE_DIAGNOSTIC: Final = 10


@dataclass(kw_only=True)
class BusMember:
    """Base class for every addressable element on a module.

    ``type`` mirrors the bus role/enabled code (a negative value means the
    member is disabled and should not be exposed). ``area`` is the bus area
    number (``0`` = the module's own area).
    """

    name: str
    nmbr: int
    type: int = 0
    area: int = 0
    _listeners: set[Listener] = field(default_factory=set, repr=False, compare=False)

    def add_listener(self, callback: Listener) -> None:
        """Register a callback fired whenever this member's value changes."""
        self._listeners.add(callback)

    def remove_listener(self, callback: Listener) -> None:
        """Remove a previously registered callback."""
        self._listeners.discard(callback)

    def notify(self) -> None:
        """Fire all registered listeners (called by the parser on a change)."""
        for callback in tuple(self._listeners):
            callback()

    @property
    def is_diagnostic(self) -> bool:
        """Whether this member reports diagnostics rather than a user value.

        The bus encodes the role in ``type``; consumers should ask this instead
        of comparing against the raw code, which is protocol detail.
        """
        return abs(self.type) == _TYPE_DIAGNOSTIC


@dataclass(kw_only=True)
class Input(BusMember):
    """A button or switch input; ``value`` is the last raw input value."""

    value: int = 0


@dataclass(kw_only=True)
class Output(BusMember):
    """An on/off output."""

    is_on: bool = False


@dataclass(kw_only=True)
class Dimmer(BusMember):
    """A dimmable output; ``brightness`` is 0..100."""

    brightness: int = 0


@dataclass(kw_only=True)
class Cover(BusMember):
    """A shutter/blind; ``position`` and ``tilt`` are 0..100."""

    position: int = 0
    tilt: int = 0


@dataclass(kw_only=True)
class Sensor(BusMember):
    """A measured value (temperature, humidity, illuminance, wind, ...)."""

    value: float | int | str | None = None


@dataclass(kw_only=True)
class Led(BusMember):
    """An indicator LED."""

    is_on: bool = False


@dataclass(kw_only=True)
class ColorLed(BusMember):
    """An RGB(W) colour LED; ``rgb`` = ``[r, g, b, w]``."""

    rgb: list[int] = field(default_factory=lambda: [0, 0, 0, 0])
    is_on: bool = False


@dataclass(kw_only=True)
class Logic(BusMember):
    """A logic/counter element."""

    idx: int = 0
    value: float = 0.0


@dataclass(kw_only=True)
class Flag(BusMember):
    """A mode or flag state."""

    idx: int = 0
    value: int = 0


@dataclass(kw_only=True)
class SetValue(BusMember):
    """A settable value (e.g. a climate set point)."""

    value: float = 0.0


@dataclass(kw_only=True)
class Finger(BusMember):
    """An ekey fingerprint-reader reading.

    ``value`` holds the last raw finger number, ``user`` the raw user id — both
    as reported by the push event, so consumers can render the press.
    """

    value: int = 0
    user: int = 0


@dataclass(kw_only=True)
class HbtnCommand(BusMember):
    """A named command or stored message (notify, direct/visual/collective)."""


@dataclass(kw_only=True)
class Diagnostic(BusMember):
    """A diagnostic reading (currents, voltages, temperatures, ...)."""

    value: float = 0.0


@dataclass(kw_only=True)
class Health(BusMember):
    """A module's operate-mode fault state.

    ``value`` is the raw one-byte fault bitmask last reported by the SmartHub via
    a ``SYS_ERR`` event (``0`` = the module is healthy). Decode it into the
    active faults with :func:`habitron_client.decode_module_faults`.
    """

    value: int = 0


@dataclass
class Area:
    """A bus-defined area (room).

    The library only carries the number and name; the consumer maps it to its
    own area registry (e.g. by slugifying ``name``).
    """

    nmbr: int
    name: str


@dataclass(kw_only=True)
class Module:
    """A Habitron module behind the router, with its parsed members."""

    #: Dimmer channel the module's analogue output is wired to. The bus has no
    #: separate command for it -- an analogue output is addressed as a dimmer.
    ANALOG_OUT_CHANNEL: ClassVar[int] = 3

    uid: str
    addr: int
    typ: bytes
    name: str
    mod_type: str = ""
    area: int = 0
    group: int = 0
    sw_version: str = ""
    hw_version: str = ""
    # Daytime/group mode as a notifiable member (entity-bound select).
    mode: Flag = field(default_factory=lambda: Flag(name="Mode", nmbr=0, value=0))
    # Operate-mode fault bitmask, pushed per module via SYS_ERR (0 = healthy).
    health: Health = field(
        default_factory=lambda: Health(name="Health", nmbr=0, value=0)
    )
    # Scalar module state filled from the status/settings bytes.
    climate_settings: int = 0
    climate_ctl12: int = 1
    auxheat_value: int = 0
    inputs: list[Input] = field(default_factory=list)
    analogins: list[Input] = field(default_factory=list)
    outputs: list[Output] = field(default_factory=list)
    # The Smart Controller's single 0..255 analogue output (AOUT) — kept
    # apart from the binary ``outputs`` so each member stays cleanly typed.
    analog_outputs: list[Dimmer] = field(default_factory=list)
    dimmers: list[Dimmer] = field(default_factory=list)
    covers: list[Cover] = field(default_factory=list)
    sensors: list[Sensor] = field(default_factory=list)
    leds: list[Led] = field(default_factory=list)
    color_leds: list[ColorLed] = field(default_factory=list)
    logic: list[Logic] = field(default_factory=list)
    flags: list[Flag] = field(default_factory=list)
    setvalues: list[SetValue] = field(default_factory=list)
    fingers: list[Finger] = field(default_factory=list)
    ids: list[HbtnCommand] = field(default_factory=list)
    messages: list[HbtnCommand] = field(default_factory=list)
    dir_commands: list[HbtnCommand] = field(default_factory=list)
    vis_commands: list[HbtnCommand] = field(default_factory=list)
    gsm_numbers: list[HbtnCommand] = field(default_factory=list)
    diags: list[Diagnostic] = field(default_factory=list)

    def led_output(self, nmbr: int) -> int:
        """Return the output number LED ``nmbr`` is addressed by.

        A module's indicator LEDs continue the output numbering rather than
        having a command of their own, so the first LED is the output after the
        last real one. Where that boundary sits is a property of the module, so
        it is answered here rather than by every caller counting outputs.
        """
        return nmbr + len(self.outputs)


@dataclass(kw_only=True)
class SmartController(Module):
    """A Smart Controller (Touch) module with extra battery/health readings."""

    battery: list[Diagnostic] = field(default_factory=list)
    stream_name: str = ""
    client_version: str = "unknown"


@dataclass(kw_only=True)
class HostDiagnostics:
    """Host readings of a Raspberry-Pi based SmartHub, unit-stripped.

    The hub reports these as strings carrying their unit ("1500MHz", "12%"),
    which is wire format, not something a consumer should have to undo.
    """

    cpu_frequency: float
    cpu_load: float
    cpu_temperature: float
    memory_usage: float
    disk_usage: float
    log_level_console: int
    log_level_file: int


@dataclass(kw_only=True)
class Router:
    """The Habitron router and everything reachable behind it."""

    uid: str = ""
    name: str = ""
    version: str = ""
    serial: str = ""
    user1_name: str = "user1"
    user2_name: str = "user2"
    mode: Flag = field(default_factory=lambda: Flag(name="Mode", nmbr=0, value=0x11))
    sys_ok: bool = True
    mirror_started: bool = True
    rebooted: bool = False
    max_group: int = 0
    #: Seconds to wait before switching a cover output off once the cover has
    #: reached its end position. ``None`` means the router has the automatic
    #: switch-off disabled (transmitted as 255); ``0`` is a valid delay.
    cover_autostop_del: int | None = 5
    module_grp: list[int] = field(default_factory=list)
    chan_list: list[list[int]] = field(default_factory=list)
    modules: list[Module] = field(default_factory=list)
    areas: list[Area] = field(default_factory=list)
    flags: list[Flag] = field(default_factory=list)
    groups: list[Flag] = field(default_factory=list)
    # ``states[0]`` = system OK, ``states[1]`` = mirror started (entity-bound).
    states: list[Flag] = field(default_factory=list)
    coll_commands: list[HbtnCommand] = field(default_factory=list)
    chan_timeouts: list[Diagnostic] = field(default_factory=list)
    chan_currents: list[Diagnostic] = field(default_factory=list)
    voltages: list[Diagnostic] = field(default_factory=list)
    diags: list[Diagnostic] = field(default_factory=list)


# A hub's identity is its LAN address, written bare and lower case. The exact
# spelling is part of this library's public contract: consumers key their
# device registries and stored records by it, so changing it would orphan every
# installation already running.
_MAC_RE: Final = re.compile(r"[0-9a-f]{12}")
# Shape alone is not enough. The all-zero address is what a consumer typically
# holds before a hub has answered, and the broadcast address is not a machine
# either. Both match the pattern, and every hub reporting one would end up
# sharing the same identity.
_NOT_AN_IDENTITY: Final = frozenset({"000000000000", "ffffffffffff"})


def normalise_mac(value: str) -> str | None:
    """Return ``value`` as a bare lower-case address, or ``None`` if it is not one.

    Hubs report their addresses with either separator and in either case, which
    is wire-format variation the consumer should not have to undo -- and only a
    real address may become an identity. A hub answering with something else (an
    IP, a redaction, a placeholder its firmware falls back to) would otherwise
    hand out an id that two machines could share.
    """
    mac = value.strip().replace(":", "").replace("-", "").lower()
    if not _MAC_RE.fullmatch(mac) or mac in _NOT_AN_IDENTITY:
        return None
    return mac


@dataclass(kw_only=True)
class SmartHub:
    """The SmartHub host itself — the machine the bus hangs off.

    :class:`Router` models everything *behind* the hub; this models the hub.
    It carries what the hub reports about itself, plus its own host readings as
    ordinary :class:`BusMember` objects, so a consumer binds entities to them
    exactly as it does for a module or the router.

    Deliberately limited to what the hub *reports*. What any of it means is the
    consumer's decision: which address identifies the device, what URL to build
    from :attr:`slug`, how to name and unit the readings.
    """

    #: The hub's identity: :attr:`lan_mac`, bare and lower case, as derived by
    #: :func:`~habitron_client.async_build_hub`. The base id every other uid in
    #: the model derives from -- pass it to
    #: :func:`~habitron_client.async_build_system` as ``b_uid``.
    #:
    #: Empty when the hub reported no usable address. That is a real state, not
    #: an error -- a hub with no LAN interface configured answers ``null`` --
    #: and the library has nothing better to offer. A field rather than a
    #: derived property precisely so a consumer can write its own fallback in
    #: and keep one identity for the whole model, the way ``Router.uid`` and
    #: ``Module.uid`` are also plain fields.
    uid: str = ""
    #: The LAN interface address, and the hub's identity: a SmartHub reports it
    #: whichever interface currently carries the traffic, so it does not flip on
    #: a LAN/WLAN switch. Empty when the hub has no LAN interface configured.
    lan_mac: str = ""
    #: Every real address the hub reports, in the order it reports them and in
    #: the notation it used. The hub answers over whichever interface is up, so
    #: a consumer matching devices by address wants all of them — but only
    #: :attr:`lan_mac` is the identity. Values that are not addresses at all
    #: (a redaction, a firmware placeholder) are already dropped, so a consumer
    #: can register the list as-is.
    macs: list[str] = field(default_factory=list)
    #: Host name the hub reports for itself.
    hostname: str = ""
    #: Hardware platform as the hub names it, e.g. ``"Raspberry Pi 5"``.
    platform: str = ""
    #: SmartHub firmware version.
    version: str = ""
    #: Ingress slug of the hub's own add-on, empty when it does not run as one.
    #: The firmware's "not an add-on" sentinel is already undone here.
    slug: str = ""

    #: Host readings. Empty on platforms that report none, so a consumer creates
    #: no host entities there rather than publishing placeholders.
    diags: list[Diagnostic] = field(default_factory=list)
    sensors: list[Sensor] = field(default_factory=list)
    loglevels: list[Sensor] = field(default_factory=list)

    #: Whether a host poll has ever succeeded. The members start at their
    #: dataclass defaults, and ``0`` is a plausible CPU load or log level rather
    #: than an obvious placeholder — so a consumer must render them as "unknown"
    #: until this turns true, not as a measurement of zero.
    host_valid: bool = False

    @property
    def is_addon(self) -> bool:
        """Whether the hub reports itself as running as a Home Assistant add-on.

        Derived from :attr:`slug`, which the hub only fills in for an add-on
        deployment. This describes the *hub*, not the consumer: an external hub
        talking to a supervised Home Assistant still answers false.
        """
        return bool(self.slug)

    @property
    def host_members(self) -> list[Diagnostic | Sensor]:
        """Every host reading in one list, diagnostics first."""
        return [*self.diags, *self.sensors, *self.loglevels]
