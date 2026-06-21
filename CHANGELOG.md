# Changelog

## 2.0.2 — 2026-06-21

### Fixed
- Hub-reboot recovery: `async_refresh_system` now restarts the router mirror
  when it finds it stopped (the lightweight, self-healing behaviour of the
  pre-library integration), so events resume after a SmartHub reboot without a
  config-entry reload.
- Flaky/rebooting hub at setup: `async_build_system` wraps the build and
  `parse_settings` guards its length, raising `HabitronProtocolError` on
  truncated blocks instead of `IndexError`, so the consumer can retry.
- Smart Controller analog-output backing slot is hidden (`type = -10`) so it is
  no longer exposed as an extra switchable output alongside its number entity.

### Added
- `Router.rebooted` and reboot diagnostics: `apply_router_status` logs a warning
  when the router mirror stops (hub reboot) and the mirror (re)start, reads the
  hub's reboot flag, and the transport logs connection open/established. This
  makes a hub-reboot recovery observable (enable with
  `logger: habitron_client: debug`).
- Real-hardware-derived tests covering the full event set (button, switch,
  output, cover, blind, dimmer, flag, mode) and a startup/autodetect replay that
  pins the parsed module line-up and feature detection against real bus data.

## 2.0.1 — 2026-06-21

### Fixed
- Smart Controller Mini colour LEDs now read their on/off state **and** colour
  from the status RGB mask (`RGB_MASK`), the same path the Smart Touch already
  used — instead of the module's output-status bits. The colour-LED status
  handling is now unified across all modules (no per-module special-casing), so
  the mirror/poll keeps colour LEDs in sync independently of the output events.

### Added
- Debug logging across the orchestration / parsing / event layers (enable with
  `logger: habitron_client: debug`): system build summary and per-refresh
  outcome (`_setup`), module inventory incl. skipped/unknown types and unrouted
  status blocks (`_parse_router`), one line per applied push event plus a log
  for unhandled event types (`_events`), and colour-LED state changes from the
  status (`_parse`). All at DEBUG, change-/event-driven (no per-poll spam).

## 2.0.0 — 2026-06-20

### Added
- Typed device model (`model.py`): `BusMember` base + per-member dataclasses
  (`Input`, `Output`, `Dimmer`, `Cover`, `Sensor`, `Led`, `ColorLed`, `Logic`,
  `Flag`, `SetValue`, `Finger`, `HbtnCommand`, `Diagnostic`) and
  `Module`/`SmartController`/`Router`/`Area`, with per-member change listeners
  (`add_listener`/`remove_listener`/`notify`). No Home Assistant dependency.
- Full protocol parsing moved out of the integration into the library: module
  member build + compact-status parsing, definitions/label parsing, settings
  parsing (versions, input typing, cover detection) and the router layer (SMR,
  module inventory + factory, global descriptions, router status, compact-status
  distribution).
- High-level API: `async_build_system(client, *, b_uid)`,
  `async_refresh_system(client, router, *, last_crc)` and
  `apply_event(router, mod_id, evnt, *args)`.

### Changed
- The library now owns the device model and parsing; consumers read typed
  members and subscribe to per-member notifications instead of parsing raw
  bytes. The transport API is unchanged.

## 1.0.4 — 2026-06-12

### Added
- `send_message_text(mod_addr, text)`: show a free-text message on a module's
  display (command 30/17, action 1); an empty text clears it (action 0).
  Text is ISO 8859-1 encoded, at most 32 characters, sent fire-and-forget.
  Requires module firmware with free-text message support (in development).

## 1.0.3 — 2026-06-11

### Tests
- Cover the remaining discovery error paths (`discover_smarthubs` socket
  failure, deadline break and response collection; `query_smarthub`
  unresolvable host, invalid descriptor and reverse-DNS failure;
  `test_connection` success and not-OK paths).
- Cover `_require_paths` validation branches (non-mapping intermediate,
  missing leaf key) and the `BusConnection` async-context-manager path.
- Test suite now reaches **100 % line coverage** across all modules
  (was 95 %).

## 1.0.2 — 2026-06-09

### Changed
- Minimum Python version raised to 3.14 (aligned with Home Assistant ≥ 2026.3).
- CI matrix reduced to Python 3.14 only.

## 1.0.1 — 2026-06-09

### Changed
- Release workflow: tests must pass on all supported Python versions before
  PyPI upload (OIDC Trusted Publishing via GitHub Actions).

### Fixed
- CHANGELOG: confirmed short-acknowledgement behaviour — was previously noted
  as "inferred", now verified against real SmartHub hardware.

## 1.0.0 — 2026-06-08

Review fixes on top of the async migration.

### Changed
- **`async with` is now enforced and connects eagerly.** Issuing a command on a
  client that was never entered as a context manager (nor `connect()`-ed) raises
  `HabitronConnectionError` instead of silently opening a connection that leaks.
  `__aenter__` opens the connection eagerly, so an unreachable hub raises on
  enter rather than on the first request; `__aexit__` always closes.
- **Retries are now at-most-once by default** (`max_attempts=1`). The previous
  hard-coded 2-attempt retry could execute a non-idempotent command (e.g.
  `inc_dec_counter`) twice when only the response was lost. `max_attempts` is
  now a validated constructor parameter (`>= 1`, else `ValueError`); retries
  are opt-in and only safe for idempotent reads.
- `socket.gaierror` (DNS) and UDP discovery-socket `OSError`s are wrapped in
  `HabitronConnectionError`, so `except HabitronError` catches them.

### Removed
- `HabitronChecksumError` — it was never raised (the library does not validate
  CRC internally). Can return if in-library CRC validation is added.

### Verified
- Tested end-to-end against real SmartHub hardware (test instance with router
  + multiple modules) covering: connection lifecycle, read path (smhub_info,
  topology, module status — 59 consecutive round-trips on a persistent
  connection), write path (LED toggle on a module with visual + bus-state
  read-back verification), and external bus events (manual button press
  correctly reflected in module state).
- Verified on Python 3.11, 3.12, 3.13, 3.14 (local 3.14 run + CI matrix).

## 1.0.0-rc1

First fully asynchronous, strictly typed release. **Breaking**: the synchronous
API was removed without replacement (path A); consumers must migrate to the
async client.

### Changed
- `HabitronClient` is now async-only and used as `async with HabitronClient(...)`.
  All bus methods are coroutines backed by `asyncio` `StreamReader`/`StreamWriter`
  (true non-blocking I/O, no executor threads).
- A single persistent connection per client, serialised by a lock, with a
  central reconnect-once strategy on connection loss.
- Command templates are typed `Command` values; arguments are `int | bytes`.
- YAML responses are parsed with `yaml.safe_load` and validated against
  `TypedDict` models.
- `send_network_info` separates the pure `_scramble_token` logic from I/O.
- Network discovery and DNS resolution are now async.

### Added
- Typed exception hierarchy: `HabitronError` → `HabitronConnectionError`,
  `HabitronTimeoutError`, `HabitronProtocolError` (→ `HabitronBusError`).
- `py.typed` marker — the package is now PEP 561 compliant.
- Async bus-simulator test suite (96% coverage) and a CI workflow running
  `ruff`, `ruff format --check`, `mypy --strict` and `pytest --cov`.

### Removed
- The synchronous `*_sync` methods, the `b""`/`b"OK"` sentinel returns and the
  `SMHUB_COMMANDS` string table.

### Notes
- The short-acknowledgement handling (a sub-header response is treated as the
  hub closing the connection) has been confirmed against a real SmartHub:
  `b'OK'` arrives in ~4 ms via the `IncompleteReadError.partial` path.
