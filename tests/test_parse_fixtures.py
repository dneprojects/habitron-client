"""Byte-vector fidelity tests for the parsing layer.

These resurrect the real status / definition byte vectors that used to live in
the integration's ``test_module.py`` / ``test_router.py`` and run them through
the *library* parser (:mod:`habitron_client._parse` /
:mod:`habitron_client._parse_router`). They assert the parser turns the exact
same bytes into the exact same model values as the pre-library code did, so the
move into the library is byte-for-byte faithful without needing hardware.
"""

from habitron_client._indices import (
    FALSE_VAL,
    TRUE_VAL,
    MSetIdx,
    MStatIdx,
    RoutIdx,
)
from habitron_client._parse import (
    apply_status,
    build_module,
    parse_definitions,
    parse_settings,
)
from habitron_client._parse_router import (
    apply_router_status,
    build_router,
    distribute_status,
    parse_global_descriptions,
    parse_module_inventory,
    parse_router_definitions,
)
from habitron_client.model import Cover, Flag, Module


def _zero_status() -> bytearray:
    """An all-zero compact-status block of the canonical length."""
    return bytearray(MStatIdx.END)


def _module(typ: bytes, name: str = "M") -> Module:
    """Build an empty module of ``typ`` via the library factory."""
    return build_module(uid="b1", addr=105, typ=typ, name=name, group=0)


# --------------------------------------------------------------------------- #
# Status parsing — covers (position + tilt)                                    #
# --------------------------------------------------------------------------- #


def test_controller_status_writes_cover_position_and_tilt() -> None:
    """SC cover at nmbr=0 pulls position/tilt from the +5 remapped slot."""
    sc = _module(b"\x01\x03", "SC LE2")
    sc.covers[0] = Cover(name="Sh 0", nmbr=0, type=1)
    status = _zero_status()
    status[MStatIdx.ROLL_POS + 3] = 50  # cm_idx 0 - 2 + 5 = 3
    status[MStatIdx.BLAD_POS + 3] = 25
    apply_status(sc, bytes(status))
    assert sc.covers[0].position == 50
    assert sc.covers[0].tilt == 25


def test_out_status_writes_cover_position_and_tilt() -> None:
    """Smart Out cover at nmbr=0 reads ROLL_POS/BLAD_POS directly."""
    out = _module(b"\x0a\x01", "Out 8/R")
    out.covers[0] = Cover(name="Sh 0", nmbr=0, type=1)
    status = _zero_status()
    status[MStatIdx.ROLL_POS + 0] = 80
    status[MStatIdx.BLAD_POS + 0] = 20
    apply_status(out, bytes(status))
    assert out.covers[0].position == 80
    assert out.covers[0].tilt == 20


def test_io2_status_writes_cover_position_and_tilt() -> None:
    """Smart IO 2 cover reads the ROLL_POS-1/BLAD_POS-1 slot."""
    io = _module(b"\x0a\x1e", "IO 2")
    io.covers[0] = Cover(name="Sh 0", nmbr=0, type=1)
    status = _zero_status()
    status[MStatIdx.ROLL_POS - 1] = 60
    status[MStatIdx.BLAD_POS - 1] = 10
    apply_status(io, bytes(status))
    assert io.covers[0].position == 60
    assert io.covers[0].tilt == 10


# --------------------------------------------------------------------------- #
# Status parsing — flags                                                       #
# --------------------------------------------------------------------------- #


def test_controller_status_sets_flag_value_from_bit() -> None:
    """A flag whose bit (nmbr-1) is set in FLAG_LOC ends up value 1."""
    sc = _module(b"\x01\x03", "SC LE2")
    sc.flags = [Flag(name="flg", nmbr=1, idx=0, type=1, value=0)]
    status = _zero_status()
    status[MStatIdx.FLAG_LOC] = 0x01  # bit 0
    apply_status(sc, bytes(status))
    assert sc.flags[0].value == 1


def test_mini_status_sets_flag_value_from_bit() -> None:
    """SC Mini also decodes the FLAG_LOC bit into the flag value."""
    mini = _module(b"\x32\x01", "Mini")
    mini.flags = [Flag(name="flg", nmbr=1, idx=0, type=1, value=0)]
    status = _zero_status()
    status[MStatIdx.FLAG_LOC] = 0x01
    apply_status(mini, bytes(status))
    assert mini.flags[0].value == 1


# --------------------------------------------------------------------------- #
# Status parsing — colour LEDs (unified: Touch + Mini both read RGB_MASK)      #
# --------------------------------------------------------------------------- #


