from typing import Protocol


class _MachineSocket(Protocol):
    async def send_json(self, payload: dict) -> None: ...

    async def close(self, code: int = 1000) -> None: ...


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[str, _MachineSocket] = {}

    def register(self, machine_id: str, websocket: _MachineSocket) -> None:
        self._connections[machine_id] = websocket

    def unregister(self, machine_id: str) -> None:
        self._connections.pop(machine_id, None)

    def is_connected(self, machine_id: str) -> bool:
        return machine_id in self._connections

    async def send_json(self, machine_id: str, payload: dict) -> bool:
        websocket = self._connections.get(machine_id)
        if websocket is None:
            return False
        await websocket.send_json(payload)
        return True

    async def close(self, machine_id: str, code: int = 1000) -> bool:
        websocket = self._connections.pop(machine_id, None)
        if websocket is None:
            return False
        await websocket.close(code=code)
        return True
