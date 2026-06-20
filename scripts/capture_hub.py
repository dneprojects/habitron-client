#!/usr/bin/env python3
"""Record a real SmartHub's wire responses for replay-based tests.

LOCAL-ONLY: the recording contains your site-specific names (rooms, modules,
flags). It is written under ``scripts/captures/`` which is git-ignored — never
commit or publish it. Hand the file to the developer (or run the replay tests
locally) to validate the v2 parser against your real installation.

Usage (with the local library on the path)::

    cd /workspaces/habitron-client
    PYTHONPATH=src python scripts/capture_hub.py <hub-ip> [refresh-cycles]

It wraps :class:`HabitronClient`, drives :func:`async_build_system` plus a few
:func:`async_refresh_system` cycles, and logs every bus call + response in order
to ``scripts/captures/build_recording.json``. Nothing is changed on the hub —
only read commands are issued.
"""

from __future__ import annotations

import asyncio
import base64
import json
import pathlib
import sys
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from habitron_client import HabitronClient
from habitron_client._setup import (
    async_build_system,
    async_refresh_system,
)

# Read-only client methods that async_build_system / async_refresh_system call.
_RECORDED = (
    "get_smr",
    "get_global_descriptions",
    "get_router_modules",
    "get_compact_status",
    "get_router_status",
    "get_module_definitions",
    "get_module_settings",
)


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


class RecordingClient:
    """Delegates to a real client and logs every recorded call in order."""

    def __init__(self, inner: HabitronClient) -> None:
        self._inner = inner
        self.calls: list[dict[str, Any]] = []

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._inner, name)
        if name not in _RECORDED:
            return attr

        async def _wrapped(*args: Any) -> Any:
            result = await attr(*args)
            entry: dict[str, Any] = {"method": name, "args": list(args)}
            if isinstance(result, tuple):  # (bytes, crc)
                payload, crc = result
                entry["kind"] = "bytes_crc"
                entry["bytes_b64"] = _b64(payload)
                entry["crc"] = crc
            else:
                entry["kind"] = "bytes"
                entry["bytes_b64"] = _b64(result)
            self.calls.append(entry)
            return result

        return _wrapped


async def main(host: str, cycles: int) -> dict[str, Any]:
    async with HabitronClient(host) as real:
        info = await real.get_smhub_info()
        mac = info.get("hardware", {}).get("network", {}).get("lan mac", "capture")
        b_uid = str(mac).replace(":", "")[-6:] or "capture"

        rec = RecordingClient(real)
        print(f"Building system (b_uid={b_uid}) ...")
        router = await async_build_system(rec, b_uid=b_uid)  # type: ignore[arg-type]
        print(f"  modules: {len(router.modules)}")

        last_crc: int | None = None
        for i in range(cycles):
            last_crc = await async_refresh_system(rec, router, last_crc=last_crc)  # type: ignore[arg-type]
            print(f"  refresh {i + 1}/{cycles}: crc={last_crc}")

        return {
            "b_uid": b_uid,
            "module_count": len(router.modules),
            "smhub_info": info,
            "calls": rec.calls,
        }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    host_arg = sys.argv[1]
    cycle_arg = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    recording = asyncio.run(main(host_arg, cycle_arg))

    out_dir = pathlib.Path(__file__).resolve().parent / "captures"
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / "build_recording.json"
    out_file.write_text(json.dumps(recording, indent=2), encoding="utf-8")
    print(f"\nWrote {len(recording['calls'])} calls to {out_file}")
    print("This file contains site-specific names — keep it local, do not commit.")
