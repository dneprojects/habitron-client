"""Tests for the HabitronClient command layer (wire frames + parsing)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import pytest

from habitron_client import HabitronClient, const
from habitron_client._protocol import build_frame, wrap_command
from habitron_client.const import Command
from habitron_client.exceptions import (
    HabitronConnectionError,
    HabitronProtocolError,
)
from sim import Reply, build_response, running, unwrap

Call = Callable[[HabitronClient], Awaitable[object]]

# (id, call, expected command, expected build_frame args)
CASES: list[tuple[str, Call, Command, tuple[int | bytes, ...]]] = [
    (
        "set_output_on",
        lambda c: c.set_output(12, 3, True),
        const.SET_OUTPUT_ON,
        (12, 3),
    ),
    (
        "set_output_off",
        lambda c: c.set_output(12, 3, False),
        const.SET_OUTPUT_OFF,
        (12, 3),
    ),
    (
        "set_dimmval",
        lambda c: c.set_dimmval(1, 2, 200),
        const.SET_DIMMER_VALUE,
        (1, 2, 200),
    ),
    ("set_rgb_on", lambda c: c.set_rgb_output(1, 2, True), const.SET_RGB_ON, (1, 2)),
    ("set_rgb_off", lambda c: c.set_rgb_output(1, 2, False), const.SET_RGB_OFF, (1, 2)),
    (
        "set_rgbval",
        lambda c: c.set_rgbval(1, 2, [10, 20, 30]),
        const.SET_RGB_COL,
        (1, 2, 10, 20, 30),
    ),
    (
        "set_shutterpos",
        lambda c: c.set_shutterpos(1, 2, 50),
        const.SET_SHUTTER_POSITION,
        (1, 2, 50),
    ),
    (
        "set_blindtilt",
        lambda c: c.set_blindtilt(1, 2, 50),
        const.SET_BLIND_TILT,
        (1, 2, 50),
    ),
    ("set_flag_on", lambda c: c.set_flag(1, 2, True), const.SET_FLAG_ON, (1, 2)),
    ("set_flag_off", lambda c: c.set_flag(1, 2, False), const.SET_FLAG_OFF, (1, 2)),
    ("counter_up", lambda c: c.inc_dec_counter(1, 2, 1), const.COUNTR_UP, (1, 2)),
    ("counter_down", lambda c: c.inc_dec_counter(1, 2, 0), const.COUNTR_DOWN, (1, 2)),
    (
        "set_setpoint",
        lambda c: c.set_setpoint(5, 2, 300),
        const.SET_SETPOINT_VALUE,
        (5, 2, 44, 1),
    ),
    (
        "set_climate_mode",
        lambda c: c.set_climate_mode(1, 2, 3),
        const.SET_CLIM_MODE,
        (1, 2, 3),
    ),
    ("call_dir", lambda c: c.call_dir_command(1, 2), const.CALL_DIR_COMMAND, (1, 2)),
    (
        "call_vis",
        lambda c: c.call_vis_command(7, 300),
        const.CALL_VIS_COMMAND,
        (7, 44, 1),
    ),
    ("call_coll", lambda c: c.call_coll_command(5), const.CALL_COLL_COMMAND, (5,)),
    ("set_group_mode", lambda c: c.set_group_mode(2, 3), const.SET_GROUP_MODE, (2, 3)),
    ("set_log_level", lambda c: c.set_log_level(1, 2), const.SET_LOG_LEVEL, (1, 2)),
    ("send_message", lambda c: c.send_message(1, 7), const.SEND_MESSAGE, (1, 15, 7)),
    ("send_sms", lambda c: c.send_sms(1, 7, 3), const.SEND_SMS, (1, 3, 7)),
    (
        "msg_text_set",
        lambda c: c.send_message_text(6, "Hallo"),
        const.SET_MESSAGE_TEXT,
        (6, 5, b"Hallo"),
    ),
    (
        "msg_text_reset",
        lambda c: c.send_message_text(6, ""),
        const.RESET_MESSAGE_TEXT,
        (6,),
    ),
    ("hub_restart", lambda c: c.hub_restart(), const.RESTART_HUB, ()),
    ("hub_reboot", lambda c: c.hub_reboot(), const.REBOOT_HUB, ()),
    ("module_restart", lambda c: c.module_restart(5), const.REBOOT_MODULE, (5,)),
    ("router_restart", lambda c: c.module_restart(0), const.REBOOT_ROUTER, ()),
    ("restart_fwd_tbl", lambda c: c.restart_fwd_tbl(), const.RESTART_FORWARD_TABLE, ()),
    ("start_mirror", lambda c: c.start_mirror(), const.START_MIRROR, ()),
    ("stop_mirror", lambda c: c.stop_mirror(), const.STOP_MIRROR, ()),
    ("get_version", lambda c: c.get_smhub_version(), const.GET_SMHUB_FIRMWARE, ()),
    ("router_status", lambda c: c.get_router_status(), const.GET_ROUTER_STATUS, ()),
    ("router_modules", lambda c: c.get_router_modules(), const.GET_MODULES, ()),
    (
        "global_desc",
        lambda c: c.get_global_descriptions(),
        const.GET_GLOBAL_DESCRIPTIONS,
        (),
    ),
    ("error_status", lambda c: c.get_error_status(), const.GET_CURRENT_ERROR, ()),
    ("module_def", lambda c: c.get_module_definitions(5), const.GET_MODULE_SMC, (5,)),
    ("module_settings", lambda c: c.get_module_settings(5), const.GET_MODULE_SMG, (5,)),
    ("compact_status", lambda c: c.get_compact_status(), const.GET_COMPACT_STATUS, ()),
    ("module_status", lambda c: c.get_module_status(5), const.GET_MODULE_STATUS, (5,)),
    ("fw_module", lambda c: c.handle_firmware(5), const.GET_MODULE_FW_FILEVS, (5,)),
    ("fw_router", lambda c: c.handle_firmware(0), const.GET_ROUTER_FW_FILEVS, ()),
    ("fw_update", lambda c: c.update_firmware(5), const.DO_FW_UPDATE, (5,)),
    ("power_down", lambda c: c.power_cycle_channel_down(3), const.POWER_DWN_CHAN, (4,)),
    ("power_up", lambda c: c.power_cycle_channel_up(3), const.POWER_UP_CHAN, (4,)),
    ("devregid", lambda c: c.send_devregid(5, "ab"), const.SEND_MD_ID, (5, 2, b"ab")),
    ("reinit_hub", lambda c: c.reinit_hub(0), const.REINIT_HUB, (0,)),
    ("check_comm", lambda c: c.check_comm_status(), const.CHECK_COMM_STATUS, ()),
    ("get_smr", lambda c: c.get_smr(), const.GET_ROUTER_SMR, ()),
]


async def _wait_for(
    sim_requests: list[bytes], count: int, timeout: float = 2.0
) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while len(sim_requests) < count and loop.time() < deadline:
        await asyncio.sleep(0.01)


def test_all_command_frames() -> None:
    async def scenario() -> list[tuple[str, bytes, bytes]]:
        results: list[tuple[str, bytes, bytes]] = []
        # close=False keeps the persistent connection alive across the loop.
        async with running(Reply(data=build_response(b"OK"), close=False)) as sim:
            async with HabitronClient("127.0.0.1", sim.port) as client:
                for index, (cid, call, cmd, args) in enumerate(CASES):
                    await call(client)
                    await _wait_for(sim.requests, index + 1)
                    expected = wrap_command(build_frame(cmd, args))
                    results.append((cid, sim.requests[index], expected))
        return results

    for cid, actual, expected in asyncio.run(scenario()):
        assert actual == expected, cid


def test_get_smhub_info_parses_yaml() -> None:
    info_yaml = (
        "software:\n  version: '3.4.5'\n"
        "hardware:\n  platform:\n    type: smarthub\n"
        "  network:\n    ip: 10.0.0.2\n    host: hub.lan\n    lan mac: aa:bb:cc\n"
    )

    async def scenario() -> object:
        response = build_response(info_yaml.encode("iso8859-1"))
        async with running(Reply(data=response)) as sim:
            async with HabitronClient("127.0.0.1", sim.port) as client:
                return await client.get_smhub_info()

    info = asyncio.run(scenario())
    assert info["software"]["version"] == "3.4.5"
    assert info["hardware"]["network"]["lan mac"] == "aa:bb:cc"


def test_get_smhub_update_parses_yaml() -> None:
    update_yaml = (
        "hardware:\n"
        "  cpu:\n    frequency current: 600MHz\n    load: 5%\n    temperature: 40C\n"
        "  memory:\n    percent: 30%\n"
        "  disk:\n    percent: 12%\n"
        "software:\n  loglevel:\n    console: 20\n    file: 10\n"
    )

    async def scenario() -> object:
        response = build_response(update_yaml.encode("iso8859-1"))
        async with running(Reply(data=response)) as sim:
            async with HabitronClient("127.0.0.1", sim.port) as client:
                return await client.get_smhub_update("1.2.3")

    update = asyncio.run(scenario())
    assert update["hardware"]["cpu"]["load"] == "5%"
    assert update["software"]["loglevel"]["console"] == 20


def test_get_smhub_info_invalid_payload_raises() -> None:
    async def scenario() -> object:
        async with running(Reply(data=build_response(b"justastring"))) as sim:
            async with HabitronClient("127.0.0.1", sim.port) as client:
                return await client.get_smhub_info()

    with pytest.raises(HabitronProtocolError):
        asyncio.run(scenario())


def test_send_network_info_addon_frame() -> None:
    async def scenario() -> bytes:
        async with running(Reply(data=build_response(b"OK"))) as sim:
            async with HabitronClient("127.0.0.1", sim.port) as client:
                await client.send_network_info(
                    "1.2.3.4",
                    b"abcd",
                    bytes.fromhex("000000000000"),
                    is_addon=True,
                    version="9.9",
                )
            await _wait_for(sim.requests, 1)
            return sim.requests[-1]

    expected = build_frame(
        const.SEND_NETWORK_INFO,
        (bytes((17, 0)), 7, b"1.2.3.4", 4, b"abcd", 3, b"9.9"),
    )
    assert unwrap(asyncio.run(scenario())) == expected


def test_send_network_info_empty_token_sends_nothing() -> None:
    async def scenario() -> int:
        async with running(Reply(data=build_response(b"OK"))) as sim:
            async with HabitronClient("127.0.0.1", sim.port) as client:
                await client.send_network_info(
                    "1.2.3.4", b"", b"\x00" * 6, is_addon=False, version="9.9"
                )
            return len(sim.requests)

    assert asyncio.run(scenario()) == 0


def test_host_and_port_properties() -> None:
    client = HabitronClient("example.local", 1234)
    assert client.host == "example.local"
    assert client.port == 1234


def test_direct_call_without_context_manager_raises() -> None:
    async def scenario() -> None:
        client = HabitronClient("127.0.0.1", 1)
        with pytest.raises(HabitronConnectionError, match="async with"):
            await client.get_smhub_info()

    asyncio.run(scenario())


def test_send_message_text_too_long_raises() -> None:
    async def scenario() -> None:
        client = HabitronClient("127.0.0.1", 1)
        with pytest.raises(ValueError, match="255"):
            await client.send_message_text(6, "x" * 256)

    asyncio.run(scenario())


def test_direct_send_only_without_context_manager_raises() -> None:
    async def scenario() -> None:
        client = HabitronClient("127.0.0.1", 1)
        with pytest.raises(HabitronConnectionError, match="async with"):
            await client.set_output(1, 2, True)

    asyncio.run(scenario())
