"""Parse the Habitron router / SMR bytes into the model.

Ports the protocol-parsing parts of the integration's ``router.py`` — the SMR
definition block, the module inventory + factory dispatch, the global
descriptions (areas/flags/collective commands) and the router-status parse plus
the compact-status distribution to modules. The Home-Assistant-only concerns
(device/issue registry, coordinator, mirror restart) stay in the integration.
"""

from __future__ import annotations

import logging

from ._indices import (
    FALSE_VAL,
    MODULE_CODES,
    TRUE_VAL,
    MStatIdx,
    RoutIdx,
)
from ._parse import _module_kind, _set, apply_status, build_module
from .model import Area, Diagnostic, Flag, HbtnCommand, Module, Router

_LOGGER = logging.getLogger(__name__)
_TYPE_DIAG = 10  # diagnostic entity, hidden by default


def build_router(*, b_uid: str) -> Router:
    """Create a router with its fixed diagnostic / state members populated."""
    return Router(
        uid=f"rt_{b_uid}",
        id=100,
        name=f"Router {b_uid}",
        chan_timeouts=[
            Diagnostic(name=f"Timeouts channel {i + 1}", nmbr=i, type=_TYPE_DIAG)
            for i in range(4)
        ],
        chan_currents=[
            Diagnostic(name=f"Current channel {i + 1}", nmbr=i, type=_TYPE_DIAG)
            for i in range(8)
        ],
        voltages=[
            Diagnostic(name="Voltage 5V", nmbr=0, type=_TYPE_DIAG),
            Diagnostic(name="Voltage 24V", nmbr=1, type=_TYPE_DIAG),
        ],
        states=[
            Flag(name="System OK", nmbr=0, idx=0, type=0, value=1),
            Flag(name="Mirror started", nmbr=1, idx=1, type=_TYPE_DIAG, value=1),
        ],
    )


def parse_router_definitions(router: Router, smr: bytes) -> None:
    """Fill the router's SMR-derived fields (mirrors ``get_definitions``)."""
    ptr = 1
    max_mod_no = 0
    router.chan_list = []
    for _ch_i in range(4):
        count = smr[ptr]
        chan = sorted(smr[ptr + 1 : ptr + count + 1])
        router.chan_list.append(chan)
        if count > 0:
            max_mod_no = max([max_mod_no, *chan])
        ptr += 1 + count
    ptr += 2
    grp_cnt = smr[ptr - 1]
    router.max_group = max(list(smr[ptr : ptr + grp_cnt]))
    router.module_grp = [int(smr[ptr + mod_i]) for mod_i in range(max_mod_no)]
    ptr += 2 * grp_cnt + 1  # groups, group dependencies, timeout

    str_len = smr[ptr]
    router.name = smr[ptr + 1 : ptr + 1 + str_len].decode("iso8859-1").strip()
    ptr += str_len + 1
    str_len = smr[ptr]
    router.user1_name = smr[ptr + 1 : ptr + 1 + str_len].decode("iso8859-1").strip()
    ptr += str_len + 1
    str_len = smr[ptr]
    router.user2_name = smr[ptr + 1 : ptr + 1 + str_len].decode("iso8859-1").strip()
    ptr += str_len + 1
    str_len = smr[ptr]
    router.serial = smr[ptr + 1 : ptr + 1 + str_len].decode("iso8859-1").strip()
    ptr += str_len + 71  # manual correction, matches the integration
    router.version = smr[-22:].decode("iso8859-1").strip()


def parse_module_inventory(
    resp: bytes, *, b_uid: str, router_id: int, module_grp: list[int]
) -> list[Module]:
    """Build (empty) modules from the router's module inventory.

    Mirrors ``get_modules`` + the factory in ``initialize``: only modules with a
    known, instantiable type are returned (others are skipped, as the
    integration does). The caller fills names/values via the module parsers.
    """
    modules: list[Module] = []
    mod_string = resp.decode("iso8859-1")
    while len(resp) > 0:
        raddr = resp[0]
        mod_typ = resp[1:3]
        name_len = int(resp[3])
        mod_name = mod_string[4 : 4 + name_len]
        if mod_typ in MODULE_CODES and _module_kind(mod_typ) != "generic":
            _LOGGER.debug(
                "inventory: raddr=%s type=%s name=%r",
                raddr,
                MODULE_CODES[mod_typ],
                mod_name,
            )
            modules.append(
                build_module(
                    uid=f"{b_uid}{raddr}",
                    addr=raddr + router_id,
                    typ=mod_typ,
                    name=mod_name,
                    group=module_grp[raddr - 1],
                )
            )
        else:
            _LOGGER.debug(
                "inventory: skipping raddr=%s type=%s (unknown/generic)",
                raddr,
                mod_typ.hex(),
            )
        mod_string = mod_string[4 + name_len : len(resp)]
        resp = resp[4 + name_len :]
    return modules


