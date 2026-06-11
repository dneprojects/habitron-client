"""Tests for the SmartHub payload validation helpers."""

from __future__ import annotations

import pytest

from habitron_client._models import _require_paths
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
