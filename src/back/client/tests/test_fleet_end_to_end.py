"""Both halves of the library against one real server.

test_admin.py proves the admin calls; test_agent_end_to_end.py proves the agent. This
file proves they work *together* — an admin action on one side arriving as real work on
the other — which is the only thing the product actually sells.

Everything here goes through the public API, so these tests double as a worked example
of how the desktop GUI and a NixOS box use the library.
"""

import asyncio
import contextlib
import time

import pytest

from nixync_client.admin import AdminClient
from nixync_client.agent import NixyncAgent
from nixync_client.protocol import MachineConfig

SETTLE_TIMEOUT_SECONDS = 5


@pytest.fixture
def admin(live_server) -> AdminClient:
    return AdminClient(live_server)


async def wait_until(admin: AdminClient, machine_id: str, predicate, what: str):
    """Poll the way the dashboard does, instead of sleeping and hoping.

    Must be async and must not block: the agent under test shares this event loop, so a
    blocking poll would stop the very thing we are waiting for from making progress.
    """
    deadline = time.monotonic() + SETTLE_TIMEOUT_SECONDS
    machine = None
    while time.monotonic() < deadline:
        machine = await call(admin.get_machine, machine_id)
        if predicate(machine):
            return machine
        await asyncio.sleep(0.05)
    pytest.fail(f"never reached: {what}\nlast seen: {machine}")


async def call(blocking_fn, *args, **kwargs):
    """Run a synchronous AdminClient call off the event loop.

    This is exactly what the Qt GUI must do with AdminClient, for the same reason.
    """
    return await asyncio.to_thread(blocking_fn, *args, **kwargs)


class FakeNixOSBox:
    """A managed machine. Records what it was told to install, like a real box would."""

    def __init__(self):
        self.installed: list[str] = []
        self.applies: list[MachineConfig] = []
        self.fail_with: str | None = None

    def apply(self, config: MachineConfig) -> None:
        if self.fail_with:
            raise RuntimeError(self.fail_with)
        self.applies.append(config)
        self.installed = list(config.packages)

    def current_config(self) -> MachineConfig:
        return MachineConfig(packages=list(self.installed))


@contextlib.asynccontextmanager
async def booted(live_server: str, machine_id: str, box: FakeNixOSBox):
    """Bring a machine online for the duration of the block."""
    agent = NixyncAgent(
        server_url=live_server,
        machine_id=machine_id,
        on_apply=box.apply,
        current_config=box.current_config,
        telemetry_interval=60,
    )
    task = asyncio.create_task(agent.run())
    try:
        yield agent
    finally:
        agent.stop()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await asyncio.wait_for(task, timeout=5)


