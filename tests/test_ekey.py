"""Tests for resolving the raw readings of an ekey fingerprint reader."""

from __future__ import annotations

import pytest

from habitron_client import HbtnCommand, decode_finger, decode_user
from habitron_client.ekey import (
    DISABLED_SUFFIX,
    FINGER_KEYS,
    USER_ERROR,
    USER_UNKNOWN,
)


def _enrolled() -> list[HbtnCommand]:
    return [HbtnCommand(name="Anna", nmbr=1), HbtnCommand(name="Bert", nmbr=2)]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        pytest.param(1, "left_pinky", id="first"),
        pytest.param(10, "right_pinky", id="last"),
        pytest.param(0, None, id="nothing presented"),
        pytest.param(255, None, id="reader error"),
        pytest.param(11, None, id="out of range"),
        pytest.param(-1, None, id="negative"),
    ],
)
def test_decode_finger(raw: int, expected: str | None) -> None:
    """Only the ten fingers resolve; everything else is nothing to show."""
    assert decode_finger(raw) == expected


def test_finger_keys_are_ordered_by_the_raw_value() -> None:
    """The reader counts from one, so key n-1 belongs to raw n."""
    assert len(FINGER_KEYS) == 10
    assert all(decode_finger(raw + 1) == key for raw, key in enumerate(FINGER_KEYS))


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        pytest.param(0, None, id="nothing presented"),
        pytest.param(1, "Anna", id="first enrolled"),
        pytest.param(2, "Bert", id="second enrolled"),
        pytest.param(255, USER_ERROR, id="reader error"),
        pytest.param(3, USER_UNKNOWN, id="not enrolled"),
        pytest.param(-1, "Anna" + DISABLED_SUFFIX, id="enrolled but disabled"),
        pytest.param(-9, USER_UNKNOWN, id="disabled and not enrolled"),
    ],
)
def test_decode_user(raw: int, expected: str | None) -> None:
    """The enrolled list is counted from one, and a negative entry is disabled."""
    assert decode_user(raw, _enrolled()) == expected


def test_decode_user_without_anyone_enrolled() -> None:
    """A module with an empty list can only report the sentinels."""
    assert decode_user(0, []) is None
    assert decode_user(255, []) == USER_ERROR
    assert decode_user(1, []) == USER_UNKNOWN
