"""Turn raw Habitron bus bytes into the typed :mod:`habitron_client.model`.

This is the parsing layer that used to live in the integration's ``module.py``
(``HbtnModule`` + per-type subclasses). It is split in two:

* :func:`build_module` mirrors the subclass ``__init__`` methods — it creates the
  empty, correctly-shaped member lists for a module type.
* :func:`apply_status` mirrors the subclass ``update`` methods — it writes the
  parsed values from a compact-status block into those members and fires each
  member's listeners on a change.

Names, default-naming, type fix-ups (definitions/settings parsing) and the
router layer are ported separately.
"""

from __future__ import annotations

from ._indices import MODULE_CODES, MStatIdx
from .model import (
    BusMember,
    ColorLed,
    Cover,
    Diagnostic,
    Dimmer,
    Finger,
    Input,
    Led,
    Logic,
    Module,
    Output,
    Sensor,
    SetValue,
    SmartController,
)


def _u16(data: bytes, idx: int) -> int:
    """Read a little-endian 16-bit value at ``idx``."""
    return int.from_bytes(data[idx : idx + 2], "little")


def _set(member: BusMember, attr: str, value: object) -> None:
    """Assign ``value`` to ``member.attr``; fire listeners only on a change."""
    if getattr(member, attr) != value:
        setattr(member, attr, value)
        member.notify()


def _module_kind(typ: bytes) -> str:
    """Map a 2-byte module type code to a parser kind."""
    m0, m1 = typ[0], typ[1]
    if m0 == 10 and m1 in (1, 2, 50, 51):
        return "out"
    if m0 == 10 and m1 in (20, 21, 22):
        return "dimm"
    if m0 == 10 and m1 == 30:
        return "io2"
    if m0 == 11:
        return "in"
    if m0 == 80:
        return "detect"
    if m0 == 20:
        return "nature"
    if m0 == 50 and m1 == 1:
        return "mini"
    if m0 == 50 and m1 == 40:
        return "sensor"
    if m0 == 1:
        return "controller"
    if m0 == 30 and m1 == 1:
        return "ekey"
    if m0 == 30 and m1 == 3:
        return "gsm"
    return "generic"


def _base_diags() -> list[Diagnostic]:
    """Default two-entry diagnostics list shared by most modules."""
    return [
        Diagnostic(name="", nmbr=0, type=0),
        Diagnostic(name="Status", nmbr=0, type=1),
    ]