def test_a_university_lab_rollout_driven_entirely_through_the_library(live_server, admin):
    """The CLAUDE.md scenario, played out through AdminClient and NixyncAgent."""

    async def scenario():
        # STEP 1 — The admin enrols three lab machines from the GUI.
        bench = await call(admin.register_machine, "library-test-bench")
        desk_1 = await call(admin.register_machine, "library-desk-01")
        desk_2 = await call(admin.register_machine, "library-desk-02")

        # STEP 2 — Each id is handed to that machine's agent out of band. Before any
        # agent runs, the dashboard honestly shows nothing is known about them.
        assert all(not m.online for m in (bench, desk_1, desk_2))
        assert bench.cpu_percent is None

        bench_box, desk_1_box, desk_2_box = FakeNixOSBox(), FakeNixOSBox(), FakeNixOSBox()
        desk_1_box.fail_with = "error: gcc collides with clang in /nix/store"

        async with booted(live_server, bench.id, bench_box):
            # STEP 3 — The test bench boots. It appears online with live metrics.
            live = await wait_until(
                admin, bench.id, lambda m: m.online and m.cpu_percent is not None,
                "the test bench reported in",
            )
            assert 0.0 <= live.cpu_percent <= 100.0
            assert live.ram_total_mb > 0

            # STEP 4 — Staged rollout, stage one: prove the change on one machine.
            results = await call(admin.add_packages, ["neovim", "gcc"], machine_ids=[bench.id])
            assert results[0].delivery == "pushed"
            assert results[0].needs_deployment

            await wait_until(
                admin, bench.id, lambda m: m.last_apply_status == "applied",
                "the test bench applied the change",
            )
            assert bench_box.installed == ["gcc", "neovim"], "the box did the real work"

        # STEP 5 — Stage two: roll out to the lab. desk-02 is powered off, and the
        # bench has already proved this config, so three machines get three outcomes.
        async with booted(live_server, desk_1.id, desk_1_box):
            await wait_until(admin, desk_1.id, lambda m: m.online, "desk-01 booted")

            rollout = {r.machine_id: r for r in await call(admin.add_packages, ["neovim", "gcc"])}
            assert rollout[desk_1.id].delivery == "pushed"
            assert rollout[desk_2.id].delivery == "queued", "powered off, not forgotten"
            assert rollout[bench.id].delivery == "unchanged", "already compliant"
            assert not rollout[bench.id].needs_deployment

            # STEP 6 — desk-01's build fails. The admin gets the reason, not a red dot.
            broken = await wait_until(
                admin, desk_1.id, lambda m: m.last_apply_status == "failed",
                "desk-01 reported its failure",
            )
            assert broken.last_apply_message == "error: gcc collides with clang in /nix/store"
            assert desk_1_box.installed == [], "nothing was installed on the broken box"

        # STEP 7 — Per-machine results from one fleet-wide request.
        by_id = {m.id: m for m in await call(admin.list_machines)}
        assert by_id[bench.id].last_apply_status == "applied"
        assert by_id[desk_1.id].last_apply_status == "failed"
        assert by_id[desk_2.id].last_apply_status == "pending"

        # STEP 8 — Recovery: desk-02 is switched on and catches up unprompted.
        async with booted(live_server, desk_2.id, desk_2_box):
            await wait_until(
                admin, desk_2.id, lambda m: m.last_apply_status == "applied",
                "desk-02 caught up on reconnect",
            )
            assert desk_2_box.installed == ["gcc", "neovim"]

        # STEP 9 — A fleet-wide removal reaches the machines that have the package.
        await call(admin.remove_packages, ["gcc"])
        assert (await call(admin.get_machine, bench.id)).config.packages == ["neovim"]
        assert (await call(admin.get_machine, desk_2.id)).config.packages == ["neovim"]

        # STEP 10 — Decommissioning takes a machine out of the fleet for good.
        await call(admin.remove_machine, desk_2.id)
        assert desk_2.id not in {m.id for m in await call(admin.list_machines)}

    asyncio.run(scenario())


def test_an_agent_reports_the_config_its_box_already_has(live_server, admin):
    """A machine that is already configured should not look empty on the dashboard."""

    async def scenario():
        machine = await call(admin.register_machine, "library-preconfigured")
        box = FakeNixOSBox()
        box.installed = ["git", "tmux"]

        async with booted(live_server, machine.id, box):
            reported = await wait_until(
                admin, machine.id, lambda m: m.config.packages != [],
                "the box reported what it already has",
            )

        assert reported.config.packages == ["git", "tmux"]

    asyncio.run(scenario())


def test_a_retried_change_is_reported_as_unchanged_once_it_has_been_proved(live_server, admin):
    """Clicking 'install' twice must not drag a healthy machine back to pending."""

    async def scenario():
        machine = await call(admin.register_machine, "library-idempotent")
        box = FakeNixOSBox()

        async with booted(live_server, machine.id, box):
            await wait_until(admin, machine.id, lambda m: m.online, "booted")

            await call(admin.add_packages, ["htop"], machine_ids=[machine.id])
            await wait_until(
                admin, machine.id, lambda m: m.last_apply_status == "applied", "first apply"
            )

            again = await call(admin.add_packages, ["htop"], machine_ids=[machine.id])

            assert again[0].delivery == "unchanged"
            assert not again[0].needs_deployment
            assert (await call(admin.get_machine, machine.id)).last_apply_status == "applied"
            assert len(box.applies) == 1, "the box was not asked to do the work twice"

    asyncio.run(scenario())


