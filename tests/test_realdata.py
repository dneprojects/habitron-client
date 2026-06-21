"""Real-hardware-derived tests for the event + colour-LED status handling.

The tuples and colour values below were harvested from DEBUG logs of a live
installation: the exact push events the modules' firmware sent, and the colour
values the status parser produced. They lock the handling against what the real
devices actually emit — the area the 2.0.x event/colour-LED rework touched.

The colour-LED material comes from a **Smart Controller Mini** (module 9); the
module-scoped event tuples below cover every other event type seen on the bus
(buttons, switches, outputs, covers, blinds, dimmers, flags, mode) keyed to the
module that emitted them.
"""

import pytest

from habitron_client._events import apply_event
from habitron_client._indices import HaEvents, MStatIdx
from habitron_client._parse import apply_status, build_module
from habitron_client._parse_router import build_router
from habitron_client.model import Flag, Module, Router

_MINI_TYP = b"\x32\x01"

# Real 2-byte type codes of the modules on the live bus. The router id is 100, so
# a module's bus address is ``100 + mod_id`` — the id its events arrive with.
_REAL_TYPES = {
    "xl2": b"\x01\x02",  # Smart Controller XL-2    (mod 2)
    "dimm2": b"\x0a\x16",  # Smart Dimm-2           (mod 3)
    "in24": b"\x0b\x1f",  # Smart In 8/24V-1        (mod 4)
    "out8r": b"\x0a\x32",  # Smart Out 8/R-1        (mod 7)
    "mini": _MINI_TYP,  # Smart Controller Mini     (mod 9)
    "touch": b"\x01\x04",  # Smart Controller Touch (mod 10)
}


def _module(kind: str, mod_id: int) -> Module:
    return build_module(
        uid=f"UID{mod_id}",
        addr=100 + mod_id,
        typ=_REAL_TYPES[kind],
        name=kind,
        group=0,
    )


def _mini() -> Module:
    return _module("mini", 9)


def _mini_router() -> Router:
    rt = build_router(b_uid="UID")
    rt.modules = [_mini()]
    return rt


def _router_with(*modules: Module) -> Router:
    rt = build_router(b_uid="UID")
    rt.modules = list(modules)
    return rt


# Real RGB push events captured from the Mini (module 9):
# (cled index, mode, r, g, b) — mode 0 = off, 1 = on, 2 = colour change.
_REAL_RGB_EVENTS = [
    (0, 2, 255, 175, 15),
    (0, 2, 255, 201, 10),
    (3, 2, 252, 252, 252),
    (3, 2, 106, 7, 255),
    (3, 2, 44, 3, 107),
    (3, 2, 99, 14, 255),
    (3, 2, 7, 1, 18),
    (0, 1, 0, 0, 0),
    (1, 1, 0, 0, 0),
    (2, 0, 0, 0, 0),
    (4, 0, 0, 0, 0),
]


@pytest.mark.parametrize(("cled", "mode", "r", "g", "b"), _REAL_RGB_EVENTS)
def test_real_rgb_events_apply(cled: int, mode: int, r: int, g: int, b: int) -> None:
    """Each real RGB event lands its on/off + colour on the right colour LED."""
    rt = _mini_router()
    led = rt.modules[0].color_leds[cled]
    apply_event(rt, 9, HaEvents.RGB, cled, mode, r, g, b)
    if mode == 2:
        assert led.is_on is True
        assert led.rgb == [r, g, b, 0]
    else:
        assert led.is_on is bool(mode)


def test_real_move_event_toggles_movement_sensor() -> None:
    """A real MOVE event (module 9) drives the movement sensor on/off."""
    rt = _mini_router()
    movement = rt.modules[0].sensors[0]  # Movement
    apply_event(rt, 9, HaEvents.MOVE, 0, 2, 0, 0, 0)  # active
    assert movement.value == 1
    apply_event(rt, 9, HaEvents.MOVE, 0, 0, 0, 0, 0)  # cleared
    assert movement.value == 0


# Real colour values the status parser produced for the Mini's five colour LEDs.
_REAL_MINI_CLED_COLOURS = {
    0: [255, 137, 14, 0],
    1: [1, 29, 255, 0],
    2: [12, 255, 182, 0],
    3: [1, 1, 1, 0],  # minimal-on ([0,0,0] = off; magnitude is the brightness)
    4: [255, 10, 189, 0],
}


def test_real_mini_status_colours_all_five_cleds() -> None:
    """A status carrying real per-LED colours parses each one from RGB_MASK.

    Exercising all five at once guards against offset/overlap bugs in the
    RGB-mask colour read.
    """
    mini = _mini()
    status = bytearray(MStatIdx.END)
    status[MStatIdx.RGB_MASK] = 0b11111  # all five colour LEDs on
    for nmbr, (r, g, b, _w) in _REAL_MINI_CLED_COLOURS.items():
        base = MStatIdx.RGB_MASK + 3 * nmbr
        status[base + 1], status[base + 2], status[base + 3] = r, g, b
    apply_status(mini, bytes(status))
    for nmbr, rgb in _REAL_MINI_CLED_COLOURS.items():
        assert mini.color_leds[nmbr].is_on is True
        assert mini.color_leds[nmbr].rgb == rgb


# --- Module-scoped push events harvested from the live bus -----------------
# Each tuple is ``(kind, mod_id, ...)``; mod_id is the bus id the event carried.


