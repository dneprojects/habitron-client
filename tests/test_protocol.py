"""Tests for CRC, framing, command building and formatting."""

from __future__ import annotations

import pytest

from habitron_client import const
from habitron_client._protocol import (
    build_frame,
    calc_crc,
    check_crc,
    format_block_output,
    format_smc,
    wrap_command,
)
from habitron_client.const import Command
from habitron_client.exceptions import HabitronProtocolError


def _old_wrap(cmd_string: str) -> bytes:
    """Faithful reimplementation of the original str-based wrap_command."""
    cmd_prefix = "\xa8\0\0\x0bSmartConfig\x05michlS\x05"
    cmd_postfix = "\x3f"
    full = cmd_prefix + cmd_string
    cmd_len = len(full) + 3
    full = full[0] + chr(cmd_len) + full[2 : cmd_len - 3]
    crc = calc_crc(full.encode("iso8859-1"))
    lo = crc & 0xFF
    hi = (crc - lo) >> 8
    return (full + chr(hi) + chr(lo) + cmd_postfix).encode("iso8859-1")


@pytest.mark.parametrize(
    "payload",
    [b"", b"\x1e\x01\x01\x01\x0c", b"\x00" * 40, bytes(range(64))],
)
def test_wrap_command_matches_legacy(payload: bytes) -> None:
    assert wrap_command(payload) == _old_wrap(payload.decode("iso8859-1"))


def test_check_crc_roundtrip() -> None:
    body = b"hello world payload"
    crc = calc_crc(body)
    frame = body + bytes((crc & 0xFF, (crc >> 8) & 0xFF, 0x3F))
    assert check_crc(frame) is True
    corrupted = body[:-1] + b"X" + frame[-3:]
    assert check_crc(corrupted) is False


def test_build_frame_substitution() -> None:
    assert build_frame(const.SET_OUTPUT_ON, (12, 3)) == (
        b"\x1e\x01\x01\x01\x0c\x03\x00\x01\x0c\x03"
    )


def test_build_frame_two_byte_and_bytes_args() -> None:
    # SET_SETPOINT_VALUE: mod, arg1, arg2(lo), arg3(hi)
    assert build_frame(const.SET_SETPOINT_VALUE, (5, 2, 0x2C, 0x01)) == (
        b"\x1e\x02\x01\x01\x00\x05\x00\x01\x05\x02\x2c\x01"
    )
    # SEND_MD_ID carries a bytes payload verbatim
    assert build_frame(const.SEND_MD_ID, (5, 2, b"ab")) == (
        b"\x3c\x03\x09\x01\x05\x02\x00ab"
    )


def test_build_frame_wrong_arg_count() -> None:
    with pytest.raises(ValueError, match="expects 2 argument"):
        build_frame(const.SET_OUTPUT_ON, (1,))


def _all_commands() -> list[tuple[str, Command]]:
    return [
        (name, value)
        for name, value in vars(const).items()
        if isinstance(value, Command)
    ]


def test_every_command_placeholder_matches_template() -> None:
    import re

    for name, cmd in _all_commands():
        tokens = re.findall(rb"<(\w+)>", cmd.template)
        unique = []
        for tok in tokens:
            decoded = tok.decode("ascii")
            if decoded not in unique:
                unique.append(decoded)
        assert tuple(unique) == cmd.placeholders, name


def test_build_every_command_consumes_all_placeholders() -> None:
    for name, cmd in _all_commands():
        args: tuple[int | bytes, ...] = tuple(1 for _ in cmd.placeholders)
        frame = build_frame(cmd, args)
        for placeholder in cmd.placeholders:
            assert b"<" + placeholder.encode("ascii") + b">" not in frame, name


def test_format_block_output() -> None:
    out = format_block_output(bytes(range(12)))
    lines = out.split(chr(13))
    assert lines[0].startswith("000  00 01 02")
    assert lines[1].startswith("010  0A 0B")


def test_format_smc_header_and_lines() -> None:
    # 7-byte header, then a line whose length is data[5]+5: offset 5 holds 2,
    # so the line spans 7 bytes (and the loop needs >6 bytes left to run).
    header = bytes(range(7))
    line = bytes((20, 21, 22, 23, 24, 2, 26))  # line[5] = 2 -> line_len = 7
    out = format_smc(header + line)
    rows = out.split(chr(13))
    assert rows[0] == "0;1;2;3;4;5;6;"
    assert rows[1] == "20;21;22;23;24;2;26;"


def test_format_smc_too_short_raises() -> None:
    with pytest.raises(HabitronProtocolError, match="too short"):
        format_smc(b"\x00\x01\x02")


def test_format_smc_truncated_line_raises() -> None:
    # Header + a line claiming length data[5]+5 = 250+5 but only a few bytes left.
    bad = bytes(range(7)) + bytes((0, 0, 0, 0, 0, 250, 0))
    with pytest.raises(HabitronProtocolError, match="malformed"):
        format_smc(bad)
