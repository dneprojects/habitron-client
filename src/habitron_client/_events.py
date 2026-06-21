"""Apply a push event from the SmartHub event server to the model.

Ports ``HbtnComm.update_entity``: a raw event (module id, event type, args)
updates the matching member's value and fires its listeners. Unlike the polled
status path this always notifies — an event (e.g. a button press) must reach the
consumer even when the value is unchanged.

The integration's HA-only timing quirks are intentionally dropped: the finger
pulse no longer sleeps-and-resets here (the consumer's event entity owns that),
and the per-member listener is the generic ``Callable[[], None]`` — payload such
as the button press code is carried on the member's ``value``.
"""

from __future__ import annotations

import logging
import math

from ._indices import HaEvents
from .model import Module, Router

_LOGGER = logging.getLogger(__name__)

# Reverse map event code -> name, for readable debug logs.
_EVENT_NAMES: dict[int, str] = {
    v: k for k, v in vars(HaEvents).items() if isinstance(v, int)
}


def _get_module(router: Router, mod_id: int) -> Module | None:
    """Return the module whose raw (bus) address matches ``mod_id``."""
    for module in router.modules:
        if module.addr - router.id == mod_id:
            return module
    return None


def _cover_index(module: Module, out_no: int) -> int:
    """Return the cover index backed by output ``out_no`` (or -1)."""
    idx = out_no - 1
    if 0 <= idx < len(module.outputs) and module.outputs[idx].type == -10:
        return math.ceil(out_no / 2) - 1
    return -1


def apply_event(
    router: Router,
    mod_id: int,
    evnt: int,
    arg1: int,
    arg2: int,
    arg3: int = 0,
    arg4: int = 0,
    arg5: int = 0,
) -> None:
    """Update the model from a SmartHub event and fire member listeners."""
    _LOGGER.debug(
        "event: mod_id=%s type=%s args=%s",
        mod_id,
        _EVENT_NAMES.get(evnt, evnt),
        (arg1, arg2, arg3, arg4, arg5),
    )
    if mod_id == 0:
        if evnt == HaEvents.FLAG:
            for flg in router.flags:
                if flg.nmbr == arg1:
                    flg.value = arg2
                    flg.notify()
                    break
            return
    elif evnt == HaEvents.MODE:
        if arg1 == 0:
            router.mode.value = arg2
            router.mode.notify()
        else:
            module = router.modules[router.module_grp.index(arg1)]
            module.mode.value = arg2
            module.mode.notify()
        return

    target = _get_module(router, mod_id)
    if target is None:
        _LOGGER.error("No module found for mod_id %s", mod_id)
        return

    try:
        _apply_module_event(target, evnt, arg1, arg2, arg3, arg4, arg5)
    except Exception as err_msg:
        _LOGGER.warning(
            "Error handling habitron event %s with arg1 %s of module %s: %s",
            evnt,
            arg1,
            mod_id,
            err_msg,
        )


def _apply_module_event(
    module: Module,
    evnt: int,
    arg1: int,
    arg2: int,
    arg3: int,
    arg4: int,
    arg5: int,
) -> None:
    """Dispatch a module-scoped event to the matching member."""
    if evnt == HaEvents.BUTTON:
        inp = module.inputs[arg1 - 1]
        inp.value = arg2  # press code (0..3)
        inp.notify()
        if arg2 in (1, 3):  # reset to inactive after a (long-)press
            inp.value = 0
            inp.notify()
    elif evnt == HaEvents.SWITCH:
        inp = module.inputs[arg1 - 1]
        inp.value = arg2
        inp.notify()
    elif evnt == HaEvents.OUTPUT:
        if arg1 > 15:  # LED
            led = module.leds[arg1 - 16]
            led.is_on = bool(arg2)
            led.notify()
        elif module.typ[0] == 50 and arg1 > 2:
            module.leds[arg1 - 2 - 1].notify()
        else:
            outpt = module.outputs[arg1 - 1]
            outpt.is_on = bool(arg2)
            outpt.notify()
            if (c_idx := _cover_index(module, arg1)) >= 0:
                module.covers[c_idx].notify()
    elif evnt == HaEvents.RGB:
        cled = module.color_leds[arg1]
        if arg2 == 2:  # full RGB value change
            cled.is_on = True
            cled.rgb = [arg3, arg4, arg5, 0]
        else:
            cled.is_on = bool(arg2)
        cled.notify()
    elif evnt == HaEvents.FINGER:
        module.sensors[0].value = arg1 if arg2 <= 10 else arg1 * -1
        module.sensors[0].notify()
        module.fingers[0].user = arg1  # raw user id
        module.fingers[0].value = arg2  # raw finger number
        module.fingers[0].notify()
    elif evnt == HaEvents.DIM_VAL:
        module.dimmers[arg1].brightness = arg2
        module.dimmers[arg1].notify()
    elif evnt == HaEvents.COV_VAL:
        module.covers[arg1].position = arg2
        module.covers[arg1].notify()
    elif evnt == HaEvents.BLD_VAL:
        module.covers[arg1].tilt = arg2
        module.covers[arg1].notify()
    elif evnt == HaEvents.MOVE:
        module.sensors[arg1].value = int(arg2 > 0)
        module.sensors[arg1].notify()
    elif evnt == HaEvents.FLAG:
        for flg in module.flags:
            if flg.nmbr == arg1:
                flg.value = arg2
                flg.notify()
                break
    elif evnt == HaEvents.CNT_VAL:
        module.logic[arg1].value = arg2
        module.logic[arg1].notify()
    else:
        _LOGGER.debug(
            "unhandled module event type %s (args %s) for module %s",
            _EVENT_NAMES.get(evnt, evnt),
            (arg1, arg2),
            module.addr,
        )
