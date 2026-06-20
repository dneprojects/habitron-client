"""Tests for the recording scrubber (``scripts/scrub_recording.py``).

The scrubber must remove site-specific names while keeping every structural
byte intact, so an anonymised recording still parses to the same *shape* (module
types, areas, group layout) as the real one — only the names differ.
"""

import importlib.util
import pathlib

from habitron_client._parse import build_module, parse_definitions
from habitron_client._parse_router import (
    build_router,
    parse_global_descriptions,
    parse_module_inventory,
    parse_router_definitions,
)

_SCRUB_PATH = (
    pathlib.Path(__file__).resolve().parent.parent / "scripts" / "scrub_recording.py"
)
_spec = importlib.util.spec_from_file_location("scrub_recording", _SCRUB_PATH)
assert _spec is not None and _spec.loader is not None
scrub = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scrub)


def test_scrub_inventory_keeps_type_drops_name() -> None:
    """Module type code survives; the module name becomes filler."""
    payload = bytes([5]) + b"\x0a\x01" + bytes([3]) + b"Out"
    scrubbed = scrub._scrub_inventory(payload)
    assert len(scrubbed) == len(payload)
    mods = parse_module_inventory(
        scrubbed, b_uid="b1", router_id=100, module_grp=[0, 0, 0, 0, 7]
    )
    assert mods[0].mod_type == "Smart Out 8/R"  # type bytes preserved
    assert mods[0].addr == 105
    assert mods[0].name == "xxx"  # name anonymised


def _desc_line(content_code: int, entry_no: int, entry_name: bytes) -> bytes:
    header = bytearray(9)
    header[1] = content_code & 0xFF
    header[2] = (content_code >> 8) & 0xFF
    header[3] = entry_no
    header[8] = len(entry_name)
    return bytes(header) + entry_name


def test_scrub_descriptions_keeps_structure_drops_names() -> None:
    """Area numbers / autostop survive; flag and area names become filler."""
    lines = [
        _desc_line(767, 1, b"flag-1"),
        _desc_line(2815, 2, b"Kitchen"),
        _desc_line(3071, 7, b"unused"),
    ]
    payload = bytes([len(lines), 0, 0, 0]) + b"".join(lines)
    scrubbed = scrub._scrub_descriptions(payload)
    assert len(scrubbed) == len(payload)
    rt = build_router(b_uid="X")
    parse_global_descriptions(rt, scrubbed)
    area = next(a for a in rt.areas if a.nmbr == 2)
    assert area.name == "xxxxxxx"  # 7 chars, anonymised
    assert rt.cover_autostop_del == 7  # structural value preserved
    assert rt.flags[0].nmbr == 1


def _name_line(arg_code: int, area: int, text: bytes) -> bytes:
    payload = text + b"\x00"
    line_len = 8 + len(payload)
    return bytes([255, area, 235, arg_code, 1, line_len - 5, 0, 0]) + payload


def test_scrub_module_definitions_keeps_area_drops_name() -> None:
    """Input area survives; the input label becomes filler."""
    lines = [_name_line(40, 3, b"Kitchen Light")]
    payload = bytes([0, 0, 0, len(lines), 0, 0, 0]) + b"".join(lines)
    scrubbed = scrub._scrub_module_definitions(payload)
    assert len(scrubbed) == len(payload)
    sc = build_module(uid="b1", addr=105, typ=b"\x01\x03", name="SC", group=0)
    parse_definitions(sc, scrubbed)
    assert sc.inputs[8].area == 3  # area byte preserved
    assert set(sc.inputs[8].name) == {"x"}  # name fully anonymised


def test_scrub_smr_keeps_layout_drops_names() -> None:
    """Channel/group layout survives; router/user/serial names become filler."""
    smr = bytearray(b"\x00" * 256)
    smr[1] = 2
    smr[2] = 5
    smr[3] = 6
    smr[8] = 2
    smr[9] = 3
    smr[10] = 4
    smr[14] = 4
    smr[15:19] = b"R-Hb"
    smr[19] = 3
    smr[20:23] = b"Bob"
    smr[23] = 3
    smr[24:27] = b"Sue"
    smr[27] = 5
    smr[28:33] = b"S/N-1"
    smr[-22:] = b"v1.0                  "
    scrubbed = scrub._scrub_smr(bytes(smr))
    assert len(scrubbed) == len(smr)
    rt = build_router(b_uid="X")
    parse_router_definitions(rt, scrubbed)
    assert len(rt.module_grp) == 6  # group layout preserved
    assert rt.max_group == 4
    assert rt.name == "xxxx"  # 4 chars, anonymised
    assert rt.serial == "xxxxx"  # 5 chars, anonymised
    assert rt.version == "v1.0"  # firmware version left intact


def test_scrub_smhub_info_redacts_network_identity() -> None:
    """The hub mac / host / ip are replaced; structure stays a dict."""
    info = {
        "hardware": {
            "network": {"ip": "192.168.1.5", "host": "myhub", "lan mac": "AA:BB:CC"}
        }
    }
    out = scrub._scrub_smhub_info(info)
    net = out["hardware"]["network"]
    assert net["ip"] == "0.0.0.0"
    assert net["host"] == "redacted"
    assert net["lan mac"] == "redacted"  # any "mac" key → redacted
