"""Regression tests for the mirror-restart logic in ``async_refresh_system``.

The hub legitimately reports its mirror as "not started" for a few seconds
right after setup (it is still coming up). Restarting it there breaks the hub's
own start-up sequence, so the mirror must only be restarted on a genuine
up->down edge (a hub reboot between two polls). These tests lock that edge
behaviour against the earlier "restart whenever not started" bug, which made
the config-entry first refresh fail on a freshly-set-up hub.
"""

import asyncio

import pytest

from habitron_client import _setup
from habitron_client._indices import FALSE_VAL, TRUE_VAL, RoutIdx
from habitron_client._parse_router import build_router
from habitron_client._setup import async_refresh_system
from habitron_client.exceptions import HabitronConnectionError


def _router_status(*, mirror_started: bool) -> bytes:
    buf = bytearray(64)
    buf[RoutIdx.ERR_SYSTEM] = FALSE_VAL  # sys_ok
    buf[RoutIdx.REBOOTED] = 0
    buf[RoutIdx.MIRROR_STARTED] = TRUE_VAL if mirror_started else FALSE_VAL
    return bytes(buf)


class _FakeClient:
    def __init__(
        self,
        *,
        mirror_started: bool,
        fail_restart: bool = False,
        crc: int = 0x1234,
    ) -> None:
        self._mirror_started = mirror_started
        self._fail_restart = fail_restart
        self._crc = crc
        self.start_mirror_calls = 0
        self.router_status_calls = 0

    async def get_compact_status(self) -> tuple[bytes, int]:
        return b"\x00" * 64, self._crc

    async def get_router_status(self) -> bytes:
        self.router_status_calls += 1
        return _router_status(mirror_started=self._mirror_started)

    async def start_mirror(self) -> bytes:
        self.start_mirror_calls += 1
        if self._fail_restart:
            raise HabitronConnectionError("hub still rebooting")
        return b""


def _refresh(client: _FakeClient, router, *, last_crc: int | None = None) -> None:
    asyncio.run(async_refresh_system(client, router, last_crc=last_crc))  # type: ignore[arg-type]


def test_no_restart_when_mirror_not_yet_up_at_startup() -> None:
    """Mirror still coming up after setup (False, no prior up) -> no restart."""
    router = build_router(b_uid="UID")
    router.mirror_started = False  # state right after build on this hub
    client = _FakeClient(mirror_started=False)
    _refresh(client, router)
    assert client.start_mirror_calls == 0


def test_restart_on_up_to_down_edge_reboot() -> None:
    """Mirror was up, now reported down (hub reboot) -> restart once."""
    router = build_router(b_uid="UID")
    router.mirror_started = True  # mirror was running
    client = _FakeClient(mirror_started=False)
    _refresh(client, router)
    assert client.start_mirror_calls == 1


def test_no_restart_while_mirror_stays_up() -> None:
    """Mirror up and stays up -> never restarted."""
    router = build_router(b_uid="UID")
    router.mirror_started = True
    client = _FakeClient(mirror_started=True)
    _refresh(client, router)
    assert client.start_mirror_calls == 0


def test_restart_failure_is_non_fatal() -> None:
    """A failing mirror restart must not propagate out of the refresh."""
    router = build_router(b_uid="UID")
    router.mirror_started = True
    client = _FakeClient(mirror_started=False, fail_restart=True)
    _refresh(client, router)  # must not raise
    assert client.start_mirror_calls == 1


def test_router_status_read_even_when_module_crc_unchanged() -> None:
    """Router telemetry refreshes every poll, not only on a module change.

    Router currents/voltages/timeouts/``sys_ok`` change independently of the
    modules; gating their read on the compact-status CRC left them stale on an
    otherwise idle bus.
    """
    router = build_router(b_uid="UID")
    router.mirror_started = True
    # Same CRC in and out -> the module compact status is byte-stable.
    client = _FakeClient(mirror_started=True, crc=0x1234)
    _refresh(client, router, last_crc=0x1234)
    assert client.router_status_calls == 1


def test_mirror_reboot_edge_caught_on_idle_bus() -> None:
    """A hub reboot is detected even when no module status changed.

    The reboot down-edge is exactly what can happen on a quiet bus, so it must
    not depend on the module CRC moving.
    """
    router = build_router(b_uid="UID")
    router.mirror_started = True
    client = _FakeClient(mirror_started=False, crc=0x1234)
    _refresh(client, router, last_crc=0x1234)  # unchanged module CRC
    assert client.start_mirror_calls == 1


def test_module_distribution_skipped_when_crc_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The (expensive) module re-parse is still skipped on a byte-stable bus."""
    calls = 0

    def _spy(router: object, sys_status: object) -> None:
        nonlocal calls
        calls += 1

    monkeypatch.setattr(_setup, "distribute_status", _spy)

    router = build_router(b_uid="UID")
    router.mirror_started = True
    client = _FakeClient(mirror_started=True, crc=0x1234)

    _refresh(client, router, last_crc=0x1234)  # unchanged -> no distribution
    assert calls == 0

    _refresh(client, router, last_crc=0x0001)  # changed -> distributed once
    assert calls == 1