def build_module(*, uid: str, addr: int, typ: bytes, name: str, group: int) -> Module:
    """Create an empty, correctly-shaped module for ``typ``.

    Member names are left blank here — they are filled by the definitions
    (label) parser. Returns a :class:`SmartController` for controller modules,
    a plain :class:`Module` otherwise.
    """
    mod_type = MODULE_CODES[typ]
    kind = _module_kind(typ)

    if kind == "controller":
        sc = SmartController(
            uid=uid,
            addr=addr,
            typ=typ,
            name=name,
            mod_type=mod_type,
            group=group,
            diags=_base_diags(),
        )
        if typ[1] > 2:
            sc.analogins = [
                Input(name=f"A/D-Kanal {i + 1}", nmbr=i, type=3) for i in range(2)
            ]
        sc.inputs = [Input(name="", nmbr=i, type=1) for i in range(18)]
        sc.outputs = [Output(name="", nmbr=i, type=1) for i in range(16)]
        sc.analog_outputs = [Dimmer(name="", nmbr=15, type=8)]
        sc.covers = [Cover(name="", nmbr=-1, type=0) for _ in range(5)]
        sc.dimmers = [Dimmer(name="", nmbr=i, type=-1) for i in range(2)]
        sc.leds = [Led(name="", nmbr=i, type=0) for i in range(9)]
        if typ[1] == 4:  # Smart Touch
            sc.color_leds = [
                ColorLed(name="", nmbr=i, type=4, rgb=[0, 0, 0, 0]) for i in range(5)
            ]
        sc.diags = [Diagnostic(name="", nmbr=i, type=0) for i in range(2)]
        sc.setvalues = [
            SetValue(name="Set temperature", nmbr=0, type=2, value=20.0),
            SetValue(name="Set temperature 2", nmbr=1, type=2, value=20.0),
        ]
        sc.sensors = [
            Sensor(name="Movement", nmbr=0, type=2, value=0),
            Sensor(name="Temperature", nmbr=1, type=2, value=0),
            Sensor(name="Temperature ext.", nmbr=2, type=2, value=0),
            Sensor(name="Humidity", nmbr=3, type=2, value=0),
            Sensor(name="Illuminance", nmbr=4, type=2, value=0),
            Sensor(name="Airquality", nmbr=5, type=2, value=0),
        ]
        sc.diags.append(Diagnostic(name="PowerTemp", nmbr=1, type=1))
        return sc

    module = Module(
        uid=uid,
        addr=addr,
        typ=typ,
        name=name,
        mod_type=mod_type,
        group=group,
        diags=_base_diags(),
    )

    if kind == "mini":
        module.inputs = [Input(name="", nmbr=i, type=1) for i in range(6)]
        module.outputs = [Output(name="", nmbr=i, type=1) for i in range(2)]
        module.color_leds = [
            ColorLed(name="", nmbr=i, type=4, rgb=[0, 0, 0, 0]) for i in range(5)
        ]
        module.diags = [Diagnostic(name="", nmbr=0, type=0)]
        module.setvalues = [
            SetValue(name="Set temperature", nmbr=0, type=2, value=20.0),
            SetValue(name="Set temperature 2", nmbr=1, type=2, value=20.0),
        ]
        module.sensors = [
            Sensor(name="Movement", nmbr=0, type=2, value=0),
            Sensor(name="Temperature", nmbr=1, type=2, value=0),
            Sensor(name="Illuminance", nmbr=2, type=2, value=0),
            Sensor(name="Airquality", nmbr=3, type=2, value=0),
        ]
    elif kind == "out":
        module.outputs = [Output(name="", nmbr=i, type=1) for i in range(8)]
        module.covers = [Cover(name="", nmbr=-1, type=0) for _ in range(4)]
    elif kind == "dimm":
        module.outputs = [Output(name="", nmbr=i, type=2) for i in range(4)]
        module.dimmers = [Dimmer(name="", nmbr=i, type=2) for i in range(4)]
        module.diags.append(Diagnostic(name="PowerTemp", nmbr=1, type=1))
    elif kind == "io2":
        module.outputs = [Output(name="", nmbr=i, type=1) for i in range(2)]
        module.inputs = [Input(name="", nmbr=i, type=1) for i in range(2)]
        module.diags = [Diagnostic(name="", nmbr=0, type=0)]
        module.covers = [Cover(name="", nmbr=-1, type=0)]
    elif kind == "in":
        module.inputs = [Input(name="", nmbr=i, type=1) for i in range(8)]
        if typ[1] == 0x1F:
            module.analogins = [Input(name="", nmbr=i, type=-3) for i in range(6)]
    elif kind == "detect":
        module.sensors = [
            Sensor(name="Movement", nmbr=0, type=2, value=0),
            Sensor(name="Illuminance", nmbr=1, type=2, value=0),
        ]
    elif kind == "nature":
        module.sensors = [
            Sensor(name="Temperature", nmbr=0, type=2, value=0),
            Sensor(name="Humidity", nmbr=1, type=2, value=0),
            Sensor(name="Illuminance", nmbr=2, type=2, value=0),
            Sensor(name="Wind", nmbr=3, type=2, value=0),
            Sensor(name="Rain", nmbr=4, type=0, value=0),
            Sensor(name="Windpeak", nmbr=5, type=2, value=0),
        ]
    elif kind == "sensor":
        module.sensors = [Sensor(name="Temperature", nmbr=0, type=2, value=0)]
        module.setvalues = [
            SetValue(name="Set temperature", nmbr=0, type=2, value=20.0)
        ]
    elif kind == "ekey":
        module.sensors = [
            Sensor(name="Identifier", nmbr=0, type=2, value=0),
            Sensor(name="Finger", nmbr=1, type=2, value=0),
        ]
        module.fingers = [Finger(name="Finger", nmbr=0, type=2)]
    # "gsm" and "generic" keep the base lists only.

    return module


