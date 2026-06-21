"""Regression tests for the mirror-restart logic in ``async_refresh_system``.

The hub legitimately reports its mirror as "not started" for a few seconds
right after setup (it is still coming up). Restarting it there breaks the hub's
own start-up sequence, so the mirror must only be restarted on a genuine
up->down edge (a hub reboot between two polls). These tests lock that edge
behaviour against the earlier "restart whenever not started" bug, which made
the config-entry first refresh fail on a freshly-set-up hub.
"""

import asyncio

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
    def __init__(self, *, mirror_started: bool, fail_restart: bool = False) -> None:
        self._mirror_started = mirror_started
        self._fail_restart = fail_restart
        self.start_mirror_calls = 0

    async def get_compact_status(self) -> tuple[bytes, int]:
        return b"\x00" * 64, 0x1234

    async def get_router_status(self) -> bytes:
        return _router_status(mirror_started=self._mirror_started)

    async def start_mirror(self) -> bytes:
        self.start_mirror_calls += 1
        if self._fail_restart:
            raise HabitronConnectionError("hub still rebooting")
        return b""


def _refresh(client: _FakeClient, router) -> None:
    asyncio.run(async_refresh_system(client, router, last_crc=None))  # type: ignore[arg-type]


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
