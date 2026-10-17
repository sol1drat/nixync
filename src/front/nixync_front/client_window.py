"""The client app: what a person using one managed device sees.

Built on the admin MainWindow shell (sidebar, theme switching, server status, sign out)
with its own pages: an app store for requesting apps, their requests, the device's users
and the system settings a user may change.
"""

import hashlib

from PySide6.QtCore import QThreadPool, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QScrollArea,
    QVBoxLayout, QWidget,
)
from PySide6.QtGui import QIcon

from nixync_front import style
from nixync_front.api import ApiError, NixyncClient
from nixync_front.app_picker import _Search
from nixync_front.config import Config
from nixync_front.main_window import MainWindow
from nixync_front.nixos_search import Package
from nixync_front.sample_data import APP_CATALOG, RequestStatus
from nixync_front.settings_panel import SettingsPanel
from nixync_front.users_panel import UsersPanel
from nixync_front.widgets import (
    FlowLayout, Panel, RingGauge, ago, clear_layout, page_header, primary_button, search_icon, status_text, cancel_box,
    themed_icon,
)

CARD_WIDTH = 300
RESULT_LIMIT = 24
# Tile colors for app initials; picked per app name so an app always gets the same one.
TILE_COLORS = ["#1D5FD1", "#1A7F37", "#8250DF", "#BF3989", "#D4A72C", "#0E8A7E", "#CF5A22", "#57606A"]


def scroll_page() -> tuple[QWidget, QVBoxLayout]:
    """A page whose content scrolls; returns (page, content layout)."""
    page = QWidget()
    outer = QVBoxLayout(page)
    outer.setContentsMargins(0, 0, 0, 0)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    outer.addWidget(scroll)
    content = QWidget()
    layout = QVBoxLayout(content)
    layout.setContentsMargins(28, 24, 28, 24)
    layout.setSpacing(16)
    scroll.setWidget(content)
    return page, layout


def app_tile(name: str, size: int = 44) -> QLabel:
    tile = QLabel(name[:1].upper())
    tile.setFixedSize(size, size)
    tile.setAlignment(Qt.AlignmentFlag.AlignCenter)
    color = TILE_COLORS[int(hashlib.md5(name.encode()).hexdigest(), 16) % len(TILE_COLORS)]
    tile.setStyleSheet(f"background: {color}; color: white; border-radius: 10px; "
                       f"font-size: {size // 2}px; font-weight: 700;")
    return tile