def apply_status(module: Module, status: bytes) -> None:
    """Parse a compact-status block into ``module`` and fire change listeners."""
    module.mode = status[MStatIdx.MODE]

    # Discover counter logic elements lazily on the first status.
    if not module.logic:
        cnt = 0
        for l_idx in range(10):
            if status[MStatIdx.COUNTER + 3 * l_idx] == 5:
                module.logic.append(
                    Logic(name=f"Counter {cnt + 1}", nmbr=cnt, idx=l_idx, type=5)
                )
                cnt += 1
        if not module.logic:
            module.logic.append(Logic(name="NotAvailable", nmbr=0, idx=0, type=-5))
    for lgc in module.logic:
        _set(lgc, "value", status[MStatIdx.COUNTER_VAL + 3 * lgc.nmbr])

    _STATUS_PARSERS.get(_module_kind(module.typ), _status_generic)(module, status)


def _status_controller(m: Module, s: bytes) -> None:
    """Smart Controller (XL / Touch) status."""
    _set(m.sensors[0], "value", int(s[MStatIdx.MOV]))
    _set(m.sensors[1], "value", _u16(s, MStatIdx.TEMP_ROOM) / 10)
    _set(m.sensors[2], "value", _u16(s, MStatIdx.TEMP_EXT) / 10)
    _set(m.sensors[3], "value", int(s[MStatIdx.HUM]))
    _set(m.sensors[4], "value", int(s[MStatIdx.LUM]) * 10)
    _set(m.sensors[5], "value", int(s[MStatIdx.AQI]))
    _set(m.setvalues[0], "value", _u16(s, MStatIdx.T_SETP_0) / 10)
    _set(m.setvalues[1], "value", _u16(s, MStatIdx.T_SETP_1) / 10)

    out_state = int.from_bytes(s[MStatIdx.OUT_1_8 : MStatIdx.OUT_1_8 + 3], "little")
    for outpt in m.outputs[:-1]:
        _set(outpt, "is_on", bool(out_state & (0x01 << outpt.nmbr)))
    if m.analog_outputs:
        _set(m.analog_outputs[0], "brightness", int(s[MStatIdx.AOUT_1]))
    _set(m.dimmers[0], "brightness", int(s[MStatIdx.DIM_1]))
    _set(m.dimmers[1], "brightness", int(s[MStatIdx.DIM_2]))

    led_state = out_state >> 15
    for led in m.leds:
        _set(led, "is_on", bool(led_state & (0x01 << led.nmbr)))

    if m.typ[1] == 4:  # Smart Touch colour LEDs
        cled_state = s[MStatIdx.RGB_MASK]
        for cled in m.color_leds:
            base = MStatIdx.RGB_MASK + 3 * cled.nmbr
            _set(cled, "is_on", bool(cled_state & (0x01 << cled.nmbr)))
            _set(cled, "rgb", [int(s[base + 1]), int(s[base + 2]), int(s[base + 3]), 0])

    for cover in m.covers:
        if cover.nmbr >= 0:
            cm_idx = cover.nmbr - 2
            if cm_idx < 0:
                cm_idx += 5
            _set(cover, "position", int(s[MStatIdx.ROLL_POS + cm_idx]))
            _set(cover, "tilt", int(s[MStatIdx.BLAD_POS + cm_idx]))

    inp_state = int.from_bytes(s[MStatIdx.INP_1_8 : MStatIdx.INP_1_8 + 3], "little")
    for inp in m.inputs:
        if inp.nmbr >= 0 and inp.type != 3:
            _set(inp, "value", int(bool(inp_state & (0x01 << inp.nmbr))))

    flags_state = int.from_bytes(s[MStatIdx.FLAG_LOC : MStatIdx.FLAG_LOC + 2], "little")
    for flg in m.flags:
        _set(flg, "value", int(bool(flags_state & (0x01 << (flg.nmbr - 1)))))

    if m.typ[1] > 2:
        _set(m.analogins[0], "value", int(s[MStatIdx.AD_1]))
        _set(m.analogins[1], "value", int(s[MStatIdx.AD_2]))

    _set(m.diags[0], "value", s[MStatIdx.MODULE_STAT])
    _set(m.diags[1], "value", _u16(s, MStatIdx.TEMP_PWR) / 10)
    m.climate_settings = int(s[MStatIdx.CLIM_MODE])
    m.climate_ctl12 = int(s[MStatIdx.CLIM_CTL12])


