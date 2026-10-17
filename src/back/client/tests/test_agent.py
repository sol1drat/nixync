"""Agent logic, driven against a fake transport so every branch is reachable.

Socket-level and server-level behaviour is covered by test_transport.py and
test_agent_end_to_end.py; these tests are about what the agent *decides*.
"""

import asyncio

import pytest

from nixync_client.agent import NixyncAgent
from nixync_client.protocol import MachineConfig
from nixync_client.telemetry import Reading
from nixync_client.transport import AgentDisconnected, UnknownMachineError

SAMPLE_READING = Reading(
    cpu_percent=12.5,
    ram_used_mb=2048,
    ram_total_mb=8192,
    disk_used_gb=100.0,
    disk_total_gb=512.0,
)


class FakeTransport:
    """Replays a scripted set of inbound messages and records everything sent."""

    def __init__(self, inbound=None, fail_connect=None):
        self.sent: list[dict] = []
        self.connected = False
        self.closed = False
        self.connect_count = 0
        self._inbound = asyncio.Queue()
        self._fail_connect = fail_connect
        for message in inbound or []:
            self._inbound.put_nowait(message)

    async def connect(self):
        self.connect_count += 1
        if self._fail_connect:
            raise self._fail_connect
        self.connected = True

    async def send(self, message):
        self.sent.append(message)

    async def receive(self):
        message = await self._inbound.get()
        if isinstance(message, Exception):
            raise message
        return message

    async def close(self):
        self.closed = True

    def sent_of_type(self, message_type: str) -> list[dict]:
        return [m for m in self.sent if m["type"] == message_type]


def build_agent(transport, **kwargs) -> NixyncAgent:
    kwargs.setdefault("sampler", lambda: SAMPLE_READING)
    kwargs.setdefault("telemetry_interval", 0.05)
    return NixyncAgent(
        server_url="http://testserver",
        machine_id="m1",
        transport_factory=lambda: transport,
        **kwargs,
    )


def run_until_disconnect(agent, transport):
    """Run one connection cycle, ending when the scripted inbound queue closes it."""
    asyncio.run(agent.run())
    return transport


def test_the_agent_reports_its_config_as_soon_as_it_connects():
    transport = FakeTransport(inbound=[AgentDisconnected("done")])
    agent = build_agent(
        transport,
        current_config=lambda: MachineConfig(packages=["git"]),
        reconnect=False,
    )

    run_until_disconnect(agent, transport)

    reports = transport.sent_of_type("config_report")
    assert len(reports) == 1
    assert reports[0]["config"]["packages"] == ["git"]


def test_an_agent_with_no_config_source_reports_an_empty_config():
    transport = FakeTransport(inbound=[AgentDisconnected("done")])
    agent = build_agent(transport, reconnect=False)

    run_until_disconnect(agent, transport)

    assert transport.sent_of_type("config_report")[0]["config"]["packages"] == []


def test_the_agent_sends_telemetry_immediately_rather_than_waiting_an_interval():
    """A dashboard that shows nothing for two minutes after connect is useless."""
    transport = FakeTransport(inbound=[AgentDisconnected("done")])
    agent = build_agent(transport, telemetry_interval=3600, reconnect=False)

    run_until_disconnect(agent, transport)

    telemetry = transport.sent_of_type("telemetry")
    assert len(telemetry) == 1
    assert telemetry[0]["cpu_percent"] == 12.5
    assert telemetry[0]["ram_used_mb"] == 2048


def test_the_agent_keeps_sending_telemetry_on_its_interval():
    async def scenario():
        transport = FakeTransport()  # never yields, so the agent just keeps running
        agent = build_agent(transport, telemetry_interval=0.05, reconnect=False)

        task = asyncio.create_task(agent.run())
        await asyncio.sleep(0.3)
        agent.stop()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=2)
        return transport

    transport = asyncio.run(scenario())
    assert len(transport.sent_of_type("telemetry")) >= 3, "interval sampling kept going"


def test_an_apply_config_push_reaches_the_handler_with_the_full_desired_state():
    received: list[MachineConfig] = []
    transport = FakeTransport(
        inbound=[
            {"type": "apply_config", "apply_id": "a1", "config": {"packages": ["htop", "git"]}},
            AgentDisconnected("done"),
        ]
    )
    agent = build_agent(transport, on_apply=received.append, reconnect=False)

    run_until_disconnect(agent, transport)

    assert len(received) == 1
    assert received[0].packages == ["htop", "git"]


def test_a_handler_that_returns_normally_acks_applied():
    transport = FakeTransport(
        inbound=[
            {"type": "apply_config", "apply_id": "a1", "config": {}},
            AgentDisconnected("done"),
        ]
    )
    agent = build_agent(transport, on_apply=lambda config: None, reconnect=False)

    run_until_disconnect(agent, transport)

    ack = transport.sent_of_type("apply_result")[0]
    assert ack == {"type": "apply_result", "apply_id": "a1", "status": "applied", "message": None}


def test_a_handler_that_raises_acks_failed_with_the_reason():
    def explode(config):
        raise RuntimeError("nixos-rebuild exited 1")

    transport = FakeTransport(
        inbound=[
            {"type": "apply_config", "apply_id": "a1", "config": {}},
            AgentDisconnected("done"),
        ]
    )
    agent = build_agent(transport, on_apply=explode, reconnect=False)

    run_until_disconnect(agent, transport)

    ack = transport.sent_of_type("apply_result")[0]
    assert ack["status"] == "failed"
    assert ack["message"] == "nixos-rebuild exited 1"


