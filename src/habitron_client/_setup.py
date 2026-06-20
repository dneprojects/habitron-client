"""High-level orchestration: build and refresh the device model.

Wires the transport (:class:`HabitronClient`) to the parsing layer. Mirrors the
integration's ``HbtnRouter.initialize`` + ``HbtnComm.async_system_update``
without any Home Assistant dependency: the consumer drives setup once and then
polls :func:`async_refresh_system` from its coordinator.
"""

from __future__ import annotations

from ._parse import parse_definitions, parse_settings
from ._parse_router import (
    apply_router_status,
    build_router,
    distribute_status,
    parse_global_descriptions,
    parse_module_inventory,
    parse_router_definitions,
)
from .client import HabitronClient
from .model import Router

# Minimum compact-status length to treat a poll as valid (matches integration).
_MIN_STATUS_LEN = 10


async def async_build_system(client: HabitronClient, *, b_uid: str) -> Router:
    """Connect's worth of reads → a fully-parsed :class:`Router` model.

    ``b_uid`` is the installation's base id (the SmartHub mac-derived id the
    consumer already holds); it seeds the router/module uids and the default
    member-name prefix.
    """
    router = build_router(b_uid=b_uid)

    parse_router_definitions(router, await client.get_smr())
    parse_global_descriptions(router, await client.get_global_descriptions())
    router.modules = parse_module_inventory(
        await client.get_router_modules(),
        b_uid=b_uid,
        router_id=router.id,
        module_grp=router.module_grp,
    )

    sys_status, _crc = await client.get_compact_status()
    for module in router.modules:
        raddr = module.addr - router.id
        name_prefix = f"Mod_{module.uid}_{b_uid}"
        parse_definitions(
            module, await client.get_module_definitions(raddr), name_prefix=name_prefix
        )
        parse_settings(module, await client.get_module_settings(raddr))
        if module.hw_version:
            # The device identifier is the hardware version (as in the
            # integration); keep the inventory uid only as a fallback.
            module.uid = module.hw_version

    apply_router_status(router, await client.get_router_status())
    distribute_status(router, sys_status)
    return router


async def async_refresh_system(
    client: HabitronClient, router: Router, *, last_crc: int | None = None
) -> int:
    """Poll the compact status and update the model in place.

    Returns the status CRC; pass it back as ``last_crc`` next time so an
    unchanged bus state skips the router-status read and distribution.
    """
    sys_status, crc = await client.get_compact_status()
    if crc != last_crc and sys_status and len(sys_status) >= _MIN_STATUS_LEN:
        apply_router_status(router, await client.get_router_status())
        distribute_status(router, sys_status)
    return crc
