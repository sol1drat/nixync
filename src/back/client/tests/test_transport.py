"""Transport-level behaviour, verified against a real WebSocket server.

A fake would not prove the thing that matters here: that a 4404 close from the real
server surfaces as UnknownMachineError rather than a generic disconnect.
"""

import asyncio

import pytest
from websockets.asyncio.server import serve

from nixync_client.transport import (
    AgentDisconnected,
    UnknownMachineError,
    WebSocketTransport,
    websocket_url_for,
)


@pytest.mark.parametrize(
    ("server_url", "expected"),
    [
        ("http://127.0.0.1:8000", "ws://127.0.0.1:8000/ws/machines/m1"),
        ("https://fleet.example.com", "wss://fleet.example.com/ws/machines/m1"),
        ("http://127.0.0.1:8000/", "ws://127.0.0.1:8000/ws/machines/m1"),
    ],
)
def test_websocket_url_is_derived_from_the_http_server_url(server_url, expected):
    """The GUI's login page supplies an http(s) URL; the agent must not need a second one."""
    assert websocket_url_for(server_url, "m1") == expected


async def _serve(handler):
    """Start a throwaway WebSocket server and return (server, ws_url_base)."""
    server = await serve(handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    return server, f"http://127.0.0.1:{port}"


def test_connecting_to_a_machine_the_server_rejects_raises_unknown_machine():
    async def reject(websocket):
        await websocket.close(code=4404, reason="Unknown machine")

    async def scenario():
        server, base_url = await _serve(reject)
        try:
            transport = WebSocketTransport(base_url, "ghost-machine")
            with pytest.raises(UnknownMachineError):
                await transport.connect()
                await transport.receive()
        finally:
            server.close()

    asyncio.run(scenario())


def test_messages_are_sent_and_received_as_json():
    async def echo_back(websocket):
        received = await websocket.recv()
        await websocket.send(received)

    async def scenario():
        server, base_url = await _serve(echo_back)
        try:
            transport = WebSocketTransport(base_url, "m1")
            await transport.connect()
            await transport.send({"type": "telemetry", "cpu_percent": 5.0})

            assert await transport.receive() == {"type": "telemetry", "cpu_percent": 5.0}
            await transport.close()
        finally:
            server.close()

    asyncio.run(scenario())


def test_a_normal_server_disconnect_raises_agent_disconnected():
    async def hang_up(websocket):
        await websocket.close()

    async def scenario():
        server, base_url = await _serve(hang_up)
        try:
            transport = WebSocketTransport(base_url, "m1")
            await transport.connect()
            with pytest.raises(AgentDisconnected):
                await transport.receive()
        finally:
            server.close()

    asyncio.run(scenario())


def test_sending_after_the_server_hangs_up_raises_agent_disconnected():
    async def hang_up(websocket):
        await websocket.close()

    async def scenario():
        server, base_url = await _serve(hang_up)
        try:
            transport = WebSocketTransport(base_url, "m1")
            await transport.connect()
            await asyncio.sleep(0.2)
            with pytest.raises(AgentDisconnected):
                await transport.send({"type": "telemetry"})
        finally:
            server.close()

    asyncio.run(scenario())


def test_using_a_transport_before_connecting_is_a_clear_error():
    transport = WebSocketTransport("http://127.0.0.1:1", "m1")

    with pytest.raises(AgentDisconnected, match="not connected"):
        asyncio.run(transport.send({"type": "telemetry"}))