def test_an_agent_with_no_handler_reports_failure_instead_of_claiming_success():
    """Silently acking 'applied' with nothing applied would corrupt the dashboard."""
    transport = FakeTransport(
        inbound=[
            {"type": "apply_config", "apply_id": "a1", "config": {}},
            AgentDisconnected("done"),
        ]
    )
    agent = build_agent(transport, reconnect=False)

    run_until_disconnect(agent, transport)

    ack = transport.sent_of_type("apply_result")[0]
    assert ack["status"] == "failed"
    assert "no handler" in ack["message"].lower()


def test_the_agent_re_reports_its_config_after_applying_a_change():
    """Otherwise the server's view goes stale the moment a deployment lands.

    Reported state would only ever be as fresh as the last connect, so every machine
    the admin deployed to would show as drifted until it happened to reconnect.
    """
    box_packages: list[str] = []

    def install(config: MachineConfig):
        box_packages[:] = config.packages

    transport = FakeTransport(
        inbound=[
            {"type": "apply_config", "apply_id": "a1", "config": {"packages": ["htop"]}},
            AgentDisconnected("done"),
        ]
    )
    agent = build_agent(
        transport,
        on_apply=install,
        current_config=lambda: MachineConfig(packages=list(box_packages)),
        reconnect=False,
    )

    run_until_disconnect(agent, transport)

    reports = transport.sent_of_type("config_report")
    assert len(reports) == 2, "once on connect, once after the apply"
    assert reports[0]["config"]["packages"] == [], "the machine started empty"
    assert reports[1]["config"]["packages"] == ["htop"], "and reports the new reality"


def test_the_agent_re_reports_its_config_even_when_the_apply_failed():
    """A partial rebuild leaves the box in some state; the admin needs to see which."""

    def explode(config):
        raise RuntimeError("boom")

    transport = FakeTransport(
        inbound=[
            {"type": "apply_config", "apply_id": "a1", "config": {"packages": ["htop"]}},
            AgentDisconnected("done"),
        ]
    )
    agent = build_agent(
        transport,
        on_apply=explode,
        current_config=lambda: MachineConfig(packages=["git"]),
        reconnect=False,
    )

    run_until_disconnect(agent, transport)

    assert transport.sent_of_type("apply_result")[0]["status"] == "failed"
    assert transport.sent_of_type("config_report")[-1]["config"]["packages"] == ["git"]


def test_an_unknown_message_type_does_not_kill_the_connection():
    transport = FakeTransport(
        inbound=[
            {"type": "something_new_from_a_later_server"},
            {"type": "apply_config", "apply_id": "a1", "config": {}},
            AgentDisconnected("done"),
        ]
    )
    agent = build_agent(transport, on_apply=lambda config: None, reconnect=False)

    run_until_disconnect(agent, transport)

    assert transport.sent_of_type("apply_result"), "the agent kept going past the unknown message"


def test_unknown_machine_is_not_a_kind_of_disconnect():
    """The hierarchy is what stops the retry loop, so pin it.

    `run()` retries on AgentDisconnected. If UnknownMachineError ever became a subclass
    of it — a tempting refactor, since it does arrive as a socket close — an agent with
    a bad id would hammer the server forever instead of failing loudly.
    """
    assert not issubclass(UnknownMachineError, AgentDisconnected)


def test_an_unregistered_machine_gives_up_instead_of_retrying_forever():
    transport = FakeTransport(fail_connect=UnknownMachineError("not registered"))
    agent = build_agent(transport, reconnect=True)

    with pytest.raises(UnknownMachineError):
        asyncio.run(agent.run())

    assert transport.connect_count == 1, "a permanent rejection must not be retried"


def test_a_dropped_connection_is_retried():
    class FlakyTransport(FakeTransport):
        async def connect(self):
            self.connect_count += 1
            if self.connect_count == 1:
                raise AgentDisconnected("network blip")
            self.connected = True

    transport = FlakyTransport(inbound=[AgentDisconnected("done")])
    agent = build_agent(transport, reconnect=True, max_connection_attempts=2, backoff_base=0.01)

    asyncio.run(agent.run())

    assert transport.connect_count == 2, "the agent came back after the blip"
    assert transport.sent_of_type("telemetry"), "and resumed reporting once reconnected"


def test_stop_ends_the_run_loop():
    async def scenario():
        transport = FakeTransport()
        agent = build_agent(transport, telemetry_interval=10, reconnect=False)
        task = asyncio.create_task(agent.run())
        await asyncio.sleep(0.1)
        agent.stop()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=2)
        return transport

    transport = asyncio.run(scenario())
    assert transport.closed, "the socket was closed on the way out"


def test_a_slow_handler_does_not_block_telemetry():
    """nixos-rebuild takes minutes; the socket must stay responsive while it runs."""
    import time

    def slow_apply(config):
        time.sleep(0.3)

    transport = FakeTransport(
        inbound=[
            {"type": "apply_config", "apply_id": "a1", "config": {}},
            AgentDisconnected("done"),
        ]
    )
    agent = build_agent(
        transport, on_apply=slow_apply, telemetry_interval=0.05, reconnect=False
    )

    run_until_disconnect(agent, transport)

    assert len(transport.sent_of_type("telemetry")) >= 2, "telemetry continued during the apply"
    assert transport.sent_of_type("apply_result")[0]["status"] == "applied"
