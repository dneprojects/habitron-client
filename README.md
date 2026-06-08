# Habitron Client

An asynchronous, fully typed API client for the Habitron SmartHub, designed for
integration with Home Assistant.

## Features

- Non-blocking TCP communication via `asyncio` `StreamReader`/`StreamWriter`.
- Persistent, lock-serialised connection with automatic reconnect on errors.
- Automatic CRC16 calculation and command wrapping.
- High-level coroutines for outputs, dimmers, RGB, shutters, climate and more.
- Safe YAML parsing (`yaml.safe_load`) into validated `TypedDict` models.
- Async UDP discovery of SmartHubs on the local network.
- Typed exception hierarchy and a `py.typed` marker (PEP 561 compliant).

## Requirements

- Python 3.11+

## Installation

```bash
pip install habitron-client
```

## Usage

The client is async-only and is used as an async context manager:

```python
import asyncio

from habitron_client import HabitronClient, HabitronError


async def main() -> None:
    async with HabitronClient("192.0.2.10") as client:
        info = await client.get_smhub_info()
        print(info["software"]["version"])

        await client.set_output(mod_addr=1, nmbr=2, val=True)


asyncio.run(main())
```

### Error handling

All failures raise a typed exception:

```text
HabitronError                 (root)
├── HabitronConnectionError   (refused / EOF / socket lost)
├── HabitronTimeoutError      (no response within the deadline)
└── HabitronProtocolError
    ├── HabitronChecksumError (CRC mismatch)
    └── HabitronBusError      (SmartHub reported an error)
```

### Discovery

```python
from habitron_client import discover_smarthubs

hubs = await discover_smarthubs()
```

## Development

```bash
pip install -e ".[dev]"
ruff check .
ruff format --check .
mypy --strict src/habitron_client
pytest
```
