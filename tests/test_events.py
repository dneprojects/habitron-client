"""Tests for :func:`habitron_client._events.apply_event`.

``apply_event`` is the push-event path: a raw event tuple from the SmartHub
event server updates the matching member and fires its listeners. These exercise
every event branch and assert both the new value and that the member notified.
"""

from habitron_client._events import apply_event
from habitron_client._indices import HaEvents
from habitron_client._parse import build_module
from habitron_client._parse_router import build_router
from habitron_client.model import BusMember, Cover, Flag, Logic, Module, Router


def _fired(member: BusMember) -> list[bool]:
    """Attach a listener and return a one-element list set True on notify."""
    flag = [False]

    def _cb() -> None:
        flag[0] = True

    member.add_listener(_cb)
    return flag


def _router_with(*modules: Module) -> Router:
    rt = build_router(b_uid="UID")
    rt.modules = list(modules)
    return rt


def _sc() -> Module:
    return build_module(uid="UID5", addr=105, typ=b"\x01\x03", name="SC", group=0)


# --------------------------------------------------------------------------- #
# Router-scoped events                                                          #
# --------------------------------------------------------------------------- #


def test_router_flag_event_updates_value() -> None:
    rt = _router_with()
    rt.flags = [Flag(name="f", nmbr=2, idx=0, value=0)]
    fired = _fired(rt.flags[0])
    apply_event(rt, 0, HaEvents.FLAG, 2, 1)
    assert rt.flags[0].value == 1
    assert fired[0]


def test_mode_event_arg1_zero_sets_router_mode() -> None:
    rt = _router_with(_sc())
    fired = _fired(rt.mode)
    apply_event(rt, 5, HaEvents.MODE, 0, 0x20)
    assert rt.mode.value == 0x20
    assert fired[0]


def test_mode_event_group_sets_module_mode() -> None:
    sc = _sc()
    rt = _router_with(sc)
    rt.module_grp = [3]  # group 3 → module index 0
    fired = _fired(sc.mode)
    apply_event(rt, 5, HaEvents.MODE, 3, 0x50)
    assert sc.mode.value == 0x50
    assert fired[0]


def test_unknown_module_is_ignored() -> None:
    rt = _router_with(_sc())
    apply_event(rt, 99, HaEvents.SWITCH, 1, 1)  # no module at addr 199 → no raise


# --------------------------------------------------------------------------- #
# Module-scoped events                                                          #
# --------------------------------------------------------------------------- #


def test_button_event_pulses_then_resets() -> None:
    sc = _sc()
    rt = _router_with(sc)
    fired = _fired(sc.inputs[0])
    apply_event(rt, 5, HaEvents.BUTTON, 1, 1)  # short press → set then reset
    assert sc.inputs[0].value == 0
    assert fired[0]


def test_switch_event_sets_input_value() -> None:
    sc = _sc()
    rt = _router_with(sc)
    apply_event(rt, 5, HaEvents.SWITCH, 2, 1)
    assert sc.inputs[1].value == 1


def test_output_event_sets_output_on() -> None:
    sc = _sc()
    rt = _router_with(sc)
    fired = _fired(sc.outputs[0])
    apply_event(rt, 5, HaEvents.OUTPUT, 1, 1)
    assert sc.outputs[0].is_on is True
    assert fired[0]


def test_output_event_high_arg_sets_led() -> None:
    sc = _sc()
    rt = _router_with(sc)
    apply_event(rt, 5, HaEvents.OUTPUT, 16, 1)  # arg1 > 15 → led 0
    assert sc.leds[0].is_on is True


def test_output_event_notifies_backed_cover() -> None:
    out = build_module(uid="UID5", addr=105, typ=b"\x0a\x01", name="Out", group=0)
    out.outputs[0].type = -10  # cover-backing output
    out.outputs[1].type = -10
    out.covers[0] = Cover(name="Sh", nmbr=0, type=1)
    rt = _router_with(out)
    cover_fired = _fired(out.covers[0])
    apply_event(rt, 5, HaEvents.OUTPUT, 1, 1)
    assert out.outputs[0].is_on is True
    assert cover_fired[0]


