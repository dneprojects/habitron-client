"""Typed command templates for the Habitron SmartHub protocol.

Each :class:`Command` pairs a raw byte template with the ordered tuple of
placeholder names it contains. Placeholders are written as ``<name>`` inside the
template and substituted positionally by :func:`habitron_client._protocol.build_frame`.

The byte templates are a 1:1 transcription of the historical ``SMHUB_COMMANDS``
string table; do not change the wire bytes here as part of the async migration.
"""

from __future__ import annotations

from typing import Final, NamedTuple


class Command(NamedTuple):
    """A SmartHub command template.

    Attributes:
        template: Raw command bytes with ``<name>`` placeholders.
        placeholders: Placeholder names in the order arguments must be supplied.
    """

    template: bytes
    placeholders: tuple[str, ...]


GET_MODULES: Final = Command(b"\x0a\x01\x02\x01\x00\x00\x00", ())
GET_MODULE_SMG: Final = Command(b"\x0a\x02\x07\x01<mod>\x00\x00", ("mod",))
GET_MODULE_SMC: Final = Command(b"\x0a\x03\x07\x01<mod>\x00\x00", ("mod",))
GET_ROUTER_SMR: Final = Command(b"\x0a\x04\x03\x01\x00\x00\x00", ())
GET_ROUTER_STATUS: Final = Command(b"\x0a\x04\x04\x01\x00\x00\x00", ())
GET_ROUTER_FW_FILEVS: Final = Command(b"\x0a\x04\x0a\x01\x00\x00\x00", ())
GET_MODULE_FW_FILEVS: Final = Command(b"\x0a\x05\x0a\x01<mod>\x00\x00", ("mod",))
GET_MODULE_STATUS: Final = Command(b"\x0a\x05\x01\x01<mod>\x00\x00", ("mod",))
GET_COMPACT_STATUS: Final = Command(b"\x0a\x05\x02\x01\xff\x00\x00", ())
GET_SMHUB_BOOT_STATUS: Final = Command(b"\x0a\x06\x01\x01\x00\x00\x00", ())
GET_SMHUB_INFO: Final = Command(b"\x0a\x06\x02\x01\x00\x00\x00", ())
GET_SMHUB_UPDATE: Final = Command(
    b"\x0a\x06\x03\x01\x00<len><vlen><vers>", ("len", "vlen", "vers")
)
GET_GLOBAL_DESCRIPTIONS: Final = Command(b"\x0a\x07\x01\x01\x00\x00\x00", ())
GET_SMHUB_STATUS: Final = Command(b"\x14\x00\x00\x00\x00\x00\x00", ())
GET_SMHUB_FIRMWARE: Final = Command(b"\x14\x1e\x00\x00\x00\x00\x00", ())
GET_GROUP_MODE: Final = Command(b"\x14\x02\x01\x01<mod>\x00\x00", ("mod",))
GET_GROUP_MODE0: Final = Command(b"\x14\x02\x01\x01\x00\x00\x00", ())
SET_GROUP_MODE: Final = Command(
    b"\x14\x02\x02\x01<mod>\x03\x00\x01<mod><arg1>", ("mod", "arg1")
)
GET_ROUTER_MODES: Final = Command(
    b"\x14\x02\x03\x01<mod>\x03\x00\x01<mod>\x00", ("mod",)
)
START_MIRROR: Final = Command(b"\x14\x28\x01\x01\x00\x00\x00", ())
STOP_MIRROR: Final = Command(b"\x14\x28\x02\x01\x00\x00\x00", ())
CHECK_COMM_STATUS: Final = Command(b"\x14\x64\x00\x00\x00\x00\x00", ())
SET_OUTPUT_ON: Final = Command(
    b"\x1e\x01\x01\x01<mod>\x03\x00\x01<mod><arg1>", ("mod", "arg1")
)
SET_OUTPUT_OFF: Final = Command(
    b"\x1e\x01\x02\x01<mod>\x03\x00\x01<mod><arg1>", ("mod", "arg1")
)
SET_DIMMER_VALUE: Final = Command(
    b"\x1e\x01\x03\x01<mod>\x04\x00\x01<mod><arg1><arg2>", ("mod", "arg1", "arg2")
)
SET_SHUTTER_POSITION: Final = Command(
    b"\x1e\x01\x04\x01\x00\x05\x00\x01<mod>\x01<arg1><arg2>", ("mod", "arg1", "arg2")
)
SET_BLIND_TILT: Final = Command(
    b"\x1e\x01\x04\x01\x00\x05\x00\x01<mod>\x02<arg1><arg2>", ("mod", "arg1", "arg2")
)
SET_SETPOINT_VALUE: Final = Command(
    b"\x1e\x02\x01\x01\x00\x05\x00\x01<mod><arg1><arg2><arg3>",
    ("mod", "arg1", "arg2", "arg3"),
)
CALL_DIR_COMMAND: Final = Command(b"\x1e\x05\x01\x01<mod>\x01\x00<cno>", ("mod", "cno"))
CALL_VIS_COMMAND: Final = Command(
    b"\x1e\x03\x01\x00\x00\x04\x00\x01<mod><visl><vish>", ("mod", "visl", "vish")
)
CALL_COLL_COMMAND: Final = Command(b"\x1e\x04\x01\x01<cno>\x00\x00", ("cno",))
READ_MODULE_MIRR_STATUS: Final = Command(b"\x64\x01\x05\x01<mod>\x00\x00", ("mod",))
SET_FLAG_OFF: Final = Command(b"\x1e\x0f\x00\x01<mod>\x01\x00<fno>", ("mod", "fno"))
SET_FLAG_ON: Final = Command(b"\x1e\x0f\x01\x01<mod>\x01\x00<fno>", ("mod", "fno"))
COUNTR_UP: Final = Command(b"\x1e\x10\x02\x01<mod>\x01\x00<cno>", ("mod", "cno"))
COUNTR_DOWN: Final = Command(b"\x1e\x10\x03\x01<mod>\x01\x00<cno>", ("mod", "cno"))
COUNTR_VAL: Final = Command(
    b"\x1e\x10\x04\x01<mod>\x02\x00<cno><val>", ("mod", "cno", "val")
)
SET_RGB_OFF: Final = Command(b"\x1e\x0c\x00\x01<mod>\x01\x00<lno>", ("mod", "lno"))
SET_RGB_ON: Final = Command(b"\x1e\x0c\x01\x01<mod>\x01\x00<lno>", ("mod", "lno"))
SET_RGB_COL: Final = Command(
    b"\x1e\x0c\x04\x01<mod>\x04\x00<lno><rd><gn><bl>",
    ("mod", "lno", "rd", "gn", "bl"),
)
SEND_MESSAGE: Final = Command(
    b"\x1e\x11\x03\x01<mod>\xff\xff<tim><msg>", ("mod", "tim", "msg")
)
SEND_SMS: Final = Command(
    b"\x1e\x11\x0b\x01<mod>\xff\xff<sms><msg>", ("mod", "sms", "msg")
)
SET_MESSAGE_TEXT: Final = Command(
    b"\x1e\x11\x01\x01<mod><len>\x00<msg>", ("mod", "len", "msg")
)
RESET_MESSAGE_TEXT: Final = Command(b"\x1e\x11\x00\x01<mod>\x00\x00", ("mod",))
SET_CLIM_MODE: Final = Command(
    b"\x1e\x13\x01\x01<mod>\x02\x00<cmode><ctl12>", ("mod", "cmode", "ctl12")
)
GET_LAST_IR_CODE: Final = Command(b"\x32\x02\x01\x01<mod>\x00\x00", ("mod",))
REINIT_HUB: Final = Command(b"\x3c\x00\x00\x01<opr>\x00\x00", ("opr",))
RESTART_HUB: Final = Command(b"\x3c\x00\x02\x01\x00\x00\x00", ())
REBOOT_HUB: Final = Command(b"\x3c\x00\x03\x00\x00\x00\x00", ())
SEND_NETWORK_INFO: Final = Command(
    b"\x3c\x00\x04\x00\x00<len><iplen><ipv4><toklen><tok><vlen><vers>",
    ("len", "iplen", "ipv4", "toklen", "tok", "vlen", "vers"),
)
SET_LOG_LEVEL: Final = Command(b"\x3c\x00\x05<hdlr><lvl>\x00\x00", ("hdlr", "lvl"))
RESTART_FORWARD_TABLE: Final = Command(b"\x3c\x01\x01\x01\x00\x00\x00", ())
GET_CURRENT_ERROR: Final = Command(b"\x3c\x01\x02\x01\x00\x00\x00", ())
GET_LAST_ERROR: Final = Command(b"\x3c\x01\x03\x01\x00\x00\x00", ())
REBOOT_ROUTER: Final = Command(b"\x3c\x01\x04\x01\x00\x00\x00", ())
POWER_UP_CHAN: Final = Command(b"\x3c\x01\x06\x01<msk>\x00\x00", ("msk",))
POWER_DWN_CHAN: Final = Command(b"\x3c\x01\x07\x01<msk>\x00\x00", ("msk",))
DO_FW_UPDATE: Final = Command(b"\x3c\x01\x14\x01<mod>\x00\x00", ("mod",))
REBOOT_MODULE: Final = Command(b"\x3c\x03\x01\x01<mod>\x00\x00", ("mod",))
SEND_MD_ID: Final = Command(b"\x3c\x03\x09\x01<mod><len>\x00<id>", ("mod", "len", "id"))
