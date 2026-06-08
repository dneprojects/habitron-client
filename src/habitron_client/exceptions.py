"""Exception hierarchy for the Habitron client.

Two tiers under a single root so consumers can distinguish transport problems
from protocol problems::

    HabitronError                 (root - catch-all)
    ├── HabitronConnectionError   (connect refused, EOF mid-frame, socket lost)
    ├── HabitronTimeoutError      (no response within the deadline)
    └── HabitronProtocolError     (a frame arrived but is unusable)
        └── HabitronBusError      (SmartHub reported an error code)
"""

from __future__ import annotations


class HabitronError(Exception):
    """Base class for every error raised by this library."""


class HabitronConnectionError(HabitronError):
    """The connection could not be established or was lost mid-exchange."""


class HabitronTimeoutError(HabitronError):
    """The SmartHub did not answer within the configured timeout."""


class HabitronProtocolError(HabitronError):
    """A response was received but does not conform to the protocol."""


class HabitronBusError(HabitronProtocolError):
    """The SmartHub answered with an error code instead of a result."""
