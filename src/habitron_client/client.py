"""Async Habitron SmartHub client.

``HabitronClient`` is a thin, fully typed command layer over
:class:`~habitron_client._transport.BusConnection`. Use it as an async context
manager::

    async with HabitronClient("192.0.2.10") as client:
        await client.set_output(1, 2, True)

Every method that talks to the bus is a coroutine. Errors surface as the typed
exceptions from :mod:`habitron_client.exceptions`.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from types import TracebackType

import yaml

from . import const
from ._models import (
    SmhubInfo,
    SmhubUpdate,
    validate_smhub_info,
    validate_smhub_update,
)
from ._protocol import build_frame
from ._transport import DEFAULT_CONNECT_TIMEOUT, DEFAULT_PORT, BusConnection
from .const import Command
from .exceptions import HabitronBusError, HabitronConnectionError

_LOGGER = logging.getLogger(__name__)

_DEFAULT_TIMEOUT: float = 10.0
_ERROR_PREFIX: bytes = b"Error"


def _scramble_token(token: bytes, mac: bytes) -> bytes:
    """Reorder *token* bytes using *mac* as a key (pure, no I/O).

    For each MAC octet, from last to first, the character at index ``octet & 0x7F``
    is moved to the end of the token. Same input always yields the same output.
    """
    result = token
    for octet in reversed(mac):
        idx = octet & 0x7F
        if idx < len(result):
            result = result[:idx] + result[idx + 1 :] + result[idx : idx + 1]
    return result


def _raise_on_bus_error(payload: bytes) -> bytes:
    """Raise :class:`HabitronBusError` if the hub reported an error.

    Returns *payload* unchanged otherwise.
    """
    if payload.startswith(_ERROR_PREFIX):
        raise HabitronBusError(payload.decode("iso8859-1", "replace"))
    return payload


class HabitronClient:
    """Typed async client for a single Habitron SmartHub.

    The connection is established eagerly when entering the context manager, so
    ``async with HabitronClient(host)`` raises ``HabitronConnectionError`` on
    enter if the hub is unreachable, rather than on the first request.
    """

    def __init__(
        self,
        host: str,
        port: int = DEFAULT_PORT,
        *,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        max_attempts: int = 1,
    ) -> None:
        """Create a client for ``host``:``port``.

        Args:
            host: SmartHub host name or IP address.
            port: SmartHub TCP port.
            connect_timeout: Seconds to wait when opening a connection.
            max_attempts: Number of attempts per request before raising.
                Defaults to 1 (no automatic retry). Retries are only safe for
                read-only operations the caller knows to be idempotent; commands
                that mutate device state (e.g. ``inc_dec_counter``) may be
                executed more than once if the response is lost on the wire.
                Must be >= 1.
        """
        self._host = host
        self._port = port
        self._entered = False
        self._bus = BusConnection(
            host, port, connect_timeout=connect_timeout, max_attempts=max_attempts
        )

    @property
    def host(self) -> str:
        """The SmartHub host name or IP address."""
        return self._host

    @property
    def port(self) -> int:
        """The SmartHub TCP port."""
        return self._port

    async def __aenter__(self) -> HabitronClient:
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self._bus.close()
        self._entered = False

    async def connect(self) -> None:
        """Open the connection eagerly (also performed by ``__aenter__``).

        ``_entered`` is only set after the connection succeeds, so a failed
        connect leaves no half-initialised, leaking client.
        """
        await self._bus.connect()
        self._entered = True

    async def close(self) -> None:
        """Close the connection."""
        await self._bus.close()
        self._entered = False

    def _ensure_entered(self) -> None:
        if not self._entered:
            raise HabitronConnectionError(
                "HabitronClient must be used as 'async with HabitronClient(...) "
                "as c'. Direct calls without context manager are unsupported."
            )

    # --- internal command helpers ----------------------------------------

    async def _send(
        self, cmd: Command, *args: int | bytes, timeout: float = _DEFAULT_TIMEOUT
    ) -> bytes:
        self._ensure_entered()
        return await self._bus.request(build_frame(cmd, args), timeout=timeout)

    async def _send_crc(
        self, cmd: Command, *args: int | bytes, timeout: float = _DEFAULT_TIMEOUT
    ) -> tuple[bytes, int]:
        self._ensure_entered()
        return await self._bus.request_crc(build_frame(cmd, args), timeout=timeout)

    async def _fire(self, cmd: Command, *args: int | bytes) -> None:
        self._ensure_entered()
        await self._bus.send_only(build_frame(cmd, args))

    # --- SmartHub info / lifecycle ---------------------------------------

    async def check_comm_status(self) -> bytes:
        """Return the SmartHub communication-status acknowledgement."""
        return await self._send(const.CHECK_COMM_STATUS, timeout=15.0)

    async def get_smhub_info(self) -> SmhubInfo:
        """Get basic SmartHub information (validated)."""
        raw = await self._send(const.GET_SMHUB_INFO, timeout=10.0)
        return validate_smhub_info(yaml.safe_load(raw.decode("iso8859-1")))

    async def get_smhub_update(self, hbtn_version: str) -> SmhubUpdate:
        """Get current sensor and status values (validated)."""
        version = hbtn_version.encode("iso8859-1")
        vlen = len(version)
        args_len = vlen + 1
        raw = await self._send(
            const.GET_SMHUB_UPDATE,
            bytes((args_len & 0xFF, args_len >> 8)),
            vlen,
            version,
            timeout=8.0,
        )
        return validate_smhub_update(yaml.safe_load(raw.decode("iso8859-1")))

    async def get_smhub_version(self) -> bytes:
        """Query the SmartHub firmware string."""
        return await self._send(const.GET_SMHUB_FIRMWARE)

    async def send_network_info(
        self,
        ipv4: str,
        token: bytes,
        mac: bytes,
        *,
        is_addon: bool,
        version: str,
    ) -> None:
        """Send Home Assistant IPv4, token and version to the SmartHub."""
        if not token:
            return
        scrambled = token if is_addon else _scramble_token(token, mac)
        ip_bytes = ipv4.encode("iso8859-1")
        version_bytes = version.encode("iso8859-1")
        args_len = len(ip_bytes) + len(scrambled) + len(version_bytes) + 3
        await self._send(
            const.SEND_NETWORK_INFO,
            bytes((args_len & 0xFF, args_len >> 8)),
            len(ip_bytes),
            ip_bytes,
            len(scrambled),
            scrambled,
            len(version_bytes),
            version_bytes,
        )

    async def reinit_hub(self, mode: int) -> bytes:
        """Restart the event server on the hub."""
        return await self._send(const.REINIT_HUB, mode, timeout=12.0)

    async def hub_restart(self) -> None:
        """Restart the hub."""
        await self._send(const.RESTART_HUB)

    async def hub_reboot(self) -> None:
        """Reboot the hub."""
        await self._send(const.REBOOT_HUB)

    async def module_restart(self, mod_nmbr: int) -> None:
        """Restart a single module (``mod_nmbr > 0``) or the router."""
        if mod_nmbr > 0:
            await self._send(const.REBOOT_MODULE, mod_nmbr)
        else:
            await self._send(const.REBOOT_ROUTER)

    async def restart_fwd_tbl(self) -> None:
        """Restart the forwarding table of the router."""
        await self._send(const.RESTART_FORWARD_TABLE)

    async def set_log_level(self, hdlr: int, level: int) -> None:
        """Set a new logging level for a console/file handler."""
        await self._send(const.SET_LOG_LEVEL, hdlr, level)

    # --- router / module queries -----------------------------------------

    async def get_smr(self) -> bytes:
        """Get router SMR information."""
        return _raise_on_bus_error(await self._send(const.GET_ROUTER_SMR, timeout=15.0))

    async def get_router_status(self) -> bytes:
        """Get router status."""
        return _raise_on_bus_error(await self._send(const.GET_ROUTER_STATUS))

    async def get_router_modules(self) -> bytes:
        """Get a summary of all Habitron modules of a router."""
        return _raise_on_bus_error(await self._send(const.GET_MODULES))

    async def get_global_descriptions(self) -> bytes:
        """Get descriptions of commands, flags, etc."""
        return await self._send(const.GET_GLOBAL_DESCRIPTIONS)

    async def get_error_status(self) -> bytes:
        """Get the error byte for each module."""
        return await self._send(const.GET_CURRENT_ERROR)

    async def get_module_definitions(self, mod_addr: int) -> bytes:
        """Get a module summary: names, commands, etc."""
        return _raise_on_bus_error(await self._send(const.GET_MODULE_SMC, mod_addr))

    async def get_module_settings(self, mod_addr: int) -> bytes:
        """Get the settings of a Habitron module."""
        return _raise_on_bus_error(await self._send(const.GET_MODULE_SMG, mod_addr))

    async def get_compact_status(self) -> tuple[bytes, int]:
        """Get the compact status for all modules (with CRC)."""
        return await self._send_crc(const.GET_COMPACT_STATUS, timeout=15.0)

    async def get_module_status(self, mod_nmbr: int) -> tuple[bytes, int]:
        """Get the status for a single module (with CRC)."""
        return await self._send_crc(const.GET_MODULE_STATUS, mod_nmbr, timeout=15.0)

    # --- firmware / power ------------------------------------------------

    async def handle_firmware(self, mod_nmbr: int) -> tuple[bytes, int]:
        """Read router/module firmware file version status (with CRC)."""
        if mod_nmbr:
            return await self._send_crc(
                const.GET_MODULE_FW_FILEVS, mod_nmbr, timeout=5.0
            )
        return await self._send_crc(const.GET_ROUTER_FW_FILEVS, timeout=5.0)

    async def update_firmware(self, mod_nmbr: int) -> tuple[bytes, int]:
        """Start a router/module firmware update (with CRC)."""
        return await self._send_crc(const.DO_FW_UPDATE, mod_nmbr, timeout=1000.0)

    async def power_cycle_channel_down(self, channel: int) -> None:
        """Power down a router channel."""
        await self._send_crc(const.POWER_DWN_CHAN, 1 << (channel - 1), timeout=1000.0)

    async def power_cycle_channel_up(self, channel: int) -> None:
        """Power a router channel back up."""
        await self._send_crc(const.POWER_UP_CHAN, 1 << (channel - 1), timeout=1000.0)

    async def send_devregid(self, mod_nmbr: int, devreg_id: str) -> None:
        """Send a device registry id to a module."""
        registry = devreg_id.encode("iso8859-1")
        await self._fire(const.SEND_MD_ID, mod_nmbr, len(registry), registry)

    # --- mirror ----------------------------------------------------------

    async def start_mirror(self) -> bytes:
        """Start the mirror on the router."""
        return await self._send(const.START_MIRROR)

    async def stop_mirror(self) -> None:
        """Stop the mirror on the router."""
        await self._send(const.STOP_MIRROR)

    # --- outputs / actuators ---------------------------------------------

    async def set_output(self, mod_addr: int, nmbr: int, val: bool) -> None:
        """Turn an output on or off."""
        await self._fire(
            const.SET_OUTPUT_ON if val else const.SET_OUTPUT_OFF, mod_addr, nmbr
        )

    async def set_dimmval(self, mod_addr: int, nmbr: int, val: int) -> None:
        """Set a dimmer output value."""
        await self._send(const.SET_DIMMER_VALUE, mod_addr, nmbr, val)

    async def set_rgb_output(self, mod_addr: int, nmbr: int, val: bool) -> None:
        """Turn an RGB light on or off."""
        await self._send(const.SET_RGB_ON if val else const.SET_RGB_OFF, mod_addr, nmbr)

    async def set_rgbval(self, mod_addr: int, nmbr: int, val: Sequence[int]) -> None:
        """Set an RGB output colour from a ``(red, green, blue)`` sequence."""
        await self._send(const.SET_RGB_COL, mod_addr, nmbr, val[0], val[1], val[2])

    async def set_shutterpos(self, mod_addr: int, nmbr: int, val: int) -> None:
        """Set a shutter position."""
        await self._send(const.SET_SHUTTER_POSITION, mod_addr, nmbr, val)

    async def set_blindtilt(self, mod_addr: int, nmbr: int, val: int) -> None:
        """Set a blind tilt value."""
        await self._send(const.SET_BLIND_TILT, mod_addr, nmbr, val)

    async def set_flag(self, mod_addr: int, nmbr: int, val: bool) -> None:
        """Set or clear a flag."""
        cmd = const.SET_FLAG_ON if val else const.SET_FLAG_OFF
        await self._send(cmd, mod_addr, nmbr)

    async def inc_dec_counter(self, mod_addr: int, nmbr: int, val: int) -> None:
        """Increment (``val == 1``) or decrement a counter."""
        await self._send(
            const.COUNTR_UP if val == 1 else const.COUNTR_DOWN, mod_addr, nmbr
        )

    async def set_setpoint(self, mod_addr: int, nmbr: int, val: int) -> None:
        """Set a two-byte setpoint value."""
        hi_val = val // 256
        lo_val = val - 256 * hi_val
        await self._send(const.SET_SETPOINT_VALUE, mod_addr, nmbr, lo_val, hi_val)

    async def set_climate_mode(self, mod_addr: int, cmode: int, ctl12: int) -> None:
        """Set the climate mode for a module."""
        await self._send(const.SET_CLIM_MODE, mod_addr, cmode, ctl12)

    # --- commands / groups / messages ------------------------------------

    async def call_dir_command(self, mod_addr: int, nmbr: int) -> None:
        """Call a direct command."""
        await self._send(const.CALL_DIR_COMMAND, mod_addr, nmbr)

    async def call_vis_command(self, mod_addr: int, nmbr: int) -> None:
        """Call a visualization command."""
        hi_no = nmbr // 256
        lo_no = nmbr - 256 * hi_no
        await self._send(const.CALL_VIS_COMMAND, mod_addr, lo_no, hi_no)

    async def call_coll_command(self, nmbr: int) -> None:
        """Call a collective command."""
        await self._send(const.CALL_COLL_COMMAND, nmbr)

    async def set_group_mode(self, grp_no: int, mode: int) -> None:
        """Set the mode for a group."""
        await self._send(const.SET_GROUP_MODE, grp_no, mode)

    async def send_message(self, mod_addr: int, msg_id: int) -> None:
        """Send a message to a module."""
        await self._send(const.SEND_MESSAGE, mod_addr, 15, msg_id)

    async def send_sms(self, mod_addr: int, msg_id: int, ct_id: int) -> None:
        """Send an SMS message to a module."""
        await self._send(const.SEND_SMS, mod_addr, ct_id, msg_id)
