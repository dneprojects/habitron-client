"""Replay a real SmartHub recording through the v2 build/refresh pipeline.

This is the end-to-end fidelity check against a *real* installation. It is
skipped unless a recording produced by ``scripts/capture_hub.py`` is present at
``scripts/captures/build_recording.json`` (git-ignored, site-specific). When
present it feeds the exact bytes the hub returned through
:func:`async_build_system` and :func:`async_refresh_system` and asserts the
parser builds a well-formed model without raising — proving the library handles
real-world data the way the pre-library integration did.
"""

from __future__ import annotations

import base64
import json
import pathlib
from collections import deque
from typing import Any

import pytest

from habitron_client._setup import async_build_system, async_refresh_system
from habitron_client.model import Router

_RECORDING = (
    pathlib.Path(__file__).resolve().parent.parent
    / "scripts"
    / "captures"
    / "build_recording.json"
)

pytestmark = pytest.mark.skipif(
    not _RECORDING.exists(),
    reason="no real-hub recording present (run scripts/capture_hub.py)",
)


class ReplayClient:
    """Returns recorded responses in the exact order they were recorded."""

    def __init__(self, calls: list[dict[str, Any]]) -> None:
        self._queue: deque[dict[str, Any]] = deque(calls)

    def __getattr__(self, name: str) -> Any:
        async def _replay(*args: Any) -> Any:
            entry = self._queue.popleft()
            assert entry["method"] == name, (
                f"call order mismatch: expected {entry['method']}, got {name}"
            )
            payload = base64.b64decode(entry["bytes_b64"])
            if entry["kind"] == "bytes_crc":
                return payload, entry["crc"]
            return payload

        return _replay

    @property
    def exhausted(self) -> bool:
        return not self._queue


def _load() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(_RECORDING.read_text(encoding="utf-8"))
    return data


async def test_replay_builds_well_formed_model() -> None:
    """The recorded bytes build the expected module model end to end."""
    data = _load()
    client = ReplayClient(list(data["calls"]))
    router = await async_build_system(client, b_uid=data["b_uid"])  # type: ignore[arg-type]

    assert isinstance(router, Router)
    assert len(router.modules) == data["module_count"]
    assert router.name  # SMR yielded a router name
    for module in router.modules:
        assert module.mod_type, f"module {module.addr} has no type"
        assert module.uid  # hw_version or inventory uid
        # Every labelled member ends up with a non-empty name.
        for group in (module.outputs, module.inputs, module.covers):
            for member in group:
                assert member.name != "" or member.type < 0


async def test_replay_refreshes_consume_all_recorded_calls() -> None:
    """Build + the recorded refresh cycles consume the whole call log."""
    data = _load()
    client = ReplayClient(list(data["calls"]))
    router = await async_build_system(client, b_uid=data["b_uid"])  # type: ignore[arg-type]

    last_crc: int | None = None
    # Drain whatever refresh cycles the recording captured.
    while not client.exhausted:
        last_crc = await async_refresh_system(client, router, last_crc=last_crc)  # type: ignore[arg-type]
    assert client.exhausted