def _status_mini(m: Module, s: bytes) -> None:
    """Smart Controller Mini status."""
    _set(m.sensors[0], "value", int(s[MStatIdx.MOV]))
    _set(m.sensors[1], "value", _u16(s, MStatIdx.TEMP_ROOM) / 10)
    _set(m.sensors[2], "value", int(s[MStatIdx.LUM]) * 10)
    _set(m.sensors[3], "value", int(s[MStatIdx.AQI]))
    _set(m.setvalues[0], "value", _u16(s, MStatIdx.T_SETP_0) / 10)
    _set(m.setvalues[1], "value", _u16(s, MStatIdx.T_SETP_1) / 10)

    out_state = int.from_bytes(s[MStatIdx.OUT_1_8 : MStatIdx.OUT_1_8 + 3], "little")
    for outpt in m.outputs:
        _set(outpt, "is_on", bool(out_state & (0x01 << outpt.nmbr)))
    for cled in m.color_leds:
        _set(cled, "is_on", bool(out_state & (0x01 << (cled.nmbr + 15))))

    inp_state = int.from_bytes(s[MStatIdx.INP_1_8 : MStatIdx.INP_1_8 + 3], "little")
    for inp in m.inputs:
        if inp.nmbr >= 0:
            _set(inp, "value", int(bool(inp_state & (0x01 << inp.nmbr))))

    flags_state = int.from_bytes(s[MStatIdx.FLAG_LOC : MStatIdx.FLAG_LOC + 2], "little")
    for flg in m.flags:
        _set(flg, "value", int(bool(flags_state & (0x01 << (flg.nmbr - 1)))))

    _set(m.diags[0], "value", s[MStatIdx.MODULE_STAT])
    m.climate_settings = int(s[MStatIdx.CLIM_MODE])
    m.climate_ctl12 = int(s[MStatIdx.CLIM_CTL12])


def _status_out(m: Module, s: bytes) -> None:
    """Smart Output status."""
    out_state = int(s[MStatIdx.OUT_1_8])
    for outpt in m.outputs:
        _set(outpt, "is_on", bool(out_state & (0x01 << outpt.nmbr)))
    for cover in m.covers:
        if cover.nmbr >= 0:
            _set(cover, "position", int(s[MStatIdx.ROLL_POS + cover.nmbr]))
            _set(cover, "tilt", int(s[MStatIdx.BLAD_POS + cover.nmbr]))
    _set(m.diags[0], "value", s[MStatIdx.MODULE_STAT])


def _status_dimm(m: Module, s: bytes) -> None:
    """Smart Dimm status."""
    out_state = int(s[MStatIdx.OUT_1_8])
    for outpt in m.outputs:
        _set(outpt, "is_on", bool(out_state & (0x01 << outpt.nmbr)))
    _set(m.dimmers[0], "brightness", int(s[MStatIdx.DIM_1]))
    _set(m.dimmers[1], "brightness", int(s[MStatIdx.DIM_2]))
    _set(m.dimmers[2], "brightness", int(s[MStatIdx.DIM_3]))
    _set(m.dimmers[3], "brightness", int(s[MStatIdx.DIM_4]))
    _set(m.diags[0], "value", s[MStatIdx.MODULE_STAT])
    _set(m.diags[1], "value", round(_u16(s, MStatIdx.TEMP_PWR) / 10))


