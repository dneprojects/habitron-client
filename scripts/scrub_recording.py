#!/usr/bin/env python3
"""Anonymise a real-hub recording into a committable test fixture.

Reads ``scripts/captures/build_recording.json`` (produced by ``capture_hub.py``,
site-specific, git-ignored) and writes ``tests/fixtures/anon_recording.json``
(safe to commit). It overwrites only the *name* regions inside each payload with
filler bytes of the same length, so every structural byte — counts, lengths,
module-type codes, offsets, CRCs and firmware versions — is preserved and the
recording still replays through the parser. Room / module / flag names and the
SmartHub network identity are removed.

Usage (with the local library on the path)::

    cd /workspaces/habitron-client
    PYTHONPATH=src python scripts/scrub_recording.py
"""

from __future__ import annotations

import json
import pathlib
import re
from base64 import b64decode, b64encode
from typing import Any

_HERE = pathlib.Path(__file__).resolve().parent
_SRC = _HERE / "captures" / "build_recording.json"
_DST = _HERE.parent / "tests" / "fixtures" / "anon_recording.json"

_FILL = ord("x")


def _fill(buf: bytearray, start: int, end: int) -> None:
    """Overwrite ``buf[start:end]`` with filler, clamped to the buffer."""
    for j in range(start, min(end, len(buf))):
        buf[j] = _FILL


def _scrub_inventory(payload: bytes) -> bytes:
    """get_router_modules: [raddr, typ(2), name_len, name] entries."""
    out = bytearray(payload)
    i = 0
    while i + 4 <= len(out):
        name_len = out[i + 3]
        _fill(out, i + 4, i + 4 + name_len)
        i += 4 + name_len
    return bytes(out)


def _scrub_descriptions(payload: bytes) -> bytes:
    """get_global_descriptions: lines with name at line[9:line_len]."""
    out = bytearray(payload)
    no_lines = int.from_bytes(out[:2], "little")
    ptr = 4
    for _ in range(no_lines):
        if ptr + 9 > len(out):
            break
        line_len = out[ptr + 8] + 9
        _fill(out, ptr + 9, ptr + line_len)
        ptr += line_len
    return bytes(out)


def _scrub_module_definitions(payload: bytes) -> bytes:
    """get_module_definitions: label lines with text at line[8:-1].

    Fills through ``line_len`` (incl. the trailing separator byte) so no real
    name fragment can survive at the line boundary.
    """
    out = bytearray(payload)
    if len(out) < 7:
        return bytes(out)
    no_lines = int.from_bytes(out[3:5], "little")
    ptr = 7
    for _ in range(no_lines):
        if ptr + 6 > len(out):
            break
        line_len = out[ptr + 5] + 5
        _fill(out, ptr + 8, ptr + line_len)
        ptr += line_len
    return bytes(out)


def _scrub_smr(payload: bytes) -> bytes:
    """get_smr: four length-prefixed names (router/user1/user2/serial).

    The names are filled, then the whole gap between the last name and the
    (kept) firmware-version tail ``smr[-22:]`` is zeroed — the parser never
    reads it, and it can hold residual site strings.
    """
    out = bytearray(payload)
    ptr = 1
    for _ in range(4):  # channel sections
        if ptr >= len(out):
            return bytes(out)
        ptr += 1 + out[ptr]
    ptr += 2
    if ptr - 1 >= len(out):
        return bytes(out)
    grp_cnt = out[ptr - 1]
    ptr += 2 * grp_cnt + 1
    for _ in range(4):  # router name, user1, user2, serial
        if ptr >= len(out):
            break
        str_len = out[ptr]
        _fill(out, ptr + 1, ptr + 1 + str_len)
        ptr += str_len + 1
    # Zero everything up to the firmware-version tail (smr[-22:], kept).
    for j in range(ptr, max(ptr, len(out) - 22)):
        out[j] = 0
    return bytes(out)


# Byte offsets parse_settings actually reads; everything else in the 256-byte
# settings block (incl. embedded module names) is zeroed.
_SETTINGS_KEEP = (
    set(range(4, 36))  # shutter + tilt times
    | set(range(39, 42))  # input state
    | {48}  # climate mode
    | set(range(83, 122))  # hw + sw version strings
    | {131, 132, 153}  # climate ctl12, shutter stat, ad state
)


def _scrub_settings(payload: bytes) -> bytes:
    """get_module_settings: keep only parsed offsets, zero the rest."""
    out = bytearray(payload)
    for i in range(len(out)):
        if i not in _SETTINGS_KEEP:
            out[i] = 0
    return bytes(out)


_SCRUBBERS = {
    "get_router_modules": _scrub_inventory,
    "get_global_descriptions": _scrub_descriptions,
    "get_module_definitions": _scrub_module_definitions,
    "get_module_settings": _scrub_settings,
    "get_smr": _scrub_smr,
    # status payloads are pure binary (no names) → left untouched.
}

_MAC_RE = re.compile(r"^[0-9a-fA-F]{2}([:-][0-9a-fA-F]{2}){5}$")
_IP_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")


def _scrub_smhub_info(obj: Any, key: str = "") -> Any:
    """Recursively redact any mac/ip value and host/ssid key in smhub info."""
    if isinstance(obj, dict):
        return {k: _scrub_smhub_info(v, k) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_scrub_smhub_info(v) for v in obj]
    if isinstance(obj, str):
        if any(token in key.lower() for token in ("host", "ssid", "mac")):
            return "redacted"
        if _MAC_RE.match(obj):
            return "00:00:00:00:00:00"
        if _IP_RE.match(obj):
            return "0.0.0.0"
    return obj


def main() -> None:
    if not _SRC.exists():
        raise SystemExit(f"no recording at {_SRC} — run capture_hub.py first")
    data = json.loads(_SRC.read_text(encoding="utf-8"))

    for call in data["calls"]:
        scrubber = _SCRUBBERS.get(call["method"])
        if scrubber is None:
            continue
        payload = b64decode(call["bytes_b64"])
        call["bytes_b64"] = b64encode(scrubber(payload)).decode("ascii")

    data["b_uid"] = "anon"
    if "smhub_info" in data:
        data["smhub_info"] = _scrub_smhub_info(data["smhub_info"])

    _DST.parent.mkdir(parents=True, exist_ok=True)
    _DST.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Wrote anonymised fixture to {_DST}")
    print("Verify: PYTHONPATH=src python -m pytest tests/test_replay_real.py")


if __name__ == "__main__":
    main()
