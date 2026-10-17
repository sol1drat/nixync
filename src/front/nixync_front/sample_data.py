"""Placeholder fleet data matching the UI sketch."""

from dataclasses import dataclass, field
from enum import Enum


class Health(Enum):
    OK = "Up to date"
    PROBLEM = "Problem after update"
    UNREACHABLE = "Can't be reached"


@dataclass
class Machine:
    name: str
    role: str
    group: str
    health: Health
    address: str = ""
    note: str = ""


@dataclass
class Bundle:
    name: str
    description: str
    enabled: bool


@dataclass
class Role:
    name: str
    bundles: list[Bundle]
    extra_apps: list[str] = field(default_factory=list)


class Step(Enum):
    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"


@dataclass
class HostResult:
    name: str
    text: str
    # prepare, connect, install, check
    steps: tuple[Step, Step, Step, Step]
    log: str = ""


@dataclass
class Update:
    title: str
    started: str
    test_host: str
    paused: bool
    results: list[HostResult]


MACHINES = [
    Machine("lab-01", "Workstation", "Lab A", Health.OK, "10.0.4.11"),
    Machine("lab-02", "Workstation", "Lab A", Health.OK, "10.0.4.12"),
    Machine("lab-03", "Workstation", "Lab A", Health.PROBLEM, "10.0.4.13",
            "updated, but its login screen didn't start afterwards."),
    Machine("lab-04", "Workstation", "Lab A", Health.UNREACHABLE, "10.0.4.14",
            "can't be reached. Check that it's turned on and connected to the network."),
    Machine("build-01", "Build server", "Build", Health.OK, "10.0.2.10"),
    Machine("web-01", "Web server", "Servers", Health.OK, "10.0.1.10"),
]

ROLES = [
    Role("Workstation", [
        Bundle("Developer tools", "Git, a C compiler, Python, VS Code and Docker", True),
        Bundle("Student accounts", "Shared student login and lab admin group", True),
        Bundle("Secure remote login", "SSH with keys only, no root login", True),
        Bundle("Printing", "Connects to the lab printer", False),
    ], ["firefox", "libreoffice", "htop"]),
    Role("Build server", [
        Bundle("Developer tools", "Git, a C compiler, Python, VS Code and Docker", True),
        Bundle("Secure remote login", "SSH with keys only, no root login", True),
    ]),
    Role("Web server", [
        Bundle("Secure remote login", "SSH with keys only, no root login", True),
    ], ["nginx"]),
]

_D, _F, _P = Step.DONE, Step.FAILED, Step.PENDING

CURRENT_UPDATE = Update(
    title="Adding Developer tools to Workstation",
    started="Started at 10:12 by admin",
    test_host="lab-01",
    paused=True,
    results=[
        HostResult("lab-01", "Updated and working", (_D, _D, _D, _D)),
        HostResult("lab-02", "Updated and working", (_D, _D, _D, _D)),
        HostResult("lab-03", "Updated, but the login screen didn't start", (_D, _D, _D, _F),
                   "10:16:14  activation finished, generation 42 is now current\n"
                   "10:16:15  check: ssh responds ............................ ok\n"
                   "10:16:16  check: display-manager.service .................. failed\n"
                   "10:16:16    Main process exited, code=exited, status=1/FAILURE"),
        HostResult("lab-04", "Couldn't connect, will try again when it's back online", (_D, _F, _P, _P)),
    ],
)