def test_mini_status_color_leds_from_rgb_mask() -> None:
    """Mini colour LEDs read on/off + colour from RGB_MASK, not the output bits."""
    mini = _module(b"\x32\x01", "Mini")
    status = _zero_status()
    status[MStatIdx.RGB_MASK] = 0x02  # bit 1 -> color_leds[1] on
    base = MStatIdx.RGB_MASK + 3 * 1
    status[base + 1], status[base + 2], status[base + 3] = 10, 20, 30
    apply_status(mini, bytes(status))
    assert mini.color_leds[1].is_on is True
    assert mini.color_leds[1].rgb == [10, 20, 30, 0]
    assert mini.color_leds[0].is_on is False


def test_touch_status_color_leds_from_rgb_mask() -> None:
    """Smart Touch colour LEDs use the very same RGB_MASK path (no module case)."""
    sc = _module(b"\x01\x04", "Touch")
    status = _zero_status()
    status[MStatIdx.RGB_MASK] = 0x01  # bit 0 -> color_leds[0] on
    base = MStatIdx.RGB_MASK
    status[base + 1], status[base + 2], status[base + 3] = 1, 2, 3
    apply_status(sc, bytes(status))
    assert sc.color_leds[0].is_on is True
    assert sc.color_leds[0].rgb == [1, 2, 3, 0]


# --------------------------------------------------------------------------- #
# Status parsing — analogue inputs                                             #
# --------------------------------------------------------------------------- #


def test_input_status_walks_six_analog_inputs() -> None:
    """A Smart In 8/24V-1 maps AD_1/AD_2/GEN_1..4 to its six analog inputs."""
    inp = _module(b"\x0b\x1f", "In 16/24V")
    assert len(inp.analogins) == 6
    status = _zero_status()
    status[MStatIdx.AD_1] = 11
    status[MStatIdx.AD_2] = 22
    status[MStatIdx.GEN_1] = 33
    status[MStatIdx.GEN_2] = 44
    status[MStatIdx.GEN_3] = 55
    status[MStatIdx.GEN_4] = 66
    apply_status(inp, bytes(status))
    assert inp.analogins[0].value == 11
    assert inp.analogins[5].value == 66


# --------------------------------------------------------------------------- #
# Status parsing — negative temperatures (sign-magnitude decode)              #
# --------------------------------------------------------------------------- #


def test_nature_status_decodes_negative_temperature() -> None:
    """0x8064 → bit15 set → -100 / 10 = -10.0 C."""
    nat = _module(b"\x14\x01", "Nature")
    status = _zero_status()
    status[MStatIdx.TEMP_ROOM] = 0x64
    status[MStatIdx.TEMP_ROOM + 1] = 0x80
    apply_status(nat, bytes(status))
    assert nat.sensors[0].value == -10.0


def test_sensor_status_decodes_negative_temperature() -> None:
    """0x80C8 → bit15 set → -200 / 10 = -20.0 C."""
    s = _module(b"\x32\x28", "Sensor")
    status = _zero_status()
    status[MStatIdx.TEMP_ROOM] = 0xC8
    status[MStatIdx.TEMP_ROOM + 1] = 0x80
    apply_status(s, bytes(status))
    assert s.sensors[0].value == -20.0


# --------------------------------------------------------------------------- #
# Status parsing — ekey disabled-user encoding                                 #
# --------------------------------------------------------------------------- #


def test_ekey_status_decodes_disabled_user() -> None:
    """A finger value > 10 negates the user id and subtracts 128."""
    ek = _module(b"\x1e\x01", "ekey")
    status = _zero_status()
    status[MStatIdx.KEY_ID] = 5  # user id
    status[MStatIdx.KEY_ID + 1] = 140  # finger > 10 → disabled encoding
    apply_status(ek, bytes(status))
    assert ek.sensors[0].value == -5
    assert ek.sensors[1].value == 12


# --------------------------------------------------------------------------- #
# Status parsing — counter discovery                                           #
# --------------------------------------------------------------------------- #


def test_status_discovers_counters_from_type_marker() -> None:
    """COUNTER slots carrying a type-5 marker seed logic counters."""
    mod = _module(b"\x0b\x1e", "In")
    status = _zero_status()
    status[MStatIdx.COUNTER + 0] = 5
    status[MStatIdx.COUNTER + 3] = 5
    apply_status(mod, bytes(status))
    assert sum(lgc.type == 5 for lgc in mod.logic) == 2


def test_status_seeds_notavailable_counter_when_none_present() -> None:
    """With no counter marker the parser seeds a single NotAvailable stub."""
    mod = _module(b"\x0b\x1e", "In")
    apply_status(mod, bytes(_zero_status()))
    assert any(lgc.name == "NotAvailable" for lgc in mod.logic)