def test_two_machines_stay_independent_under_a_targeted_change(live_server, admin):
    """Targeting one device must not touch the one next to it."""

    async def scenario():
        target = await call(admin.register_machine, "library-target")
        bystander = await call(admin.register_machine, "library-bystander")
        target_box, bystander_box = FakeNixOSBox(), FakeNixOSBox()

        async with booted(live_server, target.id, target_box), booted(
            live_server, bystander.id, bystander_box
        ):
            await wait_until(admin, target.id, lambda m: m.online, "target booted")
            await wait_until(admin, bystander.id, lambda m: m.online, "bystander booted")

            await call(admin.add_packages, ["htop"], machine_ids=[target.id])
            await wait_until(
                admin, target.id, lambda m: m.last_apply_status == "applied", "target applied"
            )

            assert target_box.installed == ["htop"]
            assert bystander_box.installed == [], "the bystander was never asked to do anything"
            assert (await call(admin.get_machine, bystander.id)).last_apply_status is None

    asyncio.run(scenario())


def test_an_agents_config_report_must_not_erase_a_pending_desired_change(live_server, admin):
    """Regression for a fixed bug: booting into queued work used to corrupt the dashboard.

    The machine used to end up correct on disk but wrong on screen:
      1. Admin queues 'add gcc, neovim' while the machine is powered off.
      2. The machine boots, genuinely has nothing installed, and says so via
         config_report — which overwrote the desired config the admin just set.
      3. The queued change was still pushed, installed, and acked 'applied'.
      4. Result: the machine really had gcc and neovim, but the dashboard showed an
         empty package list next to a green 'applied' badge.

    Fixed by storing reported state in its own column. This hits the recovery path —
    the headline feature — so it is worth a dedicated test.
    """

    async def scenario():
        machine = await call(admin.register_machine, "library-drift")
        box = FakeNixOSBox()  # a genuinely empty machine

        await call(admin.add_packages, ["gcc", "neovim"], machine_ids=[machine.id])

        async with booted(live_server, machine.id, box):
            await wait_until(
                admin, machine.id, lambda m: m.last_apply_status == "applied",
                "the queued change was applied on boot",
            )

        assert box.installed == ["gcc", "neovim"], "the machine really did install them"

        final = await call(admin.get_machine, machine.id)
        assert final.config.packages == ["gcc", "neovim"], (
            "the dashboard must reflect what the machine actually has"
        )

    asyncio.run(scenario())


def test_a_hand_edited_machine_shows_as_drifted_without_losing_the_admins_intent(
    live_server, admin
):
    """Drift detection, which separating desired from reported state makes possible.

    Someone edits configuration.nix on the box directly. The fleet view must show that
    the machine no longer matches what was declared — and must not quietly adopt the
    hand-edit as the new intent.
    """

    async def scenario():
        machine = await call(admin.register_machine, "library-drifted")
        box = FakeNixOSBox()

        async with booted(live_server, machine.id, box):
            await wait_until(admin, machine.id, lambda m: m.online, "booted")

            await call(admin.add_packages, ["htop"], machine_ids=[machine.id])
            await wait_until(
                admin, machine.id, lambda m: m.last_apply_status == "applied", "applied"
            )
            assert not (await call(admin.get_machine, machine.id)).has_drifted

        # Someone installs nmap by hand, then the machine reconnects and reports it.
        box.installed.append("nmap")

        async with booted(live_server, machine.id, box):
            drifted = await wait_until(
                admin,
                machine.id,
                lambda m: m.reported_config is not None
                and "nmap" in m.reported_config.packages,
                "the machine reported its hand-edited state",
            )

        assert drifted.has_drifted, "the fleet view flags the mismatch"
        assert drifted.config.packages == ["htop"], "the admin's intent is unchanged"
        assert sorted(drifted.reported_config.packages) == ["htop", "nmap"]


    asyncio.run(scenario())


def test_a_machine_that_has_never_reported_is_not_treated_as_drifted(live_server, admin):
    """Unknown is not drift — a powered-off machine must not light up the dashboard."""
    machine = admin.register_machine("library-never-reported")

    assert machine.reported_config is None
    assert machine.has_drifted is False
