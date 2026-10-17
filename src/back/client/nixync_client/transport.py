"""The agent's WebSocket connection to the Nixync server.

Thin on purpose: JSON in, JSON out, plus the one piece of protocol knowledge that
matters at this level — close code 4404 means "this machine is not registered", which is
permanent and must not be retried.
"""

import json
from urllib.parse import urlsplit, urlunsplit

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

UNKNOWN_MACHINE_CLOSE_CODE = 4404


class NixyncClientError(Exception):
    """Base class for every error this library raises."""


class AgentDisconnected(NixyncClientError):
    """The socket is closed — expected on network loss, and recoverable by reconnecting."""


class UnknownMachineError(NixyncClientError):
    """The server does not know this machine id. Register it before connecting."""


def websocket_url_for(server_url: str, machine_id: str) -> str:
    """Derive the agent's ws(s):// endpoint from the http(s):// URL the GUI collected."""
    parts = urlsplit(server_url)
    scheme = "wss" if parts.scheme == "https" else "ws"
    path = f"{parts.path.rstrip('/')}/ws/machines/{machine_id}"
    return urlunsplit((scheme, parts.netloc, path, "", ""))


class WebSocketTransport:
    """One connection attempt's worth of socket. Reconnection is the agent's job."""

    def __init__(self, server_url: str, machine_id: str):
        self.url = websocket_url_for(server_url, machine_id)
        self._websocket = None

    async def connect(self) -> None:
        try:
            self._websocket = await connect(self.url)
        except ConnectionClosed as closed:
            raise _closed_to_error(closed) from closed

    async def send(self, message: dict) -> None:
        if self._websocket is None:
            raise AgentDisconnected("transport is not connected")
        try:
            await self._websocket.send(json.dumps(message))
        except ConnectionClosed as closed:
            raise _closed_to_error(closed) from closed

    async def receive(self) -> dict:
        if self._websocket is None:
            raise AgentDisconnected("transport is not connected")
        try:
            return json.loads(await self._websocket.recv())
        except ConnectionClosed as closed:
            raise _closed_to_error(closed) from closed

    async def close(self) -> None:
        if self._websocket is not None:
            await self._websocket.close()
            self._websocket = None


def _closed_to_error(closed: ConnectionClosed) -> NixyncClientError:
    code = closed.rcvd.code if closed.rcvd else None
    if code == UNKNOWN_MACHINE_CLOSE_CODE:
        return UnknownMachineError(
            "the server does not recognise this machine id — register the machine first"
        )
    return AgentDisconnected(f"connection closed (code {code})")
