"""Decode a Habitron module's operate-mode fault bitmask.

The SmartHub gateway reports per-module operate-mode faults as a one-byte
bitmask in the ``SYS_ERR`` event's ``arg1``. The bit layout below is the fixed
contract shared with the SmartHub firmware — **do not change a bit position
without updating the SmartHub side in lockstep**. Bit ``0x08`` is reserved and
ignored. The display code (``F<n>``) and the German label are what consumers
show to the user.
"""

from __future__ import annotations

from typing import Final, NamedTuple


class ModuleFault(NamedTuple):
    """A single decoded module fault: its display code and label."""

    code: str  # display code, e.g. "F1"
    label: str  # human-readable description


# bit -> (display code, label). Fixed contract shared with the SmartHub.
# Bit 0x08 is reserved/unused and intentionally absent.
MODULE_FAULTS: Final[dict[int, ModuleFault]] = {
    0x01: ModuleFault("F1", "Timeout Modulkommunikation"),
    0x02: ModuleFault("F2", "Fehler Modulkommunikation"),
    0x04: ModuleFault("F4", "Abspeicherfehler"),
    0x10: ModuleFault("F16", "Fehler Leistungsteil"),
    0x20: ModuleFault("F32", "Fehler Ekey/GSM-Kommunikation"),
    0x40: ModuleFault("F3", "Weiterleitungstabelle nicht geheilt"),
    0x80: ModuleFault("F5", "Spiegelung gestört"),
}


def decode_module_faults(mask: int) -> list[ModuleFault]:
    """Return the active faults in ``mask`` ordered by ascending bit value.

    ``mask`` is the one-byte ``SYS_ERR`` ``arg1`` bitmask. A ``0`` mask (the
    module is healthy / a fault just cleared) yields an empty list. The reserved
    bit ``0x08`` and any bit outside :data:`MODULE_FAULTS` are ignored.
    """
    return [fault for bit, fault in MODULE_FAULTS.items() if mask & bit]