# --------------------------------------------------------------------------- #
# Settings parsing — versions / climate / shutter detection                    #
# --------------------------------------------------------------------------- #


def test_settings_parses_versions_and_climate_fields() -> None:
    """A space-padded settings block yields hw/sw version + climate fields."""
    sc = _module(b"\x01\x03", "SC LE2")
    resp = bytearray(b" " * 256)
    hw = b"HW-1.2.3"
    sw = b"SW-2.3.4"
    resp[MSetIdx.HW_VERS : MSetIdx.HW_VERS + len(hw)] = hw
    resp[MSetIdx.SW_VERS : MSetIdx.SW_VERS + len(sw)] = sw
    resp[MSetIdx.CLIM_MODE] = 1
    resp[MSetIdx.CLIM_CTL12] = 2
    assert parse_settings(sc, bytes(resp)) is True
    assert sc.hw_version == "HW-1.2.3"
    assert sc.sw_version == "SW-2.3.4"
    assert sc.climate_settings == 1
    assert sc.climate_ctl12 == 2


def test_settings_marks_shutter_outputs_when_flag_set() -> None:
    """A SHUTTER_STAT bit promotes the matching cover and disables its outputs."""
    sc = _module(b"\x01\x03", "SC LE2")
    resp = bytearray(b"\x00" * 256)
    resp[MSetIdx.SHUTTER_STAT] = 0x01  # cm_idx 0 → c_idx 2 in the SC remap
    assert parse_settings(sc, bytes(resp)) is True
    assert sc.covers[2].nmbr == 2
    assert sc.outputs[4].type == -10
    assert sc.outputs[5].type == -10


# --------------------------------------------------------------------------- #
# Definitions / label parsing                                                  #
# --------------------------------------------------------------------------- #


def _name_line(
    sub_code: int, area: int, arg_code: int, text: bytes, lang: int = 1
) -> bytes:
    """Build one Beschriftung (event 235) label line."""
    payload = text + b"\x00"
    line_len = 8 + len(payload)
    return bytes([sub_code, area, 235, arg_code, lang, line_len - 5, 0, 0]) + payload


def _names_response(lines: list[bytes]) -> bytes:
    """Wrap label lines in the (non-SC) definitions header."""
    header = bytes([0, 0, 0, len(lines) & 0xFF, (len(lines) >> 8) & 0xFF, 0, 0])
    return header + b"".join(lines)


def test_definitions_route_labels_to_members() -> None:
    """A crafted definitions block lands each label in the right bucket."""
    sc = _module(b"\x01\x03", "SC LE2")
    lines = [
        _name_line(255, 3, 40, b"In 9"),  # input label → inputs[40-32]=inputs[8]
        _name_line(255, 0, 120, b"Flag 1"),  # flag → flags[].nmbr = 120-119 = 1
        _name_line(255, 5, 136, b"area"),  # module area = line[1] = 5
        _name_line(253, 0, 7, b"DirCmd"),  # direct command
        _name_line(254, 0, 3, b"Msg 1"),  # message
        _name_line(252, 0, 1, b"Alice"),  # finger id
    ]
    assert parse_definitions(sc, _names_response(lines)) is True
    assert sc.inputs[8].name == "In 9"
    flag = next(f for f in sc.flags if f.name == "Flag 1")
    assert flag.nmbr == 1
    assert sc.area == 5
    assert any(c.name == "DirCmd" for c in sc.dir_commands)
    assert any(m.name == "Msg 1" for m in sc.messages)
    assert any(i.name == "Alice" for i in sc.ids)
    # The SC analogue output (old outputs[15]) is promoted to a typed member.
    assert sc.analog_outputs[0].type == 8


# --------------------------------------------------------------------------- #
# Router parsing — global descriptions                                         #
# --------------------------------------------------------------------------- #


def _desc_line(content_code: int, entry_no: int, entry_name: bytes) -> bytes:
    """Build a global description line (FF xx record)."""
    header = bytearray(9)
    header[1] = content_code & 0xFF
    header[2] = (content_code >> 8) & 0xFF
    header[3] = entry_no
    header[8] = len(entry_name)
    return bytes(header) + entry_name


def _wrap_descriptions(lines: list[bytes]) -> bytes:
    """Wrap description lines in the get_descriptions framing."""
    header = bytes([len(lines) & 0xFF, (len(lines) >> 8) & 0xFF, 0, 0])
    return header + b"".join(lines)


