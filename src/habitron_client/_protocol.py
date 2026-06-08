"""Low-level wire protocol: CRC16, command wrapping and frame geometry.

This module is deliberately a faithful port of the original synchronous
implementation. The byte-level behaviour (CRC algorithm, prefix/postfix,
length field position) must not change during the async migration.
"""

from __future__ import annotations

from .const import Command

# --- Frame geometry -------------------------------------------------------

#: Number of bytes in the fixed response header that precedes the payload.
HEADER_SIZE: int = 30
#: Number of trailing bytes after the payload: CRC high, CRC low, postfix.
TRAILER_SIZE: int = 3
#: Index of the payload-length low byte within the response header.
LEN_LO_INDEX: int = 28
#: Index of the payload-length high byte within the response header.
LEN_HI_INDEX: int = 29

_CMD_PREFIX: bytes = b"\xa8\x00\x00\x0bSmartConfig\x05michlS\x05"
_CMD_POSTFIX: int = 0x3F


def _init_crc16_tbl() -> list[int]:
    """Pre-compute the CRC16 lookup table."""
    table: list[int] = []
    for value in range(256):
        crc = 0x0000
        byte = value
        for _ in range(8):
            if (byte ^ crc) & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
            byte >>= 1
        table.append(crc)
    return table


_CRC16_TBL: list[int] = _init_crc16_tbl()


def calc_crc(data: bytes) -> int:
    """Calculate the CRC16 of *data* using the SmartHub polynomial."""
    crc = 0xFFFF
    for byte in data:
        idx = _CRC16_TBL[(crc ^ byte) & 0xFF]
        crc = ((crc >> 8) & 0xFF) ^ idx
    return ((crc << 8) & 0xFF00) | ((crc >> 8) & 0x00FF)


def check_crc(frame: bytes) -> bool:
    """Return ``True`` if the trailing CRC of *frame* matches its body."""
    frame_crc = int.from_bytes(frame[-3:-1], "little")
    return calc_crc(frame[:-3]) == frame_crc


def build_frame(cmd: Command, args: tuple[int | bytes, ...]) -> bytes:
    """Substitute *args* into a command template, before wrapping.

    Integer arguments are encoded as a single byte; bytes arguments are
    inserted verbatim (used for multi-byte length fields and text payloads
    such as version strings or tokens).
    """
    if len(args) != len(cmd.placeholders):
        raise ValueError(
            f"command expects {len(cmd.placeholders)} argument(s) "
            f"{cmd.placeholders}, got {len(args)}"
        )
    frame = cmd.template
    for name, value in zip(cmd.placeholders, args, strict=True):
        token = b"<" + name.encode("ascii") + b">"
        payload = bytes((value,)) if isinstance(value, int) else value
        frame = frame.replace(token, payload)
    return frame


def wrap_command(payload: bytes) -> bytes:
    """Add prefix, length byte, CRC and postfix to a raw command payload."""
    body = _CMD_PREFIX + payload
    frame_len = len(body) + TRAILER_SIZE
    body = body[:1] + bytes((frame_len,)) + body[2:]
    crc = calc_crc(body)
    return body + bytes(((crc >> 8) & 0xFF, crc & 0xFF, _CMD_POSTFIX))


def format_block_output(byte_str: bytes) -> str:
    """Format a byte string as offset-prefixed lines of hex (10 bytes/line)."""
    length = len(byte_str)
    result = ""
    ptr = 0
    while ptr < length:
        end = min(ptr + 10, length)
        line = "".join(f"{byte_str[i]:02X} " for i in range(ptr, end))
        result += f"{ptr:03d}  {line}{chr(13)}"
        ptr += 10
    return result