def _status_io2(m: Module, s: bytes) -> None:
    """Smart IO 2 status."""
    inp_state = int(s[MStatIdx.INP_1_8])
    for inp in m.inputs:
        if inp.nmbr >= 0:
            _set(inp, "value", int(bool(inp_state & (0x01 << inp.nmbr))))
    out_state = int(s[MStatIdx.OUT_1_8])
    for outpt in m.outputs:
        _set(outpt, "is_on", bool(out_state & (0x01 << outpt.nmbr)))
    if m.covers and m.covers[0].nmbr >= 0:
        _set(m.covers[0], "position", int(s[MStatIdx.ROLL_POS - 1]))
        _set(m.covers[0], "tilt", int(s[MStatIdx.BLAD_POS - 1]))
    _set(m.diags[0], "value", s[MStatIdx.MODULE_STAT])


def _status_in(m: Module, s: bytes) -> None:
    """Smart Input status."""
    ad_val_map = {
        0: MStatIdx.AD_1,
        1: MStatIdx.AD_2,
        2: MStatIdx.GEN_1,
        3: MStatIdx.GEN_2,
        4: MStatIdx.GEN_3,
        5: MStatIdx.GEN_4,
    }
    inp_state = int(s[MStatIdx.INP_1_8])
    for inp in m.inputs:
        if inp.nmbr >= 0 and inp.type != 3:
            _set(inp, "value", int(bool(inp_state & (0x01 << inp.nmbr))))
    for anlgin in m.analogins:
        _set(anlgin, "value", int(s[ad_val_map[anlgin.nmbr]]))
    _set(m.diags[0], "value", s[MStatIdx.MODULE_STAT])


def _status_detect(m: Module, s: bytes) -> None:
    """Smart Detect status."""
    _set(m.sensors[0], "value", int(s[MStatIdx.MOV]))
    _set(m.sensors[1], "value", int(s[MStatIdx.LUM]) * 10)
    _set(m.diags[0], "value", s[MStatIdx.MODULE_STAT])


def _status_nature(m: Module, s: bytes) -> None:
    """Smart Nature status."""
    temp = _u16(s, MStatIdx.TEMP_ROOM)
    if temp > 32767:  # negative temperature
        temp = -(temp & 0x7FFF)
    prev_wind = m.sensors[3].value
    prev_wind = prev_wind if isinstance(prev_wind, (int, float)) else 0
    _set(m.sensors[0], "value", temp / 10)
    _set(m.sensors[1], "value", int(s[MStatIdx.HUM]))
    _set(m.sensors[2], "value", _u16(s, MStatIdx.LUM))
    _set(m.sensors[3], "value", 0.8 * prev_wind + 0.2 * int(s[MStatIdx.WIND]))
    _set(m.sensors[4], "value", int(s[MStatIdx.RAIN]))
    _set(m.sensors[5], "value", int(s[MStatIdx.WINDP]))
    _set(m.diags[0], "value", s[MStatIdx.MODULE_STAT])


def _status_sensor(m: Module, s: bytes) -> None:
    """Smart Sensor status."""
    temp = _u16(s, MStatIdx.TEMP_ROOM)
    if temp > 32767:  # negative temperature
        temp = -(temp & 0x7FFF)
    _set(m.sensors[0], "value", temp / 10)
    _set(m.setvalues[0], "value", _u16(s, MStatIdx.T_SETP_0) / 10)
    _set(m.diags[0], "value", s[MStatIdx.MODULE_STAT])


def _status_ekey(m: Module, s: bytes) -> None:
    """Smart eKey status."""
    id_val = int(s[MStatIdx.KEY_ID])
    fin_val = int(s[MStatIdx.KEY_ID + 1])
    if fin_val > 10:
        id_val *= -1  # disable
        fin_val -= 128
    _set(m.sensors[0], "value", id_val)
    _set(m.sensors[1], "value", fin_val)
    _set(m.diags[0], "value", s[MStatIdx.MODULE_STAT])


def _status_generic(m: Module, s: bytes) -> None:
    """GSM and unknown modules: only the shared base values apply."""


_STATUS_PARSERS = {
    "controller": _status_controller,
    "mini": _status_mini,
    "out": _status_out,
    "dimm": _status_dimm,
    "io2": _status_io2,
    "in": _status_in,
    "detect": _status_detect,
    "nature": _status_nature,
    "sensor": _status_sensor,
    "ekey": _status_ekey,
    "gsm": _status_generic,
    "generic": _status_generic,
}