def parse_global_descriptions(router: Router, resp: bytes) -> None:
    """Fill router flags, collective commands, areas (``get_descriptions``)."""
    no_lines = int.from_bytes(resp[:2], "little")
    resp = resp[4:]
    for _ in range(no_lines):
        if resp == b"":
            break
        line_len = int(resp[8]) + 9
        line = resp[:line_len]
        content_code = int.from_bytes(line[1:3], "little")
        entry_no = int(line[3])
        entry_name = line[9:line_len].decode("iso8859-1").strip()
        if content_code == 767:  # FF 02: global flags (Merker)
            router.flags.append(
                Flag(name=entry_name, nmbr=entry_no, idx=len(router.flags), value=0)
            )
        elif content_code == 1023:  # FF 03: collective commands (Sammelbefehle)
            router.coll_commands.append(HbtnCommand(name=entry_name, nmbr=entry_no))
        elif int(line[2]) == 7 or content_code == 2303:  # group name
            pass
        elif content_code == 2815:  # FF 0A: areas
            router.areas.append(Area(nmbr=entry_no, name=entry_name))
        elif content_code == 3071:  # FF 0B: cover autostop counter
            router.cover_autostop_del = entry_no
        else:
            _LOGGER.warning(
                "Unexpected description, code: %s %s %s",
                line[1],
                line[2],
                line[3],
            )
        resp = resp[line_len:]


def apply_router_status(router: Router, status: bytes) -> None:
    """Parse the router status block (mode, flags, currents, voltages, health)."""
    if len(status) < RoutIdx.MIRROR_STARTED:
        _LOGGER.warning("Router status too short, length: %s", len(status))
        return
    _set(router.mode, "value", int(status[RoutIdx.MODE0]))

    flags_state = int.from_bytes(
        status[RoutIdx.FLAG_GLOB : RoutIdx.FLAG_GLOB + 2], "little"
    )
    for flg in router.flags:
        _set(flg, "value", int(bool(flags_state & (0x01 << (flg.nmbr - 1)))))

    for time_out in router.chan_timeouts:
        _set(time_out, "value", status[RoutIdx.TIME_OUT + time_out.nmbr])
    for curr in router.chan_currents:
        idx = RoutIdx.CURRENTS + curr.nmbr * 2
        _set(curr, "value", int.from_bytes(status[idx : idx + 2], "little") / 1000)

    _set(
        router.voltages[0],
        "value",
        int.from_bytes(status[RoutIdx.VOLTAGE_5 : RoutIdx.VOLTAGE_5 + 2], "little")
        / 10,
    )
    _set(
        router.voltages[1],
        "value",
        int.from_bytes(status[RoutIdx.VOLTAGE_24 : RoutIdx.VOLTAGE_24 + 2], "little")
        / 10,
    )

    prev_mirror = router.mirror_started
    prev_rebooted = router.rebooted
    router.sys_ok = status[RoutIdx.ERR_SYSTEM] == FALSE_VAL
    router.mirror_started = status[RoutIdx.MIRROR_STARTED] == TRUE_VAL
    router.rebooted = int(status[RoutIdx.REBOOTED]) != 0
    if prev_mirror and not router.mirror_started:
        _LOGGER.warning(
            "router mirror stopped (hub reboot, rebooted-flag=%s)", router.rebooted
        )
    elif not prev_mirror and router.mirror_started:
        _LOGGER.info("router mirror (re)started")
    if router.rebooted and not prev_rebooted:
        _LOGGER.debug("router reports a reboot since last poll")
    if router.states:
        _set(router.states[0], "value", int(router.sys_ok))
        _set(router.states[1], "value", int(router.mirror_started))


def pad_sys_status(sys_status: bytes) -> bytes:
    """Zero-pad each compact-status block up to ``MStatIdx.END`` bytes.

    The SmartHub may still send the legacy 92-byte block (no RGB); pad shorter
    blocks so a fixed block size can be assumed downstream.
    """
    if not sys_status:
        return sys_status
    blk_len = sys_status[MStatIdx.BYTE_COUNT]
    if blk_len == 0 or len(sys_status) % blk_len != 0:
        return sys_status  # unknown layout -> pass through
    if blk_len >= MStatIdx.END:
        return sys_status  # already at (or beyond) target length
    no_mods = len(sys_status) // blk_len
    pad = b"\x00" * (MStatIdx.END - blk_len)
    return b"".join(
        sys_status[i * blk_len : (i + 1) * blk_len] + pad for i in range(no_mods)
    )


def distribute_status(router: Router, sys_status: bytes) -> None:
    """Slice the padded system status and apply each block to its module."""
    padded = pad_sys_status(sys_status)
    by_addr = {module.addr: module for module in router.modules}
    block_len = MStatIdx.END
    no_mods = len(padded) // block_len
    for m_idx in range(no_mods):
        block = padded[m_idx * block_len : (m_idx + 1) * block_len]
        if not block:
            continue
        mod_addr = block[MStatIdx.ADDR] + router.id
        module = by_addr.get(mod_addr)
        if module is not None:
            apply_status(module, block)
        else:
            _LOGGER.debug("status block for unknown addr %s ignored", mod_addr)
