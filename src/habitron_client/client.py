"""Habitron API client for socket communication and string handling."""

from __future__ import annotations
import logging
import socket
import struct
from typing import Any

import yaml

from .const import SMHUB_COMMANDS

_LOGGER = logging.getLogger(__name__)



class HabitronError(Exception):
    """Base exception for the Habitron client."""
    pass

class TimeoutException(HabitronError):
    """Error to indicate a network or command timeout."""
    pass


def init_crc16_tbl() -> list[int]:
    """Prepare the crc16 table."""
    res: list[int] = []
    for byte in range(256):
        crc = 0x0000
        for _ in range(8):
            if (byte ^ crc) & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
            byte >>= 1
        res.append(crc)
    return res


# Pre-calculate CRC table
__crc16_tbl: list[int] = init_crc16_tbl()


def calc_crc(data: bytes) -> int:
    """Calculate crc16 for byte string."""
    crc = 0xFFFF
    for byt in data:
        idx = __crc16_tbl[(crc ^ int(byt)) & 0xFF]
        crc = ((crc >> 8) & 0xFF) ^ idx
    return ((crc << 8) & 0xFF00) | ((crc >> 8) & 0x00FF)


def check_crc(msg: bytes) -> bool:
    """Check crc of message."""
    msg_crc = int.from_bytes(msg[-3:-1], "little")
    return calc_crc(msg[:-3]) == msg_crc


def wrap_command(cmd_string: str) -> str:
    """Take command and add prefix, crc, postfix."""
    cmd_prefix = "¨\0\0\x0bSmartConfig\x05michlS\x05"
    cmd_postfix = "\x3f"
    full_string = cmd_prefix + cmd_string
    cmd_len = len(full_string) + 3
    full_string = full_string[0] + chr(cmd_len) + full_string[2 : cmd_len - 3]
    cmd_crc = calc_crc(full_string.encode("iso8859-1"))
    crc_low = cmd_crc & 0xFF
    crc_high = (cmd_crc - crc_low) >> 8
    cmd_postfix = chr(crc_high) + chr(crc_low) + cmd_postfix
    return full_string + cmd_postfix


def format_block_output(byte_str: bytes) -> str:
    """Format block hex output with lines."""
    lbs = len(byte_str)
    res_str = ""
    ptr = 0
    while ptr < lbs:
        line = ""
        end_l = min([ptr + 10, lbs])
        for i in range(end_l - ptr):
            line = line + f"{f'{byte_str[ptr + i]:02X}'} "
        res_str += f"{f'{ptr:03d}'}  {line}{chr(13)}"
        ptr += 10
    return res_str


