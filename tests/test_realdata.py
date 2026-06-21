"""Real-hardware-derived tests for the event + colour-LED status handling.

The tuples and colour values below were harvested from DEBUG logs of a live
**Smart Controller Mini** (module 9): the exact ``(cled, mode, r, g, b)`` RGB
push events the firmware sent, and the colour values the status parser produced.
They lock the handling against what the real device actually emits — the area
the 2.0.1 colour-LED unification touched.
"""

import pytest

from habitron_client._events import apply_event
from habitron_client._indices import HaEvents, MStatIdx
from habitron_client._parse import apply_status, build_module
from habitron_client._parse_router import build_router
from habitron_client.model import Module, Router

_MINI_TYP = b"\x32\x01"


def _mini() -> Module:
    return build_module(uid="UID9", addr=109, typ=_MINI_TYP, name="Mini", group=0)


def _mini_router() -> Router:
    rt = build_router(b_uid="UID")
    rt.modules = [_mini()]
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
