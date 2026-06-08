"""Characterization tests for the pure token-scrambling function.

The oracle reimplements the original str/MAC-string algorithm exactly. The new
bytes-only implementation must match it for every input, locking the wire
behaviour without needing a hardware capture.
"""

from __future__ import annotations

import pytest

from habitron_client.client import _scramble_token


def _old_scramble(token: str, mac: str) -> str:
    nmbrs = mac.split(":")
    for i in range(len(nmbrs)):
        idx = int("0x" + nmbrs[len(nmbrs) - i - 1], 0) & 0x7F
        if idx < len(token):
            token = token[:idx] + token[idx + 1 :] + token[idx]
    return token


@pytest.mark.parametrize(
    ("token", "mac"),
    [
        ("abcdefghijklmnop0123456789", "A1:B2:C3:04:E5:0F"),
        ("short", "FF:FF:FF:FF:FF:FF"),
        ("token-with-symbols_=.", "00:00:00:00:00:00"),
        ("x", "7F:01:02:03:04:05"),
        ("longtoken" * 5, "12:34:56:78:9A:BC"),
        ("", "01:02:03:04:05:06"),
    ],
)
def test_scramble_matches_legacy(token: str, mac: str) -> None:
    mac_bytes = bytes.fromhex(mac.replace(":", ""))
    expected = _old_scramble(token, mac).encode("iso8859-1")
    assert _scramble_token(token.encode("iso8859-1"), mac_bytes) == expected


def test_scramble_is_pure() -> None:
    token = b"deterministic"
    mac = bytes.fromhex("a1b2c3d4e5f6")
    assert _scramble_token(token, mac) == _scramble_token(token, mac)


def test_scramble_addon_mac_noop_index_out_of_range() -> None:
    # All MAC octets index past the token length -> token unchanged.
    assert _scramble_token(b"ab", bytes.fromhex("646464646464")) == b"ab"