def test_rgb_event_full_value_sets_color() -> None:
    sc = build_module(uid="UID5", addr=105, typ=b"\x01\x04", name="Touch", group=0)
    rt = _router_with(sc)
    fired = _fired(sc.color_leds[0])
    apply_event(rt, 5, HaEvents.RGB, 0, 2, 10, 20, 30)
    assert sc.color_leds[0].is_on is True
    assert sc.color_leds[0].rgb == [10, 20, 30, 0]
    assert fired[0]


def test_rgb_event_on_off_toggle() -> None:
    sc = build_module(uid="UID5", addr=105, typ=b"\x01\x04", name="Touch", group=0)
    rt = _router_with(sc)
    apply_event(rt, 5, HaEvents.RGB, 0, 0)
    assert sc.color_leds[0].is_on is False


def test_finger_event_sets_identifier_and_finger() -> None:
    ek = build_module(uid="UID5", addr=105, typ=b"\x1e\x01", name="ekey", group=0)
    rt = _router_with(ek)
    sens_fired = _fired(ek.sensors[0])
    fin_fired = _fired(ek.fingers[0])
    apply_event(rt, 5, HaEvents.FINGER, 7, 3)  # arg2 <= 10 → positive id
    assert ek.sensors[0].value == 7
    assert ek.fingers[0].user == 7
    assert ek.fingers[0].value == 3
    assert sens_fired[0]
    assert fin_fired[0]


def test_finger_event_disabled_user_negates_id() -> None:
    ek = build_module(uid="UID5", addr=105, typ=b"\x1e\x01", name="ekey", group=0)
    rt = _router_with(ek)
    apply_event(rt, 5, HaEvents.FINGER, 7, 12)  # arg2 > 10 → negative id
    assert ek.sensors[0].value == -7


def test_dim_value_event_sets_brightness() -> None:
    sc = _sc()
    rt = _router_with(sc)
    fired = _fired(sc.dimmers[0])
    apply_event(rt, 5, HaEvents.DIM_VAL, 0, 77)
    assert sc.dimmers[0].brightness == 77
    assert fired[0]


def test_cover_position_and_tilt_events() -> None:
    sc = _sc()
    sc.covers[0] = Cover(name="Sh", nmbr=0, type=1)
    rt = _router_with(sc)
    apply_event(rt, 5, HaEvents.COV_VAL, 0, 40)
    apply_event(rt, 5, HaEvents.BLD_VAL, 0, 15)
    assert sc.covers[0].position == 40
    assert sc.covers[0].tilt == 15


def test_move_event_sets_sensor() -> None:
    sc = _sc()
    rt = _router_with(sc)
    apply_event(rt, 5, HaEvents.MOVE, 0, 1)
    assert sc.sensors[0].value == 1


def test_module_flag_event_updates_matching_flag() -> None:
    sc = _sc()
    sc.flags = [Flag(name="f", nmbr=4, idx=0, value=0)]
    rt = _router_with(sc)
    fired = _fired(sc.flags[0])
    apply_event(rt, 5, HaEvents.FLAG, 4, 1)
    assert sc.flags[0].value == 1
    assert fired[0]


def test_counter_value_event_updates_logic() -> None:
    sc = _sc()
    sc.logic = [Logic(name="c", nmbr=0, idx=0, type=5, value=0)]
    rt = _router_with(sc)
    fired = _fired(sc.logic[0])
    apply_event(rt, 5, HaEvents.CNT_VAL, 0, 42)
    assert sc.logic[0].value == 42
    assert fired[0]


def test_bad_event_args_are_caught_not_raised() -> None:
    """An out-of-range arg is logged and swallowed, not raised."""
    sc = _sc()
    rt = _router_with(sc)
    apply_event(rt, 5, HaEvents.DIM_VAL, 99, 1)  # no dimmer 99 → caught
