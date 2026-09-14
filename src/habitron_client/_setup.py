"""High-level orchestration: build and refresh the device model.

Wires the transport (:class:`HabitronClient`) to the parsing layer. Mirrors the
integration's ``HbtnRouter.initialize`` + ``HbtnComm.async_system_update``
without any Home Assistant dependency: the consumer drives setup once and then
polls :func:`async_refresh_system` from its coordinator.
"""

from __future__ import annotations

import logging

from ._models import apply_host_diagnostics, parse_smhub_info
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
from .exceptions import HabitronError, HabitronProtocolError
from .model import Router, SmartHub

_LOGGER = logging.getLogger(__name__)

# Minimum compact-status length to treat a poll as valid (matches integration).
_MIN_STATUS_LEN = 10

# A valid description answer always carries at least the 4-byte table header,
# even when the router holds no lists at all ("0 entries"). The hub replies with
# an empty payload when it could not read the descriptions from the router, so
# anything shorter means "unavailable" rather than "there are none".
_MIN_DESCRIPTIONS_LEN = 4


async def async_build_system(client: HabitronClient, *, b_uid: str) -> Router:
    """Connect's worth of reads → a fully-parsed :class:`Router` model.

    ``b_uid`` is the installation's base id (the SmartHub mac-derived id the
    consumer already holds); it seeds the router/module uids and the default
    member-name prefix.
    """
    router = build_router(b_uid=b_uid)

    # A flaky/rebooting hub can return truncated blocks mid-build; the
    # fixed-offset parsers would then raise IndexError. Convert that into a
    # protocol error so the consumer treats the whole build as transient and
    # retries (rather than failing setup permanently).
    try:
        parse_router_definitions(router, await client.get_smr())
        descriptions = await client.get_global_descriptions()
        if len(descriptions) < _MIN_DESCRIPTIONS_LEN:
            # Building with empty lists would drop every flag, collective
            # command and area entity. Fail the build instead, so the consumer
            # retries and keeps what it already has registered.
            raise HabitronProtocolError(
                "hub reports the router descriptions as unavailable"
            )
        parse_global_descriptions(router, descriptions)
        router.modules = parse_module_inventory(
            await client.get_router_modules(),
            b_uid=b_uid,
            module_grp=router.module_grp,
        )

        sys_status, _crc = await client.get_compact_status()
        for module in router.modules:
            name_prefix = f"Mod_{module.uid}_{b_uid}"
            parse_definitions(
                module,
                await client.get_module_definitions(module.addr),
                name_prefix=name_prefix,
            )
            parse_settings(module, await client.get_module_settings(module.addr))
            if module.hw_version:
                # The device identifier is the hardware version (as in the
                # integration); keep the inventory uid only as a fallback.
                module.uid = module.hw_version

        apply_router_status(router, await client.get_router_status())
        distribute_status(router, sys_status)
    except IndexError as exc:
        raise HabitronProtocolError(
            f"truncated hub response during system build: {exc}"
        ) from exc
    _LOGGER.debug(
        "built system %s: router=%r, %d modules (%s)",
        b_uid,
        router.name,
        len(router.modules),
        ", ".join(sorted({m.mod_type for m in router.modules})),
    )
    return router


async def async_refresh_system(
    client: HabitronClient, router: Router, *, last_crc: int | None = None
) -> int:
    """Poll the whole-bus status and update the model in place.

    Returns the compact-status CRC; pass it back as ``last_crc`` next time so an
    unchanged bus skips the module-status distribution (a full re-parse of every
    module that fires listeners). The router's *own* status — currents,
    voltages, channel timeouts, ``sys_ok`` and the mirror flag — is read on every
    poll regardless: it changes independently of the modules, so gating it on the
    module CRC used to leave those values (and the health repair) stale on an
    otherwise idle bus. We have already talked to the hub for the compact status,
    so the extra router read is cheap.
    """
    sys_status, crc = await client.get_compact_status()

    # Router telemetry is independent of the module compact status, so refresh
    # it every poll. Reading it unconditionally also lets the mirror-down (hub
    # reboot) edge be caught on a quiet bus, when no module change would trigger
    # a router read.
    was_started = router.mirror_started
    apply_router_status(router, await client.get_router_status())
    if was_started and not router.mirror_started:
        # The mirror went *down* between two polls — i.e. the hub rebooted.
        # Restart it so the event push resumes (the lightweight recovery the
        # pre-library integration used). Only act on this up->down edge: right
        # after setup the mirror is legitimately still coming up (reported "not
        # started" for a few seconds), and restarting it there breaks the hub's
        # own start-up sequence. A restart failure is non-fatal — the hub usually
        # brings the mirror back on its own, and the next poll retries the edge.
        _LOGGER.warning("router mirror stopped (hub reboot) — restarting it")
        try:
            await client.start_mirror()
        except HabitronError as err:
            _LOGGER.warning("mirror restart failed (will retry next poll): %s", err)

    # Distributing the compact status re-parses every module and fires their
    # listeners, so keep skipping it while the bus is byte-stable.
    if crc != last_crc and sys_status and len(sys_status) >= _MIN_STATUS_LEN:
        _LOGGER.debug("refresh: module status changed (crc %s -> %s)", last_crc, crc)
        distribute_status(router, sys_status)
    else:
        _LOGGER.debug("refresh: module status unchanged (crc %s)", crc)
    return crc


async def async_build_hub(client: HabitronClient) -> SmartHub:
    """One read's worth → a :class:`SmartHub` describing the hub itself.

    Companion to :func:`async_build_system`, which builds everything *behind*
    the hub. Kept separate on purpose: the two answer different queries, and a
    consumer that registers the hub as its own device wants it before it starts
    the much longer bus build -- so a hub that answers but whose bus is still
    coming up can already be shown.
    """
    hub = parse_smhub_info(await client.get_smhub_info())
    _LOGGER.debug(
        "built hub %s: platform=%r, version=%r, %d host readings",
        hub.lan_mac or "<no lan mac>",
        hub.platform,
        hub.version,
        len(hub.host_members),
    )
    return hub


async def async_refresh_hub(
    client: HabitronClient, hub: SmartHub, *, hbtn_version: str
) -> None:
    """Poll the hub's host readings and update the model in place.

    Fires the per-member listeners for everything that changed, exactly as
    :func:`async_refresh_system` does for the bus. There is nothing to return:
    the hub has no status CRC to gate on, and its readings move on almost every
    poll anyway.

    A platform that reports no host readings is skipped without a wire round
    trip. Errors are raised, not swallowed -- how a failed host poll should
    affect the rest of a consumer's update cycle is the consumer's call.
    """
    if not hub.host_members:
        return
    apply_host_diagnostics(hub, await client.get_host_diagnostics(hbtn_version))
