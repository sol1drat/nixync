import asyncio

from connection_manager import ConnectionManager


class FakeWebSocket:
    def __init__(self):
        self.sent: list[dict] = []
        self.closed = False

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)

    async def close(self, code: int = 1000) -> None:
        self.closed = True


def test_unknown_machine_is_not_connected():
    manager = ConnectionManager()

    assert manager.is_connected("unknown") is False


def test_register_marks_machine_as_connected():
    manager = ConnectionManager()
    ws = FakeWebSocket()

    manager.register("m1", ws)

    assert manager.is_connected("m1") is True


def test_unregister_marks_machine_as_disconnected():
    manager = ConnectionManager()
    ws = FakeWebSocket()
    manager.register("m1", ws)

    manager.unregister("m1")

    assert manager.is_connected("m1") is False


def test_send_json_to_unconnected_machine_returns_false():
    manager = ConnectionManager()

    delivered = asyncio.run(manager.send_json("unknown", {"type": "ping"}))

    assert delivered is False


def test_close_disconnects_the_socket_and_deregisters_it():
    manager = ConnectionManager()
    ws = FakeWebSocket()
    manager.register("m1", ws)

    closed = asyncio.run(manager.close("m1"))

    assert closed is True
    assert ws.closed is True
    assert manager.is_connected("m1") is False


def test_close_on_unconnected_machine_returns_false():
    manager = ConnectionManager()

    assert asyncio.run(manager.close("unknown")) is False


def test_send_json_to_connected_machine_delivers_and_returns_true():
    manager = ConnectionManager()
    ws = FakeWebSocket()
    manager.register("m1", ws)

    delivered = asyncio.run(manager.send_json("m1", {"type": "apply_config"}))

    assert delivered is True
    assert ws.sent == [{"type": "apply_config"}]
