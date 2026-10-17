"""Placeholder fleet data matching the UI sketch."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum


class Health(Enum):
    OK = "Online"
    PROBLEM = "Problem after update"
    UNREACHABLE = "Can't be reached"


@dataclass
class Build:
    finished: datetime
    generation: int
    ok: bool
    summary: str


@dataclass
class MachineError:
    title: str
    when: datetime
    log: str = ""


@dataclass
class Machine:
    name: str
    preset: str
    group: str
    health: Health
    address: str = ""
    note: str = ""
    nixos_version: str = "24.11"
    # Live usage reported by the device; None when it isn't reporting.
    cpu_percent: float | None = None
    ram_percent: float | None = None
    last_seen: datetime | None = None
    disk_used_gb: float | None = None
    disk_total_gb: float | None = None

    @property
    def disk_percent(self) -> float | None:
        if self.disk_used_gb is None or not self.disk_total_gb:
            return None
        return 100 * self.disk_used_gb / self.disk_total_gb
    extra_apps: list[str] = field(default_factory=list)
    builds: list[Build] = field(default_factory=list)  # newest first
    errors: list[MachineError] = field(default_factory=list)

    @property
    def last_successful_build(self) -> Build | None:
        return next((b for b in self.builds if b.ok), None)


@dataclass
class App:
    name: str
    description: str


class RequestStatus(Enum):
    PENDING = "Pending"
    APPROVED = "Approved"
    DECLINED = "Declined"


@dataclass
class AppRequest:
    """A person on a managed machine asking for an app to be installed."""
    id: int
    machine: str
    app: str
    requested_by: str
    when: datetime
    reason: str = ""
    status: RequestStatus = RequestStatus.PENDING


@dataclass
class Bundle:
    name: str
    description: str
    enabled: bool


@dataclass
class Preset:
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


_NOW = datetime.now().replace(second=0, microsecond=0)


def _ago(**delta) -> datetime:
    return _NOW - timedelta(**delta)


def _history(latest_gen: int, *recent: Build) -> list[Build]:
    """Recent builds followed by a few older successful ones."""
    older = [Build(_ago(days=d), latest_gen - i, True, "Scheduled update")
             for i, d in enumerate((2, 5, 9), start=1)]
    return [*recent, *older]


MACHINES = [
    Machine("lab-01", "Workstation", "Lab A", Health.OK, "10.0.4.11",
            cpu_percent=5.4, ram_percent=56.0, last_seen=_ago(seconds=20),
            disk_used_gb=118, disk_total_gb=256,
            extra_apps=["gimp"],
            builds=_history(42, Build(_ago(hours=2, minutes=4), 42, True, "Added Developer tools"))),
    Machine("lab-02", "Workstation", "Lab A", Health.OK, "10.0.4.12",
            cpu_percent=12.8, ram_percent=47.5, last_seen=_ago(seconds=35),
            disk_used_gb=96.4, disk_total_gb=256,
            builds=_history(42, Build(_ago(hours=2, minutes=1), 42, True, "Added Developer tools"))),
    Machine("lab-03", "Workstation", "Lab A", Health.PROBLEM, "10.0.4.13",
            "updated, but its login screen didn't start afterwards.",
            cpu_percent=31.4, ram_percent=81.3, last_seen=_ago(minutes=1),
            disk_used_gb=201.7, disk_total_gb=256,
            builds=_history(41,
                            Build(_ago(hours=1, minutes=58), 42, False, "Added Developer tools: check failed"),
                            Build(_ago(days=1, hours=3), 41, True, "Scheduled update")),
            errors=[MachineError("The login screen (display-manager) didn't start after the update",
                                 _ago(hours=1, minutes=58),
                                 "10:16:14  activation finished, generation 42 is now current\n"
                                 "10:16:15  check: ssh responds ............................ ok\n"
                                 "10:16:16  check: display-manager.service .................. failed\n"
                                 "10:16:16    Main process exited, code=exited, status=1/FAILURE")]),
    Machine("lab-04", "Workstation", "Lab A", Health.UNREACHABLE, "10.0.4.14",
            "can't be reached. Check that it's turned on and connected to the network.",
            cpu_percent=None, ram_percent=None, last_seen=_ago(hours=2, minutes=3),
            disk_used_gb=None, disk_total_gb=None,
            builds=_history(40, Build(_ago(days=3, hours=6), 40, True, "Scheduled update")),
            errors=[MachineError("Couldn't connect over SSH",
                                 _ago(hours=1, minutes=57),
                                 "ssh: connect to host 10.0.4.14 port 22: Connection timed out")]),
    Machine("build-01", "Build server", "Build", Health.OK, "10.0.2.10",
            cpu_percent=88.2, ram_percent=64.9, last_seen=_ago(seconds=10),
            disk_used_gb=842, disk_total_gb=1000,
            extra_apps=["podman", "tmux"],
            builds=_history(118, Build(_ago(hours=20), 118, True, "Scheduled update"))),
    Machine("web-01", "Web server", "Servers", Health.OK, "10.0.1.10",
            cpu_percent=0.9, ram_percent=38.0, last_seen=_ago(seconds=15),
            disk_used_gb=31.2, disk_total_gb=128,
            builds=_history(77, Build(_ago(days=1, hours=1), 77, True, "Renewed TLS settings"))),
]

# A slice of nixpkgs for the app search until the server can search it.
APP_CATALOG = [
    App("firefox", "Web browser"),
    App("chromium", "Open-source web browser from Google"),
    App("libreoffice", "Office suite: documents, spreadsheets, slides"),
    App("gimp", "Image editor"),
    App("inkscape", "Vector graphics editor"),
    App("vlc", "Media player"),
    App("thunderbird", "Email client"),
    App("vscode", "Code editor from Microsoft"),
    App("neovim", "Terminal text editor"),
    App("htop", "Interactive process viewer"),
    App("tmux", "Terminal multiplexer"),
    App("git", "Version control"),
    App("python3", "Python 3 interpreter"),
    App("nodejs", "JavaScript runtime"),
    App("docker", "Container engine"),
    App("podman", "Daemonless container engine"),
    App("nginx", "Web server and reverse proxy"),
    App("postgresql", "Relational database"),
    App("blender", "3D creation suite"),
    App("obs-studio", "Screen recording and streaming"),
    App("zoom-us", "Video meetings"),
    App("wireshark", "Network protocol analyzer"),
]

PRESETS = [
    Preset("Workstation", [
        Bundle("Developer tools", "Git, a C compiler, Python, VS Code and Docker", True),
        Bundle("Student accounts", "Shared student login and lab admin group", True),
        Bundle("Secure remote login", "SSH with keys only, no root login", True),
        Bundle("Printing", "Connects to the lab printer", False),
    ], ["firefox", "libreoffice", "htop"]),
    Preset("Build server", [
        Bundle("Developer tools", "Git, a C compiler, Python, VS Code and Docker", True),
        Bundle("Secure remote login", "SSH with keys only, no root login", True),
    ]),
    Preset("Web server", [
        Bundle("Secure remote login", "SSH with keys only, no root login", True),
    ], ["nginx"]),
]

_PENDING, _APPROVED, _DECLINED = RequestStatus.PENDING, RequestStatus.APPROVED, RequestStatus.DECLINED

REQUESTS = [
    AppRequest(1, "lab-01", "blender", "student14", _ago(minutes=12), "For the 3D modelling assignment due Friday"),
    AppRequest(2, "lab-01", "inkscape", "student14", _ago(minutes=9), "Need to make vector diagrams for my report"),
    AppRequest(3, "lab-03", "vlc", "student02", _ago(hours=3), "Lecture recordings won't play in the browser"),
    AppRequest(4, "build-01", "postgresql", "ci-bot", _ago(hours=5), "Integration tests need a local database"),
    AppRequest(5, "lab-02", "obs-studio", "student07", _ago(days=1, hours=2), "Recording a presentation"),
    AppRequest(6, "lab-02", "gimp", "student07", _ago(days=2), "Editing photos for the poster", _APPROVED),
    AppRequest(7, "web-01", "wireshark", "intern", _ago(days=3), "", _DECLINED),
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