def test_router_descriptions_parses_flags_commands_and_areas() -> None:
    """Each FF-record branch lands flags / collective cmds / areas / autostop."""
    rt = build_router(b_uid="ROUTER-1")
    lines = [
        _desc_line(767, 1, b"flag-1"),  # FF 02 → global flag
        _desc_line(1023, 4, b"All off"),  # FF 03 → collective command
        _desc_line(2815, 2, b"Kitchen"),  # FF 0A → area
        _desc_line(3071, 7, b"unused"),  # FF 0B → cover autostop delay
    ]
    parse_global_descriptions(rt, _wrap_descriptions(lines))
    assert any(f.name == "flag-1" for f in rt.flags)
    assert any(c.name == "All off" for c in rt.coll_commands)
    kitchen = next(a for a in rt.areas if a.nmbr == 2)
    assert kitchen.name == "Kitchen"
    assert rt.cover_autostop_del == 7


# --------------------------------------------------------------------------- #
# Router parsing — SMR definitions block                                       #
# --------------------------------------------------------------------------- #


def test_router_definitions_parse_smr_layout() -> None:
    """A SMR with channel/group/name layout fills the router fields."""
    rt = build_router(b_uid="ROUTER-1")
    smr = bytearray(b"\x00" * 256)
    # Channel 0: count=2, addrs [5, 6] → max_mod_no = 6
    smr[1] = 2
    smr[2] = 5
    smr[3] = 6
    # grp_cnt + groups
    smr[8] = 2
    smr[9] = 3
    smr[10] = 4
    smr[11] = 1
    smr[12] = 2
    smr[13] = 1
    # Router name @ ptr 14
    smr[14] = 4
    smr[15:19] = b"R-Hb"
    smr[19] = 3
    smr[20:23] = b"Bob"
    smr[23] = 3
    smr[24:27] = b"Sue"
    smr[27] = 5
    smr[28:33] = b"S/N-1"
    smr[-22:] = b"v1.0                  "
    parse_router_definitions(rt, bytes(smr))
    assert len(rt.module_grp) == 6
    assert rt.max_group == 4
    assert rt.name == "R-Hb"
    assert rt.user1_name == "Bob"
    assert rt.user2_name == "Sue"
    assert rt.serial == "S/N-1"
    assert rt.version == "v1.0"


# --------------------------------------------------------------------------- #
# Router parsing — status block                                                #
# --------------------------------------------------------------------------- #


def test_router_status_writes_flag_and_state_values() -> None:
    """FLAG_GLOB drives flag values; system/mirror bytes drive the states."""
    rt = build_router(b_uid="ROUTER-1")
    rt.flags = [Flag(name="flg", nmbr=1, idx=0, type=1, value=0)]
    status = bytearray(b"\x00" * 60)
    status[RoutIdx.FLAG_GLOB] = 0x01
    status[RoutIdx.ERR_SYSTEM] = FALSE_VAL
    status[RoutIdx.MIRROR_STARTED] = TRUE_VAL
    apply_router_status(rt, bytes(status))
    assert rt.flags[0].value == 1
    assert rt.sys_ok is True
    assert rt.mirror_started is True
    assert rt.states[0].value == 1
    assert rt.states[1].value == 1


# --------------------------------------------------------------------------- #
# Router parsing — module inventory + status distribution (end to end)         #
# --------------------------------------------------------------------------- #


def test_module_inventory_builds_known_modules_only() -> None:
    """The inventory factory builds known module types and skips the rest."""
    # raddr=5, type Smart Out 8/R, name "Out"
    resp = bytes([5]) + b"\x0a\x01" + bytes([3]) + b"Out"
    mods = parse_module_inventory(
        resp, b_uid="b1", router_id=100, module_grp=[0, 0, 0, 0, 7]
    )
    assert len(mods) == 1
    assert mods[0].addr == 105
    assert mods[0].group == 7
    assert mods[0].mod_type == "Smart Out 8/R"


def test_distribute_status_applies_block_to_addressed_module() -> None:
    """distribute_status routes each status block to its module by address."""
    rt = build_router(b_uid="ROUTER-1")
    out = build_module(uid="b1", addr=105, typ=b"\x0a\x01", name="Out", group=0)
    rt.modules = [out]
    block = _zero_status()
    block[MStatIdx.BYTE_COUNT] = MStatIdx.END  # full-length block, pass-through
    block[MStatIdx.ADDR] = 5  # raddr → addr 5 + 100 = 105
    block[MStatIdx.OUT_1_8] = 0x01  # output 0 on
    distribute_status(rt, bytes(block))
    assert out.outputs[0].is_on is True