def get_own_ip() -> str:
    """Return string of own ip."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    own_ip = s.getsockname()[0]
    s.close()
    return own_ip


def get_host_ip(host_name: str) -> str:
    """Get IP from DNS host name."""
    return socket.gethostbyname(host_name)


class HabitronClient:
    """Habitron client for direct socket communication and protocol parsing."""

    def __init__(self, host: str, port: int = 7777) -> None:
        """Init client."""
        self.host = host
        self.port = port
        self.logger = logging.getLogger(__name__)

    def _send_receive(self, sck: socket.socket, cmd_str: str) -> bytes:
        """Send string to SmartHub and wait for response with timeout."""
        try:
            sck.send(cmd_str.encode("iso8859-1"))
            resp_bytes = sck.recv(30)
            if len(resp_bytes) < 30:
                return b"OK"
            resp_len = resp_bytes[29] * 256 + resp_bytes[28]
            resp_bytes = b""
            # Read remaining bytes
            while len(resp_bytes) < resp_len + 3:
                buffer = sck.recv(resp_len + 3)
                if not buffer:
                    raise TimeoutException("Connection dropped by SmartHub")
                resp_bytes = resp_bytes + buffer
            resp_bytes = resp_bytes[0:resp_len]
        except TimeoutError as exc:
            raise TimeoutException("Timeout during send_receive") from exc
        return resp_bytes

    def _send_receive_crc(self, sck: socket.socket, cmd_str: str) -> tuple[bytes, int]:
        """Send string to SmartHub and wait for response returning crc."""
        try:
            sck.send(cmd_str.encode("iso8859-1"))
            resp_bytes = sck.recv(30)
            if len(resp_bytes) < 30:
                return b"OK", 0
            resp_len = resp_bytes[29] * 256 + resp_bytes[28]
            resp_bytes = b""
            # Read remaining bytes
            while len(resp_bytes) < resp_len + 3:
                buffer = sck.recv(resp_len + 3)
                if not buffer:
                    raise TimeoutException("Connection dropped by SmartHub")
                resp_bytes = resp_bytes + buffer
            crc = resp_bytes[-2] * 256 + resp_bytes[-3]
            resp_bytes = resp_bytes[0:resp_len]
        except TimeoutError as exc:
            raise TimeoutException("Timeout during send_receive_crc") from exc
        return resp_bytes, crc

    def send_command_sync(self, cmd_string: str, time_out_sec: float = 10.0) -> bytes:
        """Synchronous version of send command."""
        sck = socket.socket()
        try:
            sck.settimeout(time_out_sec)
            sck.connect((self.host, self.port))
            full_string = wrap_command(cmd_string)
            resp_bytes = self._send_receive(sck, full_string)
        finally:
            sck.close()
        return resp_bytes

    def send_command_crc_sync(
        self, cmd_string: str, time_out_sec: float = 10.0
    ) -> tuple[bytes, int]:
        """Synchronous version of send command crc."""
        sck = socket.socket()
        try:
            sck.settimeout(time_out_sec)
            sck.connect((self.host, self.port))
            full_string = wrap_command(cmd_string)
            resp_bytes, crc = self._send_receive_crc(sck, full_string)
        finally:
            sck.close()
        return resp_bytes, crc

    def send_only(self, cmd_string: str) -> None:
        """Send string and return without waiting for response."""
        try:
            self.send_command_sync(cmd_string)
        except Exception as e:  # noqa: BLE001
            self.logger.warning("Error in send_only: %s", e)

    def _execute(
        self,
        cmd_key: str,
        replacements: dict[str, Any] | None = None,
        timeout: float = 10.0,
        crc: bool = False,
        send_only: bool = False,
    ) -> Any:
        """Helper to format and execute commands dynamically."""
        cmd_str = SMHUB_COMMANDS[cmd_key]
        if replacements:
            for key, val in replacements.items():
                # Automatically convert integers to characters for the protocol
                str_val = chr(val) if isinstance(val, int) else val
                cmd_str = cmd_str.replace(key, str_val)

        if send_only:
            self.send_only(cmd_str)
            return None
        if crc:
            return self.send_command_crc_sync(cmd_str, time_out_sec=timeout)
        return self.send_command_sync(cmd_str, time_out_sec=timeout)

    # --- High-level API Methods ---

    def get_smhub_info(self) -> dict:
        """Get basic infos of SmartHub parsed from YAML."""
        resp_bytes = self._execute("GET_SMHUB_INFO", timeout=10.0)
        decoded_resp = resp_bytes.decode("iso8859-1")
        info = yaml.load(decoded_resp, Loader=yaml.Loader)
        if not isinstance(info, dict):
            self.logger.warning("Invalid SmartHub info received")
            raise TimeoutException("Invalid response format")
        return info

    def get_smhub_update(self, hbtn_version: str) -> dict:
        """Get current sensor and status values parsed from YAML."""
        vlen = len(hbtn_version)
        args_len = vlen + 1
        resp_bytes = self._execute(
            "GET_SMHUB_UPDATE",
            {
                "<len>": chr(args_len & 0xFF) + chr(args_len >> 8),
                "<vlen>": vlen,
                "<vers>": hbtn_version,
            },
            timeout=8.0,
        )
        return yaml.load(resp_bytes.decode("iso8859-1"), Loader=yaml.Loader)

    def send_network_info(
        self, ipv4: str, tok: str, mac: str, is_addon: bool, version: str
    ) -> None:
        """Send home assistant ipv4, token and version."""
        if not tok:
            return
        ip_len = len(ipv4)
        tk_len = len(tok)
        vlen = len(version)
        if not is_addon:
            nmbrs = mac.split(":")
            for i in range(len(nmbrs)):
                idx = int("0x" + nmbrs[len(nmbrs) - i - 1], 0) & 0x7F
                if idx < tk_len:
                    tok = tok[:idx] + tok[idx + 1 :] + tok[idx]

        # Calculate correct total arguments length
        args_len = ip_len + tk_len + vlen + 3

        self._execute(
            "SEND_NETWORK_INFO",
            {
                "<len>": chr(args_len & 0xFF) + chr(args_len >> 8),
                "<iplen>": ip_len,
                "<ipv4>": ipv4,
                "<toklen>": tk_len,
                "<tok>": tok,
                "<vlen>": vlen,
                "<vers>": version,
            },
        )

    def reinit_hub(self, mode: int) -> bytes:
        """Restart event server on hub."""
        return self._execute("REINIT_HUB", {"<opr>": mode}, timeout=12.0)

    def get_smr(self) -> bytes:
        """Get router SMR information."""
        resp = self._execute("GET_ROUTER_SMR", timeout=15.0)
        return b"" if resp.decode("iso8859-1").startswith("Error") else resp

    def set_output(self, mod_addr: int, nmbr: int, val: bool) -> None:
        """Send turn_on/turn_off command."""
        cmd = "SET_OUTPUT_ON" if val else "SET_OUTPUT_OFF"
        self._execute(cmd, {"<mod>": mod_addr, "<arg1>": nmbr}, send_only=True)

    def set_dimmval(self, mod_addr: int, nmbr: int, val: int) -> None:
        """Send value to dimm output."""
        self._execute(
            "SET_DIMMER_VALUE", {"<mod>": mod_addr, "<arg1>": nmbr, "<arg2>": val}
        )

    def set_rgb_output(self, mod_addr: int, nmbr: int, val: bool) -> None:
        """Turn RGB light on/off."""
        cmd = "SET_RGB_ON" if val else "SET_RGB_OFF"
        self._execute(cmd, {"<mod>": mod_addr, "<lno>": nmbr})

    def set_rgbval(self, mod_addr: int, nmbr: int, val: list) -> None:
        """Send value to rgb output."""
        self._execute(
            "SET_RGB_COL",
            {
                "<mod>": mod_addr,
                "<lno>": nmbr,
                "<rd>": val[0],
                "<gn>": val[1],
                "<bl>": val[2],
            },
        )

    def set_shutterpos(self, mod_addr: int, nmbr: int, val: int) -> None:
        """Send value to shutter position."""
        self._execute(
            "SET_SHUTTER_POSITION", {"<mod>": mod_addr, "<arg1>": nmbr, "<arg2>": val}
        )

    def set_blindtilt(self, mod_addr: int, nmbr: int, val: int) -> None:
        """Send value to blind tilt."""
        self._execute(
            "SET_BLIND_TILT", {"<mod>": mod_addr, "<arg1>": nmbr, "<arg2>": val}
        )

    def set_flag(self, mod_addr: int, nmbr: int, val: bool) -> None:
        """Send flag on/flag off command."""
        cmd = "SET_FLAG_ON" if val else "SET_FLAG_OFF"
        self._execute(cmd, {"<mod>": mod_addr, "<fno>": nmbr})

    def inc_dec_counter(self, mod_addr: int, nmbr: int, val: int) -> None:
        """Send counter up/down command."""
        cmd = "COUNTR_UP" if val == 1 else "COUNTR_DOWN"
        self._execute(cmd, {"<mod>": mod_addr, "<cno>": nmbr})

    def set_setpoint(self, mod_addr: int, nmbr: int, val: int) -> None:
        """Send two byte value for setpoint definition."""
        hi_val = int(val / 256)
        lo_val = val - 256 * hi_val
        self._execute(
            "SET_SETPOINT_VALUE",
            {"<mod>": mod_addr, "<arg1>": nmbr, "<arg3>": hi_val, "<arg2>": lo_val},
        )

    def set_climate_mode(self, mod_addr: int, cmode: int, ctl12: int) -> None:
        """Set climate mode for given module."""
        self._execute(
            "SET_CLIM_MODE", {"<mod>": mod_addr, "<cmode>": cmode, "<ctl12>": ctl12}
        )

    def call_dir_command(self, mod_addr: int, nmbr: int) -> None:
        """Call of direct command of nmbr."""
        self._execute("CALL_DIR_COMMAND", {"<mod>": mod_addr, "<cno>": nmbr})

    def call_vis_command(self, mod_addr: int, nmbr: int) -> None:
        """Call of visualization command of nmbr."""
        hi_no = int(nmbr / 256)
        lo_no = nmbr - 256 * hi_no
        self._execute(
            "CALL_VIS_COMMAND", {"<mod>": mod_addr, "<vish>": hi_no, "<visl>": lo_no}
        )

    def call_coll_command(self, nmbr: int) -> None:
        """Call collective command of nmbr."""
        self._execute("CALL_COLL_COMMAND", {"<cno>": nmbr})

    def set_group_mode(self, grp_no: int, mode: int) -> None:
        """Set mode for given group."""
        self._execute("SET_GROUP_MODE", {"<mod>": grp_no, "<arg1>": mode})

    def set_log_level(self, hdlr: int, level: int) -> None:
        """Set new logging level."""
        self._execute("SET_LOG_LEVEL", {"<hdlr>": hdlr, "<lvl>": level})

    def send_message(self, mod_addr: int, msg_id: Any) -> None:
        """Send message to module."""
        self._execute("SEND_MESSAGE", {"<mod>": mod_addr, "<tim>": 15, "<msg>": msg_id})

    def send_sms(self, mod_addr: int, msg_id: Any, ct_id: int) -> None:
        """Send sms message to module."""
        self._execute("SEND_SMS", {"<mod>": mod_addr, "<sms>": ct_id, "<msg>": msg_id})

    def hub_restart(self) -> None:
        """Restart hub."""
        self._execute("RESTART_HUB")

    def hub_reboot(self) -> None:
        """Reboot hub."""
        self._execute("REBOOT_HUB")

    def module_restart(self, mod_nmbr: int) -> None:
        """Restart a single module or all with arg 0xFF or router if arg 0."""
        cmd = "REBOOT_MODULE" if mod_nmbr > 0 else "REBOOT_ROUTER"
        self._execute(cmd, {"<mod>": mod_nmbr} if mod_nmbr > 0 else None)

    def restart_fwd_tbl(self) -> None:
        """Restart forwarding table of router."""
        self._execute("RESTART_FORWARD_TABLE")

    def start_mirror(self) -> bytes:
        """Start mirror on specified router."""
        return self._execute("START_MIRROR")

    def stop_mirror(self) -> None:
        """Stop mirror on specified router."""
        self._execute("STOP_MIRROR")

    def get_smhub_version(self) -> bytes:
        """Query of SmartHub firmware."""
        return self._execute("GET_SMHUB_FIRMWARE")

    def get_router_status(self) -> bytes:
        """Get router status."""
        resp = self._execute("GET_ROUTER_STATUS")
        return b"" if resp.decode("iso8859-1").startswith("Error") else resp

    def get_router_modules(self) -> bytes:
        """Get summary of all Habitron modules of a router."""
        resp = self._execute("GET_MODULES")
        return b"" if resp.decode("iso8859-1").startswith("Error") else resp

    def get_global_descriptions(self) -> bytes:
        """Get descriptions of commands, etc."""
        return self._execute("GET_GLOBAL_DESCRIPTIONS")

    def get_error_status(self) -> bytes:
        """Get error byte for each module."""
        return self._execute("GET_CURRENT_ERROR")

    def get_module_definitions(self, mod_addr: int) -> bytes:
        """Get summary of Habitron module: names, commands, etc."""
        resp = self._execute("GET_MODULE_SMC", {"<mod>": mod_addr})
        return b"" if resp.decode("iso8859-1").startswith("Error") else resp

    def get_module_settings(self, mod_addr: int) -> bytes:
        """Get settings of Habitron module."""
        resp = self._execute("GET_MODULE_SMG", {"<mod>": mod_addr})
        return b"" if resp.decode("iso8859-1").startswith("Error") else resp

    def get_compact_status(self) -> tuple[bytes, int]:
        """Get compact status for all modules."""
        return self._execute("GET_COMPACT_STATUS", timeout=15.0, crc=True)

    def get_module_status(self, mod_nmbr: int) -> tuple[bytes, int]:
        """Get compact status for all modules."""
        return self._execute(
            "GET_MODULE_STATUS", {"<mod>": mod_nmbr}, timeout=15.0, crc=True
        )

    def handle_firmware(self, mod_nmbr: int) -> tuple[bytes, int]:
        """Handle router/module firmware update file status."""
        cmd = "GET_MODULE_FW_FILEVS" if mod_nmbr else "GET_ROUTER_FW_FILEVS"
        return self._execute(cmd, {"<mod>": mod_nmbr}, timeout=5.0, crc=True)

    def update_firmware(self, mod_nmbr: int) -> tuple[bytes, int]:
        """Start router/module firmware updates."""
        return self._execute(
            "DO_FW_UPDATE", {"<mod>": mod_nmbr}, timeout=1000.0, crc=True
        )

    def power_cycle_channel_down(self, channel: int) -> None:
        """Power down a router channel."""
        self._execute(
            "POWER_DWN_CHAN", {"<msk>": 1 << (channel - 1)}, timeout=1000.0, crc=True
        )

    def power_cycle_channel_up(self, channel: int) -> None:
        """Set power on again."""
        self._execute(
            "POWER_UP_CHAN", {"<msk>": 1 << (channel - 1)}, timeout=1000.0, crc=True
        )

    def send_devregid(self, mod_nmbr: int, devreg_id: str) -> None:
        """Send device registry id to module."""
        self._execute(
            "SEND_MD_ID",
            {"<mod>": mod_nmbr, "<len>": chr(len(devreg_id)), "<id>": devreg_id},
            send_only=True,
        )


def discover_smarthubs() -> list[dict[str, str]]:
    """Discover SmartHub and SmartServer hardware on the network."""
    smhub_port = 30718
    own_ip = get_own_ip()
    timeout = 2

    req_header_data = [0x00, 0x00, 0x00, 0xF6]
    req_header = struct.pack("B" * len(req_header_data), *req_header_data)
    resp_header_data = [0x00, 0x00, 0x00, 0xF7]
    resp_header = struct.pack("B" * len(resp_header_data), *resp_header_data)

    network_socket = socket.socket(
        socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP
    )
    network_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, True)
    network_socket.settimeout(timeout)
    network_socket.bind((own_ip, 0))

    network_socket.sendto(req_header, ("<broadcast>", smhub_port))

    smarthubs = []

    try:
        while True:
            response, address_info = network_socket.recvfrom(1024)

            smhub_ip = address_info[0]
            _LOGGER.info("SmartHub found at address %s", smhub_ip)

            if response[0:4] == resp_header and smhub_ip != "0.0.0.0":
                smhub_version = f"{response[7]}.{response[6]}.{response[5]}"
                smhub_mac = f"{response[24]:02X}:{response[25]:02X}:{response[26]:02X}:{response[27]:02X}:{response[28]:02X}:{response[29]:02X}"
                smhub_serial = (
                    f"{response[20]:c}{response[21]:c}{response[22]:c}{response[23]:c}"
                )
                smhub_type = f"{response[8]:c}-{response[9]:c}"
                smarthub_info = {
                    "type": smhub_type,
                    "version": smhub_version,
                    "serial": smhub_serial,
                    "mac": smhub_mac,
                    "ip": smhub_ip,
                }
                smarthubs.append(smarthub_info)
    except TimeoutError:
        pass
    finally:
        network_socket.close()

    return smarthubs


def query_smarthub(smhub_ip: str) -> dict[str, str]:
    """Read properties of identified SmartIP or SmartHub."""
    smartip_info: dict[str, str] = {}
    smhub_port = 30718
    timeout = 1

    req_header_data = [0x00, 0x00, 0x00, 0xF6]
    req_header = struct.pack("B" * len(req_header_data), *req_header_data)
    resp_header_data = [0x00, 0x00, 0x00, 0xF7]
    resp_header = struct.pack("B" * len(resp_header_data), *resp_header_data)

    network_socket = socket.socket(
        socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP
    )
    network_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, True)
    network_socket.settimeout(timeout)

    try:
        network_socket.sendto(req_header, (smhub_ip, smhub_port))
        response, address_info = network_socket.recvfrom(1024)

        smhub_ip = address_info[0]

        if response[0:4] == resp_header and smhub_ip != "0.0.0.0":
            smhub_version = f"{response[7]}.{response[6]}.{response[5]}"
            smhub_mac = f"{response[24]:02X}:{response[25]:02X}:{response[26]:02X}:{response[27]:02X}:{response[28]:02X}:{response[29]:02X}"
            smhub_serial = (
                f"{response[20]:c}{response[21]:c}{response[22]:c}{response[23]:c}"
            )
            smhub_type = f"{response[8]:c}-{response[9]:c}"

            if smhub_type == "E-5":
                smhub_name = f"SmartIP_{smhub_mac.replace(':', '')}"
            else:
                smhub_name = f"SmartHub_{smhub_mac.replace(':', '')}"

            smartip_info = {
                "name": smhub_name,
                "hostname": "",
                "type": smhub_type,
                "version": smhub_version,
                "serial": smhub_serial,
                "mac": smhub_mac,
                "ip": smhub_ip,
            }
    except TimeoutError:
        network_socket.close()
        return {}

    network_socket.close()
    try:
        smartip_info["hostname"] = socket.gethostbyaddr(smhub_ip)[0].split(".")[0]
    except (socket.herror, socket.gaierror, OSError, TimeoutException):
        smartip_info["hostname"] = ""
    return smartip_info


def test_connection(host_name: str) -> tuple[bool, str]:
    """Test connectivity to SmartHub is OK."""
    try:
        host = get_host_ip(host_name)
    except socket.gaierror as exc:
        raise socket.gaierror from exc

    client = HabitronClient(host, port=7777)

    try:
        resp_bytes = client._execute("CHECK_COMM_STATUS", timeout=15.0)  # noqa: SLF001
        resp_string = resp_bytes.decode("iso8859-1")
        conn_ok = resp_string.startswith("OK")
    except (TimeoutException, ConnectionRefusedError):
        return False, ""

    if conn_ok:
        smhub_info = query_smarthub(host)
        host_name = smhub_info.get("name", "")
    else:
        host_name = ""

    return conn_ok, host_name


# End of client definition.
