"""The device app window: wires the pages to the server."""

import getpass

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtWidgets import QPushButton, QWidget

from nixync_agent.gui.pages import AppsPage, MachinePage, MyRequestsPage
from nixync_agent.gui.shell import AgentShell
from nixync_client import AdminClient, NixyncApiError

DEFAULT_SEARCH_INDEX = "latest-51-nixos-26.05"


class _LoadSignals(QObject):
    done = Signal(object, list, str)


class _Load(QRunnable):
    """Fetch this machine and its requests off the UI thread.

    AdminClient is synchronous, so calling it directly would freeze the window on
    every poll — and it polls every ten seconds.
    """

    def __init__(self, client: AdminClient, machine_id: str):
        super().__init__()
        self.client, self.machine_id = client, machine_id
        self.signals = _LoadSignals()

    def run(self):
        try:
            machine = self.client.get_machine(self.machine_id)
            requests = self.client.list_requests(self.machine_id)
            self.signals.done.emit(machine, requests, "")
        except NixyncApiError as problem:
            self.signals.done.emit(None, [], str(problem))


class AgentWindow(AgentShell):
    """What a person using one managed machine sees."""

    PAGES = ["Apps", "My requests", "This machine"]

    def __init__(self, server_url: str, machine_id: str, *, username: str = "",
                 search_index: str = DEFAULT_SEARCH_INDEX, timeout: float = 5.0):
        self.client = AdminClient(server_url, timeout=timeout)
        self.machine_id = machine_id
        self.username = username or getpass.getuser()
        self.search_index = search_index
        self._requests: list = []
        super().__init__("Nixync", server_url.replace("http://", ""))

        refresh = QPushButton("Refresh")
        refresh.setToolTip("Re-read this machine from the server")
        refresh.clicked.connect(self.refresh)
        self.statusBar().addPermanentWidget(refresh)

    def make_pages(self) -> list[QWidget]:
        self.apps = AppsPage(self.search_index)
        self.apps.requested.connect(self._send_request)
        self.my_requests = MyRequestsPage()
        self.machine = MachinePage()
        return [self.apps, self.my_requests, self.machine]

    def refresh(self) -> None:
        job = _Load(self.client, self.machine_id)
        job.signals.done.connect(self._loaded, Qt.ConnectionType.QueuedConnection)
        QThreadPool.globalInstance().start(job)

    def _loaded(self, machine, requests, error: str) -> None:
        self.set_connected(machine is not None, "" if machine else "Can't reach the server")
        self.machine.show_machine(machine, self.machine_id, error)
        self._requests = [r for r in requests if r.requested_by == self.username]
        self.my_requests.show_requests(self._requests)
        self.apps.set_state(
            installed=set(machine.config.packages) if machine else set(),
            # Only pending ones: a declined request should be askable again, and an
            # approved one shows as installed once it has actually been deployed.
            pending={r.app for r in requests if r.is_pending},
        )

    def _send_request(self, app: str, reason: str) -> None:
        try:
            self.client.create_request(self.machine_id, app, self.username, reason)
        except NixyncApiError as problem:
            self.show_message(f"Couldn't send the request: {problem}")
            return
        self.show_message(f"Asked for {app}. Your administrator will decide.")
        self.refresh()
