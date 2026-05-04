"""Constants for habitron client."""

from typing import Final


SMHUB_COMMANDS: Final[dict[str, str]] = {
    "GET_MODULES": "\x0a\1\2\x01\0\0\0",
    "GET_MODULE_SMG": "\x0a\2\7\x01<mod>\0\0",
    "GET_MODULE_SMC": "\x0a\3\7\x01<mod>\0\0",
    "GET_ROUTER_SMR": "\x0a\4\3\x01\0\0\0",
    "GET_ROUTER_STATUS": "\x0a\4\4\x01\0\0\0",
    "GET_ROUTER_FW_FILEVS": "\x0a\4\x0a\x01\0\0\0",
    "GET_MODULE_FW_FILEVS": "\x0a\5\x0a\x01<mod>\0\0",
    "GET_MODULE_STATUS": "\x0a\5\1\x01<mod>\0\0",
    "GET_COMPACT_STATUS": "\x0a\5\2\x01\xff\0\0",  # compact status of all modules (0xFF)
    "GET_SMHUB_BOOT_STATUS": "\x0a\6\1\1\0\0\0",
    "GET_SMHUB_INFO": "\x0a\6\2\1\0\0\0",
    "GET_SMHUB_UPDATE": "\x0a\6\3\1\0<len><vlen><vers>",
    "GET_GLOBAL_DESCRIPTIONS": "\x0a\7\1\x01\0\0\0",  # Flags, Command collections
    "GET_SMHUB_STATUS": "\x14\0\0\0\0\0\0",
    "GET_SMHUB_FIRMWARE": "\x14\x1e\0\0\0\0\0",
    "GET_GROUP_MODE": "\x14\2\1\x01<mod>\0\0",  # <Group 0..>
    "GET_GROUP_MODE0": "\x14\2\1\x01\0\0\0",
    "SET_GROUP_MODE": "\x14\2\2\x01<mod>\3\0\x01<mod><arg1>",  # <Group 0..><Mode>
    "GET_ROUTER_MODES": "\x14\2\3\x01<mod>\3\0\x01<mod>\0",
    "START_MIRROR": "\x14\x28\1\x01\0\0\0",
    "STOP_MIRROR": "\x14\x28\2\x01\0\0\0",
    "CHECK_COMM_STATUS": "\x14\x64\0\0\0\0\0",
    "SET_OUTPUT_ON": "\x1e\1\1\x01<mod>\3\0\x01<mod><arg1>",
    "SET_OUTPUT_OFF": "\x1e\1\2\x01<mod>\3\0\x01<mod><arg1>",
    "SET_DIMMER_VALUE": "\x1e\1\3\x01<mod>\4\0\x01<mod><arg1><arg2>",  # <Module><DimNo><DimVal>
    "SET_SHUTTER_POSITION": "\x1e\1\4\x01\0\5\0\x01<mod>\1<arg1><arg2>",  # <Module><RollNo><RolVal>
    "SET_BLIND_TILT": "\x1e\1\4\x01\0\5\0\x01<mod>\2<arg1><arg2>",
    "SET_SETPOINT_VALUE": "\x1e\2\1\x01\0\5\0\x01<mod><arg1><arg2><arg3>",  # <Module><ValNo><ValL><ValH>
    "CALL_DIR_COMMAND": "\x1e\5\1\x01<mod>\1\0<cno>",  # <CmdNo>
    "CALL_VIS_COMMAND": "\x1e\3\1\0\0\4\0\x01<mod><visl><vish>",  # <Module><VisNoL><VisNoH>
    "CALL_COLL_COMMAND": "\x1e\4\1\x01<cno>\0\0",  # <CmdNo>
    "READ_MODULE_MIRR_STATUS": "\x64\1\5\x01<mod>\0\0",  # <Module>
    "SET_FLAG_OFF": "\x1e\x0f\0\x01<mod>\1\0<fno>",
    "SET_FLAG_ON": "\x1e\x0f\1\x01<mod>\1\0<fno>",
    "COUNTR_UP": "\x1e\x10\2\x01<mod>\1\0<cno>",
    "COUNTR_DOWN": "\x1e\x10\3\x01<mod>\1\0<cno>",
    "COUNTR_VAL": "\x1e\x10\4\x01<mod>\2\0<cno><val>",
    "SET_RGB_OFF": "\x1e\x0c\x00\x01<mod>\1\0<lno>",
    "SET_RGB_ON": "\x1e\x0c\x01\x01<mod>\1\0<lno>",
    "SET_RGB_COL": "\x1e\x0c\x04\x01<mod>\4\0<lno><rd><gn><bl>",
    "SEND_MESSAGE": "\x1e\x11\3\x01<mod>\xff\xff<tim><msg>",
    "SEND_SMS": "\x1e\x11\x0b\x01<mod>\xff\xff<sms><msg>",
    "SET_CLIM_MODE": "\x1e\x13\x01\x01<mod>\2\0<cmode><ctl12>",
    "GET_LAST_IR_CODE": "\x32\2\1\x01<mod>\0\0",
    "REINIT_HUB": "\x3c\x00\x00\x01<opr>\0\0",
    "RESTART_HUB": "\x3c\x00\x02\x01\0\0\0",
    "REBOOT_HUB": "\x3c\x00\x03\0\0\0\0",
    "SEND_NETWORK_INFO": "\x3c\x00\x04\0\0<len><iplen><ipv4><toklen><tok><vlen><vers>",
    "SET_LOG_LEVEL": "\x3c\x00\x05<hdlr><lvl>\0\0",  # Set logging level of console/file handler
    "RESTART_FORWARD_TABLE": "\x3c\x01\x01\x01\0\0\0",  # Weiterleitungstabelle löschen und -automatik starten
    "GET_CURRENT_ERROR": "\x3c\x01\x02\x01\0\0\0",
    "GET_LAST_ERROR": "\x3c\x01\x03\x01\0\0\0",
    "REBOOT_ROUTER": "\x3c\x01\x04\x01\0\0\0",
    "POWER_UP_CHAN": "\x3c\x01\x06\x01<msk>\0\0",
    "POWER_DWN_CHAN": "\x3c\x01\x07\x01<msk>\0\0",
    "DO_FW_UPDATE": "\x3c\x01\x14\x01<mod>\0\0",
    "REBOOT_MODULE": "\x3c\x03\x01\x01<mod>\0\0",  # <Module> or 0xFF for all modules
    "SEND_MD_ID": "\x3c\x03\x09\x01<mod><len>\x00<id>",
}
