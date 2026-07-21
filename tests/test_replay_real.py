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

import asyncio
import base64
import json
import pathlib
from collections import deque
from typing import Any

import pytest

from habitron_client._setup import async_build_system, async_refresh_system
from habitron_client.model import Router

_ROOT = pathlib.Path(__file__).resolve().parent.parent
# Prefer a local, full-fidelity recording; fall back to the committed,
# anonymised fixture so the replay still runs in CI.
_LOCAL = _ROOT / "scripts" / "captures" / "build_recording.json"
_ANON = _ROOT / "tests" / "fixtures" / "anon_recording.json"
_RECORDING = _LOCAL if _LOCAL.exists() else _ANON

pytestmark = pytest.mark.skipif(
    not _RECORDING.exists(),
    reason="no recording present (run scripts/capture_hub.py + scrub_recording.py)",
)


class ReplayClient:
    """Returns recorded responses in the exact order they were recorded."""

    def __init__(self, calls: list[dict[str, Any]]) -> None:
        self._queue: deque[dict[str, Any]] = deque(calls)
        self._last_router_status: Any = None

    def __getattr__(self, name: str) -> Any:
        async def _replay(*args: Any) -> Any:
            # ``async_refresh_system`` now reads the router status on every poll,
            # but this recording was captured under the older logic that read it
            # only when the compact-status CRC changed. For those byte-stable
            # cycles the hub would return the same router status again, so serve
            # the last recorded one instead of consuming an unrelated queued
            # call. Every recorded call is still replayed, in order.
            if (
                name == "get_router_status"
                and self._last_router_status is not None
                and (not self._queue or self._queue[0]["method"] != "get_router_status")
            ):
                return self._last_router_status
            entry = self._queue.popleft()
            assert entry["method"] == name, (
                f"call order mismatch: expected {entry['method']}, got {name}"
            )
            payload = base64.b64decode(entry["bytes_b64"])
            if entry["kind"] == "bytes_crc":
                return payload, entry["crc"]
            if name == "get_router_status":
                self._last_router_status = payload
            return payload

        return _replay

    @property
    def exhausted(self) -> bool:
        return not self._queue


def _load() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(_RECORDING.read_text(encoding="utf-8"))
    return data


async def _build(data: dict[str, Any]) -> Router:
    client = ReplayClient(list(data["calls"]))
    return await async_build_system(client, b_uid=data["b_uid"])  # type: ignore[arg-type]


def test_replay_builds_well_formed_model() -> None:
    """The recorded bytes build the expected module model end to end."""
    data = _load()
    router = asyncio.run(_build(data))

    assert isinstance(router, Router)
    assert len(router.modules) == data["module_count"]
    assert router.name  # SMR yielded a router name
    for module in router.modules:
        assert module.mod_type, f"module {module.addr} has no type"
        assert module.uid  # hw_version or inventory uid
        # Every addressable member (nmbr >= 0; placeholders are nmbr == -1)
        # ends up either named or disabled (type negated).
        for group in (module.outputs, module.inputs, module.covers):
            for member in group:
                if member.nmbr < 0:
                    continue
                assert member.name != "" or member.type < 0


# The exact device line-up the autodetect (type-code map + settings parse)
# produces from the committed recording. Addresses and types are not scrubbed by
# the anonymiser, so these lock the *startup* path against real bus data.
_EXPECTED_TYPES = {
    101: "Smart Detect 360",
    102: "Smart Controller XL-2",
    103: "Smart Dimm-2",
    104: "Smart In 8/24V-1",
    105: "Smart GSM",
    106: "Smart In 8/230V",
    107: "Smart Out 8/R-1",
    108: "Fanekey",
    109: "Smart Controller Mini",
    110: "Smart Controller Touch",
    113: "Smart Nature",
}


def test_replay_autodetects_expected_devices() -> None:
    """Startup autodetect maps the recorded type codes to the real line-up."""
    data = _load()
    # The committed anonymised fixture is what CI replays; skip the type/feature
    # assertions when a different (local, site-specific) recording is in use.
    if _RECORDING != _ANON:
        pytest.skip("type/feature assertions are pinned to the anon fixture")

    router = asyncio.run(_build(data))
    by_addr = {m.addr: m for m in router.modules}

    assert {a: m.mod_type for a, m in by_addr.items()} == _EXPECTED_TYPES

    def _covers(addr: int) -> int:  # autodetected (addressable) covers
        return sum(c.nmbr >= 0 for c in by_addr[addr].covers)

    # Feature autodetect from the settings blocks: covers, analog inputs, fingers.
    assert _covers(102) == 3  # XL-2
    assert _covers(107) == 2  # Out 8/R-1
    assert _covers(110) == 4  # Touch
    assert len(by_addr[104].analogins) == 6  # In 8/24V-1
    assert len(by_addr[110].analogins) == 2  # Touch
    assert len(by_addr[108].fingers) == 1  # Fanekey

    # The analog-output backing slot stays hidden (#7): controllers expose their
    # analog out as a number, never as a switchable output (type -10, not -1).
    for addr in (102, 110):
        assert by_addr[addr].outputs[15].type == -10


def test_replay_refreshes_consume_all_recorded_calls() -> None:
    """Build + the recorded refresh cycles consume the whole call log."""
    data = _load()

    async def _scenario() -> bool:
        client = ReplayClient(list(data["calls"]))
        router = await async_build_system(client, b_uid=data["b_uid"])  # type: ignore[arg-type]
        last_crc: int | None = None
        # Drain whatever refresh cycles the recording captured.
        while not client.exhausted:
            last_crc = await async_refresh_system(
                client,  # type: ignore[arg-type]
                router,
                last_crc=last_crc,
            )
        return client.exhausted

    assert asyncio.run(_scenario())