# BUTTON (event 1): a press code (1 short, 2 down, 3 long) on input ``btn``.
# Codes 1/3 self-reset to 0 after firing; code 2 (held) stays until released.
_REAL_BUTTON_EVENTS = [  # (kind, mod_id, btn, press_code)
    ("xl2", 2, 3, 2),
    ("xl2", 2, 6, 1),
    ("mini", 9, 1, 2),
    ("mini", 9, 2, 3),
    ("touch", 10, 2, 1),
    ("touch", 10, 5, 2),
    ("touch", 10, 7, 3),
]


@pytest.mark.parametrize(("kind", "mod_id", "btn", "code"), _REAL_BUTTON_EVENTS)
def test_real_button_events(kind: str, mod_id: int, btn: int, code: int) -> None:
    """A real button press lands its code, self-resetting on 1/3."""
    module = _module(kind, mod_id)
    rt = _router_with(module)
    apply_event(rt, mod_id, HaEvents.BUTTON, btn, code)
    expected = 0 if code in (1, 3) else code
    assert module.inputs[btn - 1].value == expected


# SWITCH (event 2): a real on/off from a Smart In 8/24V-1 input.
_REAL_SWITCH_EVENTS = [("in24", 4, 1, 0), ("in24", 4, 1, 1)]


@pytest.mark.parametrize(("kind", "mod_id", "inp", "val"), _REAL_SWITCH_EVENTS)
def test_real_switch_events(kind: str, mod_id: int, inp: int, val: int) -> None:
    """A real switch event sets the input to its on/off value."""
    module = _module(kind, mod_id)
    rt = _router_with(module)
    apply_event(rt, mod_id, HaEvents.SWITCH, inp, val)
    assert module.inputs[inp - 1].value == val


# OUTPUT (event 3): a relay/output toggling on (1) and off (0).
_REAL_OUTPUT_EVENTS = [
    ("out8r", 7, 1, 1),
    ("out8r", 7, 1, 0),
    ("dimm2", 3, 1, 1),
    ("xl2", 2, 1, 1),
    ("xl2", 2, 1, 0),
    ("touch", 10, 1, 1),
]


@pytest.mark.parametrize(("kind", "mod_id", "out", "val"), _REAL_OUTPUT_EVENTS)
def test_real_output_events(kind: str, mod_id: int, out: int, val: int) -> None:
    """A real output event drives the relay's on/off state."""
    module = _module(kind, mod_id)
    rt = _router_with(module)
    apply_event(rt, mod_id, HaEvents.OUTPUT, out, val)
    assert module.outputs[out - 1].is_on is bool(val)


# COV_VAL (event 4): a real cover position update (0..100 %).
_REAL_COVER_POSITIONS = [
    ("xl2", 2, 2, 84),
    ("xl2", 2, 2, 100),
    ("out8r", 7, 0, 0),
    ("out8r", 7, 0, 72),
]


@pytest.mark.parametrize(("kind", "mod_id", "cov", "pos"), _REAL_COVER_POSITIONS)
def test_real_cover_position_events(kind: str, mod_id: int, cov: int, pos: int) -> None:
    """A real cover-position event lands on the addressed cover."""
    module = _module(kind, mod_id)
    rt = _router_with(module)
    apply_event(rt, mod_id, HaEvents.COV_VAL, cov, pos)
    assert module.covers[cov].position == pos


def test_real_blind_tilt_event() -> None:
    """A real blind-tilt (BLD_VAL) event sets the cover's tilt."""
    module = _module("out8r", 7)
    rt = _router_with(module)
    apply_event(rt, 7, HaEvents.BLD_VAL, 0, 45)
    assert module.covers[0].tilt == 45


# DIM_VAL (event 6): a real Smart Dimm-2 brightness update.
_REAL_DIM_EVENTS = [("dimm2", 3, 0, 46), ("dimm2", 3, 0, 79)]


@pytest.mark.parametrize(("kind", "mod_id", "dim", "level"), _REAL_DIM_EVENTS)
def test_real_dim_events(kind: str, mod_id: int, dim: int, level: int) -> None:
    """A real dimmer event sets the channel brightness."""
    module = _module(kind, mod_id)
    rt = _router_with(module)
    apply_event(rt, mod_id, HaEvents.DIM_VAL, dim, level)
    assert module.dimmers[dim].brightness == level


# FLAG (event 9): a real local module flag toggling on a Touch controller.
_REAL_FLAG_EVENTS = [(15, 1), (15, 0), (16, 1), (16, 0)]


@pytest.mark.parametrize(("flag_no", "val"), _REAL_FLAG_EVENTS)
def test_real_module_flag_events(flag_no: int, val: int) -> None:
    """A real module-flag event updates the matching flag's value."""
    module = _module("touch", 10)
    module.flags = [Flag(name="flag", nmbr=15), Flag(name="flag", nmbr=16)]
    rt = _router_with(module)
    apply_event(rt, 10, HaEvents.FLAG, flag_no, val)
    flag = next(f for f in module.flags if f.nmbr == flag_no)
    assert flag.value == val


# MODE (event 15): a real router-wide mode change. The event is reported *by* a
# module (mod_id != 0) but ``arg1 == 0`` scopes it to the whole router.
_REAL_MODE_EVENTS = [49, 53]


@pytest.mark.parametrize("mode", _REAL_MODE_EVENTS)
def test_real_router_mode_events(mode: int) -> None:
    """A real router mode event updates the router's mode value."""
    rt = _router_with(_module("xl2", 2))
    apply_event(rt, 2, HaEvents.MODE, 0, mode)
    assert rt.mode.value == mode
