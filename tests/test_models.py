"""Tests for the SmartHub payload validation helpers."""

from __future__ import annotations

from dataclasses import fields

import pytest

from habitron_client import Module, Output
from habitron_client._models import _require_paths
from habitron_client._parse_router import build_module
from habitron_client.exceptions import HabitronProtocolError


def test_require_paths_accepts_complete_mapping() -> None:
    # Every key path present with mapping intermediates -> no error.
    _require_paths({"a": {"b": 1}}, [("a", "b")], "label")


def test_require_paths_non_mapping_root_raises() -> None:
    with pytest.raises(HabitronProtocolError, match="expected a mapping"):
        _require_paths("not-a-mapping", [("a",)], "label")


def test_require_paths_non_mapping_intermediate_raises() -> None:
    # "a" exists but is a scalar, so descending into "b" hits a non-mapping node.
    with pytest.raises(HabitronProtocolError, match="expected mapping at 'a'"):
        _require_paths({"a": 1}, [("a", "b")], "label")


def test_require_paths_missing_leaf_key_raises() -> None:
    # "a" is a mapping but the leaf "b" is absent.
    with pytest.raises(HabitronProtocolError, match=r"missing key 'a\.b'"):
        _require_paths({"a": {}}, [("a", "b")], "label")


def test_led_output_continues_the_output_numbering() -> None:
    """LEDs have no command of their own; they continue the output numbering.

    Where that boundary sits depends on the module, so the module answers it
    rather than every caller counting outputs itself.
    """
    module = build_module(uid="M", addr=5, typ=b"\x01\x03", name="SC", group=0)
    module.outputs = [Output(name=f"Out{i}", nmbr=i, type=1) for i in range(16)]

    assert module.led_output(0) == 16
    assert module.led_output(3) == 19


def test_analog_out_channel_is_a_class_constant() -> None:
    """An analogue output is addressed as a dimmer; the bus has no own command.

    A ``ClassVar``, so the dataclass does not turn it into a per-module field.
    """
    assert Module.ANALOG_OUT_CHANNEL == 3
    assert "ANALOG_OUT_CHANNEL" not in {f.name for f in fields(Module)}
