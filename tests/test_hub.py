"""Tests for the SmartHub model: payload -> hub, and host-reading updates.

The hub is the one device the library did not model: its data left in three
unrelated shapes (a raw ``SmhubInfo`` mapping, a ``HostDiagnostics`` dataclass
and a free MAC helper) and every consumer reassembled them itself. These tests
lock the assembled shape and the notification contract its readings carry.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import pytest

from habitron_client import (
    SmartHub,
    async_build_hub,
    async_refresh_hub,
    normalise_mac,
)
from habitron_client._models import apply_host_diagnostics, parse_smhub_info
from habitron_client.model import HostDiagnostics


def _info(
    *,
    platform: str = "Raspberry Pi 5",
    software: dict[str, Any] | None = None,
    network: dict[str, Any] | None = None,
) -> Any:
    """Build a validated-shape ``GET_SMHUB_INFO`` payload."""
    return {
        "hardware": {
            "platform": {"type": platform},
            "network": {
                "ip": "10.0.0.2",
                "host": "smarthub-1",
                "lan mac": "AA:BB:CC:DD:EE:FF",
                **(network or {}),
            },
        },
        "software": {"version": "1.2.3", **(software or {})},
    }


def _host(**overrides: float) -> HostDiagnostics:
    values: dict[str, Any] = {
        "cpu_frequency": 1500.0,
        "cpu_load": 12.0,
        "cpu_temperature": 55.5,
        "memory_usage": 40.0,
        "disk_usage": 60.0,
        "log_level_console": 20,
        "log_level_file": 30,
    }
    values.update(overrides)
    return HostDiagnostics(**values)


# --- parse_smhub_info -----------------------------------------------------


def test_parse_collects_the_hubs_own_data() -> None:
    hub = parse_smhub_info(_info(network={"wlan mac": "11:22:33:44:55:66"}))
    assert hub.lan_mac == "AA:BB:CC:DD:EE:FF"
    assert hub.macs == ["AA:BB:CC:DD:EE:FF", "11:22:33:44:55:66"]
    assert hub.hostname == "smarthub-1"
    assert hub.platform == "Raspberry Pi 5"
    assert hub.version == "1.2.3"


def test_parse_creates_the_host_readings_of_a_pi() -> None:
    hub = parse_smhub_info(_info())
    assert [member.name for member in hub.diags] == [
        "CPU Frequency",
        "CPU load",
        "CPU Temperature",
    ]
    assert [member.name for member in hub.sensors] == ["Memory usage", "Disk usage"]
    assert [member.name for member in hub.loglevels] == [
        "Logging level console",
        "Logging level file",
    ]
    # Numbered per list, so a consumer can index into them.
    assert [member.nmbr for member in hub.diags] == [0, 1, 2]
    # The CPU readings are diagnostics, memory/disk and the log levels are not.
    assert all(member.is_diagnostic for member in hub.diags)
    assert not any(member.is_diagnostic for member in hub.sensors)


@pytest.mark.parametrize("platform", ["Raspberry Pi 4", "Raspberry Pi 5"])
def test_parse_matches_any_pi_board_revision(platform: str) -> None:
    assert parse_smhub_info(_info(platform=platform)).host_members


def test_parse_leaves_a_non_pi_platform_without_readings() -> None:
    """Another platform reports none, so it must not get placeholder members."""
    hub = parse_smhub_info(_info(platform="Generic x86"))
    assert hub.host_members == []


def test_parse_starts_out_invalid() -> None:
    """Nothing has been polled yet, so the defaults are not measurements."""
    assert parse_smhub_info(_info()).host_valid is False


@pytest.mark.parametrize(
    ("software", "expected"),
    [
        ({"slug": "habitron_smarthub"}, "habitron_smarthub"),
        # Sentinel, omitted key and null all mean "not an add-on".
        ({"slug": "none"}, ""),
        ({}, ""),
        ({"slug": None}, ""),
        ({"slug": "  spaced  "}, "spaced"),
    ],
)
def test_parse_undoes_the_no_addon_sentinel(
    software: dict[str, Any], expected: str
) -> None:
    hub = parse_smhub_info(_info(software=software))
    assert hub.slug == expected
    assert hub.is_addon is bool(expected)


def test_parse_turns_a_null_lan_mac_into_the_empty_string() -> None:
    """A hub without a configured LAN interface answers null, not a string."""
    hub = parse_smhub_info(_info(network={"lan mac": None}))
    assert hub.lan_mac == ""


# --- identity -------------------------------------------------------------


@pytest.mark.parametrize(
    "reported",
    [
        "AA:BB:CC:DD:EE:FF",
        "aa-bb-cc-dd-ee-ff",
        "AABBCCDDEEFF",
        "  aa:bb:cc:dd:ee:ff  ",
    ],
)
def test_normalise_mac_undoes_the_reported_notation(reported: str) -> None:
    """Separator and case are wire variation, not a difference in identity."""
    assert normalise_mac(reported) == "aabbccddeeff"


@pytest.mark.parametrize(
    "reported",
    [
        # The placeholder a consumer holds before the hub has answered, and the
        # broadcast address: both match the shape, neither is a machine.
        "00:00:00:00:00:00",
        "ff:ff:ff:ff:ff:ff",
        # Not an address at all: a redaction, an IP, a truncated value.
        "redacted",
        "192.168.1.5",
        "aa:bb:cc",
        "",
    ],
)
def test_normalise_mac_refuses_what_is_not_an_address(reported: str) -> None:
    """Anything else would hand out an id two machines could share."""
    assert normalise_mac(reported) is None


def test_uid_is_the_lan_address() -> None:
    hub = parse_smhub_info(_info())
    assert hub.uid == "aabbccddeeff"


@pytest.mark.parametrize("lan_mac", [None, "00:00:00:00:00:00", "redacted"])
def test_uid_is_empty_without_a_usable_address(lan_mac: str | None) -> None:
    """A real state, not an error -- the consumer decides what to key on."""
    hub = parse_smhub_info(_info(network={"lan mac": lan_mac}))
    assert hub.uid == ""


def test_uid_accepts_a_consumer_fallback() -> None:
    """A field, not a derived property: a consumer without an address from the
    hub writes its own id in and keeps one identity across the whole model."""
    hub = parse_smhub_info(_info(network={"lan mac": None}))
    hub.uid = "01JABCDEF"
    assert hub.uid == "01JABCDEF"
    # The address it could not be derived from is untouched and still reported.
    assert hub.lan_mac == ""


def test_macs_drop_what_is_not_an_address() -> None:
    """The consumer registers these as device connections unchanged."""
    hub = parse_smhub_info(
        _info(network={"wlan mac": "11:22:33:44:55:66", "mac": "redacted"})
    )
    assert hub.macs == ["AA:BB:CC:DD:EE:FF", "11:22:33:44:55:66"]


# --- apply_host_diagnostics ----------------------------------------------


def _subscribe(hub: SmartHub) -> list[str]:
    """Record the name of every member that notifies."""
    fired: list[str] = []

    def recorder(name: str) -> Callable[[], None]:
        return lambda: fired.append(name)

    for member in hub.host_members:
        member.add_listener(recorder(member.name))
    return fired


def test_apply_writes_every_reading() -> None:
    hub = parse_smhub_info(_info())
    apply_host_diagnostics(hub, _host())
    assert [member.value for member in hub.diags] == [1500.0, 12.0, 55.5]
    assert [member.value for member in hub.sensors] == [40.0, 60.0]
    assert [member.value for member in hub.loglevels] == [20, 30]
    assert hub.host_valid is True


def test_first_poll_notifies_even_a_member_that_matches_its_default() -> None:
    """The regression this moved into the library.

    ``Diagnostic.value`` defaults to 0.0, so a hub genuinely reporting 0 would
    look "unchanged" on the very first poll and never fire -- leaving a consumer
    that renders an unread member as unknown stuck on it indefinitely.
    """
    hub = parse_smhub_info(_info())
    fired = _subscribe(hub)
    apply_host_diagnostics(hub, _host(cpu_load=0.0, log_level_console=0))
    assert set(fired) == {member.name for member in hub.host_members}


def test_later_polls_notify_only_what_moved() -> None:
    hub = parse_smhub_info(_info())
    apply_host_diagnostics(hub, _host())
    fired = _subscribe(hub)
    apply_host_diagnostics(hub, _host(cpu_load=99.0))
    assert fired == ["CPU load"]


def test_a_platform_without_readings_applies_nothing() -> None:
    hub = parse_smhub_info(_info(platform="Generic x86"))
    apply_host_diagnostics(hub, _host())
    assert hub.host_members == []


# --- async_build_hub / async_refresh_hub ---------------------------------


class _FakeClient:
    def __init__(self, *, platform: str = "Raspberry Pi 5") -> None:
        self._platform = platform
        self.info_calls = 0
        self.host_calls: list[str] = []

    async def get_smhub_info(self) -> Any:
        self.info_calls += 1
        return _info(platform=self._platform)

    async def get_host_diagnostics(self, hbtn_version: str) -> HostDiagnostics:
        self.host_calls.append(hbtn_version)
        return _host()


def test_build_hub_reads_the_info_once() -> None:
    client = _FakeClient()
    hub = asyncio.run(async_build_hub(client))  # type: ignore[arg-type]
    assert client.info_calls == 1
    assert hub.version == "1.2.3"
    assert len(hub.host_members) == 7


def test_refresh_hub_polls_and_applies() -> None:
    client = _FakeClient()
    hub = asyncio.run(async_build_hub(client))  # type: ignore[arg-type]
    asyncio.run(async_refresh_hub(client, hub, hbtn_version="3.2.5"))  # type: ignore[arg-type]
    assert client.host_calls == ["3.2.5"]
    assert hub.diags[0].value == 1500.0


def test_refresh_hub_skips_the_query_without_readings() -> None:
    """No members to fill, so the round trip is pure cost."""
    client = _FakeClient(platform="Generic x86")
    hub = asyncio.run(async_build_hub(client))  # type: ignore[arg-type]
    asyncio.run(async_refresh_hub(client, hub, hbtn_version="3.2.5"))  # type: ignore[arg-type]
    assert client.host_calls == []
