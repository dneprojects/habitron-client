"""Resolve the raw readings of an ekey fingerprint reader.

A scanner reports two raw numbers per press: which enrolled identity it
recognised, and which finger was presented. Neither is a value a consumer can
show. Both carry sentinels the bus defines -- ``0`` while nothing has been
presented, ``255`` when the reader reports a failure -- the identity is counted
from one against the module's enrolled list, and a *negative* identity means
that entry exists but has been disabled.

Those four rules are wire semantics, so they live here rather than in each
consumer. What comes back is a string to render: a name, one of the markers
below, or ``None`` for "nothing to show".
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from .model import HbtnCommand

#: Stable keys for the ten fingers, ordered by the raw value the reader sends
#: (1..10). They are identifiers, not display text: a consumer localises them.
FINGER_KEYS: Final[tuple[str, ...]] = (
    "left_pinky",
    "left_ring",
    "left_middle",
    "left_index",
    "left_thumb",
    "right_thumb",
    "right_index",
    "right_middle",
    "right_ring",
    "right_pinky",
)

#: Reported when the reader itself failed rather than identifying someone.
USER_ERROR: Final = "Error"
#: Reported for an identity the module does not have in its enrolled list.
USER_UNKNOWN: Final = "Unknown"
#: Appended to the name of an enrolled identity that has been disabled.
DISABLED_SUFFIX: Final = "-disabled"

_NOTHING_PRESENTED: Final = 0
_READER_ERROR: Final = 255


def decode_finger(raw: int) -> str | None:
    """Return the stable key of the finger ``raw`` names, or ``None``.

    ``None`` covers everything that is not one of the ten fingers: nothing
    presented, a reader error, and any value outside the range.
    """
    if raw in range(1, len(FINGER_KEYS) + 1):
        return FINGER_KEYS[raw - 1]
    return None


def decode_user(raw: int, ids: Sequence[HbtnCommand]) -> str | None:
    """Return what to show for the identity ``raw`` names, or ``None``.

    ``ids`` is the module's enrolled list, counted from one. A negative ``raw``
    names an entry that exists but is disabled, which is worth showing as such
    rather than as an unknown one.
    """
    if raw == _NOTHING_PRESENTED:
        return None
    if raw == _READER_ERROR:
        return USER_ERROR
    if (raw - 1) in range(len(ids)):
        return str(ids[raw - 1].name)
    if (abs(raw) - 1) in range(len(ids)):
        return str(ids[abs(raw) - 1].name) + DISABLED_SUFFIX
    return USER_UNKNOWN