class RequestDialog(QDialog):
    def __init__(self, package: Package, device: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Request {package.name}")
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        head = QHBoxLayout()
        head.setSpacing(12)
        head.addWidget(app_tile(package.name, 52))
        text = QVBoxLayout()
        title = QLabel(package.name)
        title.setObjectName("PageTitle")
        text.addWidget(title)
        desc = QLabel(package.description or "No description")
        desc.setObjectName("Muted")
        desc.setWordWrap(True)
        text.addWidget(desc)
        head.addLayout(text, 1)
        layout.addLayout(head)
        note = QLabel(f"Your administrator reviews requests before anything is installed on {device}.")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addWidget(QLabel("Why do you need it? (optional)"))
        self.reason = QPlainTextEdit()
        self.reason.setPlaceholderText("e.g. For the 3D modelling assignment due Friday")
        self.reason.setFixedHeight(84)
        layout.addWidget(self.reason)
        buttons = cancel_box()
        send = buttons.addButton("Send request", QDialogButtonBox.ButtonRole.AcceptRole)
        send.setProperty("primary", True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class AppCard(Panel):
    """One app in the store: tile, name, version, description and its request state."""

    request_clicked = Signal(object)  # Package

    def __init__(self, package: Package, state: str):
        super().__init__("Card")
        self.setFixedWidth(CARD_WIDTH)
        self.body.setContentsMargins(14, 14, 14, 12)
        top = QHBoxLayout()
        top.setSpacing(12)
        top.addWidget(app_tile(package.name), 0, Qt.AlignmentFlag.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(2)
        name = QLabel(package.name)
        name.setStyleSheet("font-weight: 600; font-size: 15px; border: none;")
        text.addWidget(name)
        if package.version:
            version = QLabel(package.version)
            version.setObjectName("Muted")
            version.setStyleSheet("font-size: 12px; border: none;")
            text.addWidget(version)
        top.addLayout(text, 1)
        self.body.addLayout(top)

        desc = QLabel()
        desc.setObjectName("Muted")
        desc.setStyleSheet("font-size: 13px; border: none;")
        desc.setWordWrap(True)
        full = package.description or "No description"
        # Two lines at most, so cards stay the same height.
        metrics = desc.fontMetrics()
        width = CARD_WIDTH - 28
        if metrics.horizontalAdvance(full) > 2 * width - 20:
            full_cut = metrics.elidedText(full, Qt.TextElideMode.ElideRight, 2 * width - 40)
            desc.setText(full_cut)
            desc.setToolTip(package.description)
        else:
            desc.setText(full)
        desc.setFixedHeight(2 * metrics.lineSpacing() + 2)
        self.body.addWidget(desc)

        bottom = QHBoxLayout()
        bottom.addStretch()
        if state == "installed":
            bottom.addWidget(status_text(style.OK, "Installed"))
        elif state == "requested":
            bottom.addWidget(status_text(style.MUTED, "Requested"))
        else:
            request = primary_button("Request")
            request.setObjectName("SmallButton")
            request.clicked.connect(lambda: self.request_clicked.emit(package))
            bottom.addWidget(request)
        self.body.addLayout(bottom)


class StorePage(QWidget):
    message = Signal(str)
    requested = Signal()

    def __init__(self, client: NixyncClient, device: str, username: str):
        super().__init__()
        self.client, self.device, self.username = client, device, username
        self.packages: list[Package] = []
        self._seq = 0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 0)
        outer.setSpacing(14)
        outer.addWidget(page_header("Apps", f"Find apps for {device}. Your administrator approves requests."))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search apps (from search.nixos.org)")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumHeight(42)
        themed_icon(self.search.addAction(QIcon(), QLineEdit.ActionPosition.LeadingPosition), search_icon,
                    owner=self.search)
        self.search.textChanged.connect(self._schedule)
        outer.addWidget(self.search)
        self.heading = QLabel()
        self.heading.setStyleSheet("font-size: 16px; font-weight: 600;")
        outer.addWidget(self.heading)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        grid_host = QWidget()
        self.grid = FlowLayout(grid_host, spacing=12)
        self.grid.setContentsMargins(0, 0, 0, 24)
        scroll.setWidget(grid_host)
        outer.addWidget(scroll, 1)

        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(300)
        self.debounce.timeout.connect(self._run_search)
        self._show_popular()

    def _state(self, name: str) -> str:
        if name in self.client.installed_apps(self.device):
            return "installed"
        if any(r.app == name for r in self.client.pending_requests(self.device)):
            return "requested"
        return ""

    def _render(self, packages: list[Package]):
        clear_layout(self.grid)
        for package in packages:
            card = AppCard(package, self._state(package.name))
            card.request_clicked.connect(self._request)
            self.grid.addWidget(card)

    def _show_popular(self):
        self.heading.setText("Popular apps")
        self.packages = [Package(a.name, "", a.description) for a in APP_CATALOG]
        self._render(self.packages)

    def _schedule(self, text: str):
        self._seq += 1
        if not text.strip():
            self.debounce.stop()
            self._show_popular()
            return
        self.heading.setText("Searching…")
        self.debounce.start()

    def _run_search(self):
        job = _Search(self.client, self.search.text(), self._seq)
        job.signals.done.connect(self._on_results, Qt.ConnectionType.QueuedConnection)
        QThreadPool.globalInstance().start(job)

    def _on_results(self, seq: int, packages: list, error: str, offline: bool):
        if seq != self._seq:
            return
        query = self.search.text().strip()
        if error:
            self.heading.setText("Couldn't reach search.nixos.org. Check your internet connection."
                                 if offline else "The app search isn't working right now.")
            self._render([])
            return
        self.packages = packages[:RESULT_LIMIT]
        self.heading.setText(f"Results for “{query}”" if self.packages else f"No apps match “{query}”")
        self._render(self.packages)

    def _request(self, package: Package):
        dialog = RequestDialog(package, self.device, self)
        if dialog.exec():
            self.client.create_request(self.device, package.name, self.username,
                                       dialog.reason.toPlainText().strip())
            self.message.emit(f"Requested {package.name}. You'll see the answer under My requests.")
            self._render(self.packages)
            self.requested.emit()

    def refresh(self):
        self._render(self.packages)


class MyRequestsPage(QWidget):
    def __init__(self, client: NixyncClient, device: str, username: str):
        super().__init__()
        self.client, self.device, self.username = client, device, username
        page, self.layout_ = scroll_page()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(page)
        self.refresh()

    def refresh(self):
        clear_layout(self.layout_)
        self.layout_.addWidget(page_header("My requests", f"Apps you've asked for on {self.device}."))
        mine = [r for r in self.client.list_requests()
                if r.machine == self.device and r.requested_by == self.username]
        if not mine:
            empty = QLabel("You haven't requested any apps yet. Find one under Apps.")
            empty.setObjectName("Muted")
            self.layout_.addWidget(empty)
        colors = {RequestStatus.PENDING: style.MUTED, RequestStatus.APPROVED: style.OK,
                  RequestStatus.DECLINED: style.PROBLEM}
        words = {RequestStatus.PENDING: "Waiting for approval", RequestStatus.APPROVED: "Approved",
                 RequestStatus.DECLINED: "Declined"}
        for request in mine:
            card = Panel("Card")
            row = QHBoxLayout()
            row.setSpacing(12)
            row.addWidget(app_tile(request.app, 36))
            text = QVBoxLayout()
            text.setSpacing(2)
            name = QLabel(request.app)
            name.setStyleSheet("font-weight: 600; border: none;")
            text.addWidget(name)
            meta = QLabel(f"Requested {ago(request.when)}" + (f" · “{request.reason}”" if request.reason else ""))
            meta.setObjectName("Muted")
            meta.setStyleSheet("border: none;")
            text.addWidget(meta)
            row.addLayout(text, 1)
            row.addWidget(status_text(colors[request.status], words[request.status]))
            card.body.addLayout(row)
            self.layout_.addWidget(card)
        self.layout_.addStretch()

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()


class ClientWindow(MainWindow):
    PAGES = ["Apps", "My requests", "Users", "Settings"]

    def __init__(self, config: Config, username: str, device: str):
        self.device_name = device  # needed by _make_pages, which the base __init__ calls
        super().__init__(config, username)
        self.setWindowTitle(f"Nixync · {device}")

    def _make_pages(self) -> list[QWidget]:
        machine = self.client.get_machine(self.device_name)
        self.store = StorePage(self.client, self.device_name, self.username)
        self.my_requests = MyRequestsPage(self.client, self.device_name, self.username)
        self.store.message.connect(self.show_message)
        self.store.requested.connect(self._update_counts)

        users_page, users_layout = scroll_page()
        users_layout.addWidget(page_header("Users", f"People who can log in to {self.device_name}."))
        users = UsersPanel(self.client, machine, can_grant_admin=False, current_user=self.username, show_title=False)
        users.message.connect(self.show_message)
        users_layout.addWidget(users)
        users_layout.addStretch()

        settings_page, settings_layout = scroll_page()
        settings_layout.addWidget(page_header("Settings", f"{self.device_name} · {machine.preset}"))
        gauges = Panel()
        row = QHBoxLayout()
        row.setSpacing(24)
        disk = ""
        if machine.disk_used_gb is not None and machine.disk_total_gb:
            disk = f"{machine.disk_used_gb:.0f} / {machine.disk_total_gb:.0f} GB"
        for gauge in (RingGauge("CPU", machine.cpu_percent), RingGauge("RAM", machine.ram_percent),
                      RingGauge("Disk", machine.disk_percent, disk)):
            row.addWidget(gauge)
        row.addStretch()
        last = machine.last_successful_build
        info = QLabel(f"NixOS {machine.nixos_version}" + (f" · last updated {ago(last.finished)}" if last else ""))
        info.setObjectName("Muted")
        row.addWidget(info, 0, Qt.AlignmentFlag.AlignBottom)
        gauges.body.addLayout(row)
        settings_layout.addWidget(gauges)
        panel = SettingsPanel(self.device_name, machine.settings, admin=False)
        panel.applied.connect(self._apply_settings)
        settings_layout.addWidget(panel)
        settings_layout.addStretch()

        return [self.store, self.my_requests, users_page, settings_page]

    def _after_build(self):
        self._update_counts()

    def _update_counts(self):
        mine = [r for r in self.client.pending_requests(self.device_name) if r.requested_by == self.username]
        item = self.sidebar.item(self.PAGES.index("My requests"))
        item.setText(f"My requests ({len(mine)})" if mine else "My requests")

    def _apply_settings(self, settings):
        try:
            self.client.save_settings(self.device_name, settings)
        except ApiError as e:
            self.show_message(f"Couldn't apply settings: {e}")
            return
        self.show_message(f"Applying your settings to {self.device_name}…")
