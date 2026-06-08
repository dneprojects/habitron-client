"""Network discovery and connectivity helpers for SmartHub hardware.

Discovery uses the SmartHub UDP identification protocol (port 30718) over
``asyncio`` datagram endpoints. DNS lookups go through the running loop so no
call blocks the event loop.
"""

from __future__ import annotations

import asyncio
import logging
import socket

from .client import HabitronClient
from .exceptions import HabitronConnectionError, HabitronError

_LOGGER = logging.getLogger(__name__)

_DISCOVERY_PORT: int = 30718
_DISCOVERY_TIMEOUT: float = 2.0
_QUERY_TIMEOUT: float = 1.0
_REQ_HEADER: bytes = b"\x00\x00\x00\xf6"
_RESP_HEADER: bytes = b"\x00\x00\x00\xf7"
_DESCRIPTOR_SIZE: int = 30


class _DiscoveryProtocol(asyncio.DatagramProtocol):
    """Collects incoming identification datagrams into a queue."""

    def __init__(self) -> None:
        self.queue: asyncio.Queue[tuple[bytes, tuple[str, int]]] = asyncio.Queue()

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        self.queue.put_nowait((data, addr))


def get_own_ip() -> str:
    """Return this host's primary outbound IPv4 address."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return str(sock.getsockname()[0])
    finally:
        sock.close()


async def get_host_ip(host_name: str) -> str:
    """Resolve *host_name* to an IPv4 address (async DNS).

    Raises:
        HabitronConnectionError: if the name cannot be resolved.
    """
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(
            host_name, None, family=socket.AF_INET, type=socket.SOCK_STREAM
        )
    except socket.gaierror as exc:
        raise HabitronConnectionError(f"cannot resolve host {host_name!r}") from exc
    return str(infos[0][4][0])


def _parse_descriptor(data: bytes, ip: str) -> dict[str, str] | None:
    """Parse an identification response, or return ``None`` if not one."""
    if len(data) < _DESCRIPTOR_SIZE or data[0:4] != _RESP_HEADER or ip == "0.0.0.0":
        return None
    return {
        "type": f"{chr(data[8])}-{chr(data[9])}",
        "version": f"{data[7]}.{data[6]}.{data[5]}",
        "serial": "".join(chr(data[i]) for i in range(20, 24)),
        "mac": ":".join(f"{data[i]:02X}" for i in range(24, 30)),
        "ip": ip,
    }


async def discover_smarthubs(
    timeout: float = _DISCOVERY_TIMEOUT,
) -> list[dict[str, str]]:
    """Discover SmartHub/SmartServer hardware on the local network."""
    loop = asyncio.get_running_loop()
    try:
        transport, protocol = await loop.create_datagram_endpoint(
            _DiscoveryProtocol,
            local_addr=(get_own_ip(), 0),
            allow_broadcast=True,
        )
    except OSError as exc:
        raise HabitronConnectionError("cannot open discovery socket") from exc
    found: list[dict[str, str]] = []
    seen: set[str] = set()
    try:
        transport.sendto(_REQ_HEADER, ("<broadcast>", _DISCOVERY_PORT))
        deadline = loop.time() + timeout
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            try:
                data, addr = await asyncio.wait_for(protocol.queue.get(), remaining)
            except TimeoutError:
                break
            info = _parse_descriptor(data, addr[0])
            if info is not None and info["ip"] not in seen:
                seen.add(info["ip"])
                _LOGGER.info("SmartHub found at %s", info["ip"])
                found.append(info)
    finally:
        transport.close()
    return found


async def query_smarthub(smhub_ip: str) -> dict[str, str]:
    """Read the properties of a single identified SmartIP/SmartHub."""
    loop = asyncio.get_running_loop()
    try:
        transport, protocol = await loop.create_datagram_endpoint(
            _DiscoveryProtocol,
            remote_addr=(smhub_ip, _DISCOVERY_PORT),
        )
    except OSError as exc:
        raise HabitronConnectionError(
            f"cannot reach {smhub_ip}:{_DISCOVERY_PORT}"
        ) from exc
    try:
        transport.sendto(_REQ_HEADER)
        try:
            data, addr = await asyncio.wait_for(protocol.queue.get(), _QUERY_TIMEOUT)
        except TimeoutError:
            return {}
    finally:
        transport.close()

    descriptor = _parse_descriptor(data, addr[0])
    if descriptor is None:
        return {}
    mac_flat = descriptor["mac"].replace(":", "")
    prefix = "SmartIP" if descriptor["type"] == "E-5" else "SmartHub"
    info: dict[str, str] = {
        "name": f"{prefix}_{mac_flat}",
        "hostname": "",
        **descriptor,
    }
    try:
        host, _ = await loop.getnameinfo((descriptor["ip"], 0), socket.NI_NAMEREQD)
        info["hostname"] = host.split(".")[0]
    except (socket.gaierror, OSError):
        info["hostname"] = ""
    return info


async def test_connection(host_name: str) -> tuple[bool, str]:
    """Test connectivity to a SmartHub; return ``(ok, name)``."""
    host = await get_host_ip(host_name)
    client = HabitronClient(host)
    try:
        await client.connect()
        resp = await client.check_comm_status()
        conn_ok = resp.decode("iso8859-1").startswith("OK")
    except HabitronError:
        return False, ""
    finally:
        await client.close()

    if not conn_ok:
        return False, ""
    info = await query_smarthub(host)
    return True, info.get("name", "")
