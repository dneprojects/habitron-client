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

from collections.abc import Callable
from dataclasses import dataclass, field

Listener = Callable[[], None]


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
    """An ekey fingerprint-reader reading."""

    value: int = 0


@dataclass(kw_only=True)
class HbtnCommand(BusMember):
    """A named command or stored message (notify, direct/visual/collective)."""


@dataclass(kw_only=True)
class Diagnostic(BusMember):
    """A diagnostic reading (currents, voltages, temperatures, ...)."""

    value: float = 0.0


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

    uid: str
    addr: int
    typ: bytes
    name: str
    mod_type: str = ""
    area: int = 0
    group: int = 0
    sw_version: str = ""
    hw_version: str = ""
    # Scalar module state filled from the status/settings bytes.
    mode: int = 0
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


@dataclass(kw_only=True)
class SmartController(Module):
    """A Smart Controller (Touch) module with extra battery/health readings."""

    battery: list[Diagnostic] = field(default_factory=list)
    stream_name: str = ""


@dataclass(kw_only=True)
class Router:
    """The Habitron router and everything reachable behind it."""

    uid: str = ""
    id: int = 100
    name: str = ""
    version: str = ""
    serial: str = ""
    user1_name: str = "user1"
    user2_name: str = "user2"
    mode: int = 0x11
    sys_ok: bool = True
    mirror_started: bool = True
    max_group: int = 0
    cover_autostop_del: int = 5
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
