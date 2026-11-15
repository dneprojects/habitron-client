"""Tests for the SEA add-on client against a local aiohttp server."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from habitron_client.sea import SeaClient, SeaCommandError, SeaError

TOKEN = "t" * 64


def _app(state: dict[str, Any]) -> web.Application:
    """Build a SEA stand-in whose answers the test sets through ``state``."""

    def authorized(request: web.Request) -> bool:
        return request.headers.get("Authorization") == f"Bearer {TOKEN}"

    async def info(request: web.Request) -> web.Response:
        if not authorized(request):
            return web.Response(status=401)
        return web.json_response(state.get("info", {"api_version": 1}))

    async def values(request: web.Request) -> web.Response:
        if not authorized(request):
            return web.Response(status=401)
        return web.json_response(state.get("state", {"a": 1}))

    async def command(request: web.Request) -> web.Response:
        state.setdefault("commands", []).append(await request.json())
        status = state.get("command_status", 200)
        return web.json_response({"ok": status == 200}, status=status)

    async def ws(request: web.Request) -> web.StreamResponse:
        if not authorized(request):
            return web.Response(status=401)
        socket = web.WebSocketResponse()
        await socket.prepare(request)
        for message in state.get("messages", []):
            if isinstance(message, str):
                await socket.send_str(message)
            else:
                await socket.send_json(message)
        await socket.close()
        return socket

    app = web.Application()
    app.router.add_get("/api/v1/info", info)
    app.router.add_get("/api/v1/state", values)
    app.router.add_post("/api/v1/command", command)
    app.router.add_get("/api/v1/ws", ws)
    return app


def _run(
    state: dict[str, Any],
    scenario: Callable[[SeaClient], Awaitable[Any]],
    token: str = TOKEN,
) -> Any:
    async def main() -> Any:
        server = TestServer(_app(state))
        await server.start_server()
        try:
            async with aiohttp.ClientSession() as session:
                client = SeaClient(session, server.host, server.port, token)
                return await scenario(client)
        finally:
            await server.close()

    return asyncio.run(main())


def test_info_and_state() -> None:
    """Info and state come back as objects."""
    state = {"info": {"api_version": 1, "version": "0.16.0"}, "state": {"a": 2}}

    async def scenario(client: SeaClient) -> tuple[Any, Any]:
        return await client.get_info(), await client.get_state()

    assert _run(state, scenario) == ({"api_version": 1, "version": "0.16.0"}, {"a": 2})


@pytest.mark.parametrize(
    ("state", "token"),
    [
        pytest.param({}, "wrong", id="wrong-token"),
        pytest.param({"info": [1, 2]}, TOKEN, id="not-an-object"),
    ],
)
def test_unusable_info_raises(state: dict[str, Any], token: str) -> None:
    """A rejected token or an answer that is not an object is an error."""
    with pytest.raises(SeaError):
        _run(state, lambda client: client.get_info(), token)


def test_unreachable_host_raises() -> None:
    """A connection error is wrapped as SeaError."""

    async def main() -> None:
        async with aiohttp.ClientSession() as session:
            await SeaClient(session, "127.0.0.1", 9, TOKEN).get_state()

    with pytest.raises(SeaError):
        asyncio.run(main())


def test_command_posts_key_and_value() -> None:
    """A command posts the key and the value."""
    state: dict[str, Any] = {}
    _run(state, lambda client: client.command("regelung", "manual"))

    assert state["commands"] == [{"key": "regelung", "value": "manual"}]


@pytest.mark.parametrize(
    ("status", "error"),
    [
        pytest.param(400, SeaCommandError, id="refused"),
        pytest.param(500, SeaError, id="failed"),
    ],
)
def test_command_errors(status: int, error: type[SeaError]) -> None:
    """A refused command and a server error raise distinct errors."""
    state = {"command_status": status}

    with pytest.raises(error):
        _run(state, lambda client: client.command("strategie_setback", True))


def test_messages_until_the_connection_ends() -> None:
    """Objects are yielded, anything else skipped, the end raises SeaError."""
    state = {
        "messages": [
            {"type": "snapshot", "values": {"a": 1}},
            "not json",
            [1, 2],
            {"type": "update", "values": {"a": 2}},
        ]
    }
    received: list[dict[str, Any]] = []

    async def scenario(client: SeaClient) -> None:
        async for message in client.messages():
            received.append(message)

    with pytest.raises(SeaError, match="connection closed"):
        _run(state, scenario)
    assert received == [
        {"type": "snapshot", "values": {"a": 1}},
        {"type": "update", "values": {"a": 2}},
    ]


def test_messages_with_a_wrong_token_raise() -> None:
    """A refused WebSocket handshake raises SeaError."""

    async def scenario(client: SeaClient) -> None:
        async for _message in client.messages():
            pass

    with pytest.raises(SeaError, match="ws:"):
        _run({}, scenario, token="wrong")
