from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QListWidget, QMainWindow, QStackedWidget, QWidget,
)

from nixync_front import style
from nixync_front.api import ApiError, NixyncClient
from nixync_front.config import Config
from nixync_front.dialogs import AddMachineDialog, UndoUpdateDialog
from nixync_front.pages import MachinesPage, RolesPage, UpdatesPage
from nixync_front.widgets import dot


class _StatusSignals(QObject):
    done = Signal(bool, str)


class _StatusCheck(QRunnable):
    """Calls GET /status off the UI thread."""

    def __init__(self, client: NixyncClient):
        super().__init__()
        self.client = client
        self.signals = _StatusSignals()

    def run(self):
        try:
            status = self.client.get_status()
            self.signals.done.emit(True, status.get("hostname", "server"))
        except ApiError as e:
            self.signals.done.emit(False, str(e))


class MainWindow(QMainWindow):
    PAGES = ["Machines", "Roles", "Updates"]

    def __init__(self, config: Config):
        super().__init__()
        self.config = config
        self.client = NixyncClient(config)
        self.setWindowTitle("Nixync")
        self.resize(1360, 860)

        self.sidebar = QListWidget()
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setFixedWidth(200)
        self.sidebar.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.sidebar.addItems(self.PAGES)

        self.machines = MachinesPage(self.client)
        self.roles = RolesPage(self.client)
        self.updates = UpdatesPage(self.client)
        self.stack = QStackedWidget()
        for page in (self.machines, self.roles, self.updates):
            self.stack.addWidget(page)

        self.sidebar.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.sidebar.setCurrentRow(0)

        self.machines.add_machine_requested.connect(self.open_add_machine)
        self.machines.change_roles_requested.connect(lambda: self.go_to("Roles"))
        self.machines.show_update_requested.connect(lambda: self.go_to("Updates"))
        self.machines.undo_requested.connect(self.open_undo)
        self.roles.deploy_requested.connect(lambda _role: self.go_to("Updates"))
        self.updates.undo_requested.connect(self.open_undo)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.sidebar)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self.connection_dot = dot(style.OFFLINE, 8)
        self.connection_label = QLabel(f"Connecting to {config.server_url}")
        status = QWidget()
        status_layout = QHBoxLayout(status)
        status_layout.setContentsMargins(6, 0, 6, 0)
        status_layout.addWidget(self.connection_dot)
        status_layout.addWidget(self.connection_label)
        self.statusBar().addWidget(status)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.check_server)
        self.timer.start(config.poll_interval_seconds * 1000)
        QTimer.singleShot(0, self.check_server)

    def go_to(self, name: str):
        self.sidebar.setCurrentRow(self.PAGES.index(name))

    def open_add_machine(self):
        dialog = AddMachineDialog([r.name for r in self.client.list_roles()], self)
        if dialog.exec():
            # TODO: POST the new machine to the server.
            self.statusBar().showMessage(f"Added {dialog.values()['name']}", 5000)

    def open_undo(self, host: str):
        if UndoUpdateDialog(host, self).exec():
            # TODO: ask the server to roll the host back.
            self.statusBar().showMessage(f"Undoing update on {host}", 5000)

    def check_server(self):
        job = _StatusCheck(self.client)
        job.signals.done.connect(self._on_status, Qt.ConnectionType.QueuedConnection)
        QThreadPool.globalInstance().start(job)

    def _on_status(self, ok: bool, detail: str):
        color = style.OK if ok else style.PROBLEM
        self.connection_dot.setStyleSheet(f"background: {color}; border-radius: 4px;")
        if ok:
            self.connection_label.setText(f"Connected to {detail} ({self.config.server_url})")
        else:
            self.connection_label.setText(f"Can't reach server at {self.config.server_url}")
            self.connection_label.setToolTip(detail)
