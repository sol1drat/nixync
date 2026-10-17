from PySide6.QtCore import QObject, QRunnable, QSettings, QSize, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QListWidget, QMainWindow, QPushButton, QStackedWidget, QToolButton, QVBoxLayout,
    QWidget,
)

from nixync_front import style
from nixync_front.api import ApiError, NixyncClient
from nixync_front.config import Config
from nixync_front.dialogs import AddAppsDialog, AddMachineDialog, UndoUpdateDialog
from nixync_front.pages import MachineConfigPage, MachinesPage, PresetsPage, RequestsPage, UpdatesPage
from nixync_front.widgets import dot, moon_icon, panel_icon, sun_icon


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
    PAGES = ["Devices", "Requests", "Presets", "Updates"]
    SIDEBAR_WIDTH = 230

    def __init__(self, config: Config):
        super().__init__()
        self.config = config
        self.client = NixyncClient(config)
        self.setWindowTitle("Nixync")
        self.setWindowIcon(QIcon(str(style.ICONS / "app-icon.png")))
        self.settings = QSettings("Nixync", "Nixync")
        self.resize(1360, 860)
        self._last_status: tuple[bool, str] | None = None

        self._build_ui()
        QShortcut(QKeySequence("Ctrl+B"), self, activated=self.toggle_sidebar)

        self.connection_dot = dot(style.OFFLINE, 8)
        self.connection_label = QLabel(f"Connecting to {config.server_url}")
        status = QWidget()
        status_layout = QHBoxLayout(status)
        status_layout.setContentsMargins(6, 0, 6, 0)
        status_layout.addWidget(self.connection_dot)
        status_layout.addWidget(self.connection_label)
        self.statusBar().addWidget(status, 1)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.check_server)
        self.timer.start(config.poll_interval_seconds * 1000)
        QTimer.singleShot(0, self.check_server)

    def _build_ui(self):
        """Sidebar and pages. Rebuilt in place by toggle_theme so every color and icon updates."""
        self.sidebar = QListWidget()
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.sidebar.addItems(self.PAGES)

        self.machines = MachinesPage(self.client)
        self.requests = RequestsPage(self.client)
        self.presets = PresetsPage(self.client)
        self.updates = UpdatesPage(self.client)
        # Not in the sidebar; reached from a machine card's settings button.
        self.machine_config = MachineConfigPage(self.client)
        self.stack = QStackedWidget()
        for page in (self.machines, self.requests, self.presets, self.updates, self.machine_config):
            self.stack.addWidget(page)

        self.sidebar.currentRowChanged.connect(self.stack.setCurrentIndex)
        # Clicking the current entry again (e.g. Devices while a device's settings are open)
        # doesn't change the row, so switch pages on click too.
        self.sidebar.itemClicked.connect(lambda item: self.stack.setCurrentIndex(self.sidebar.row(item)))
        self.sidebar.setCurrentRow(0)

        self.machines.add_machine_requested.connect(self.open_add_machine)
        self.machines.change_presets_requested.connect(lambda: self.go_to("Presets"))
        self.machines.configure_requested.connect(self.open_machine_config)
        self.machines.requests_requested.connect(self.open_requests)
        self.machines.add_apps_requested.connect(self.open_add_apps)
        self.machine_config.requests_requested.connect(self.open_requests)
        self.requests.machine_requested.connect(self.open_machine_config)
        self.requests.changed.connect(self.update_request_counts)
        self.requests.message.connect(lambda text: self.statusBar().showMessage(text, 5000))
        self.machine_config.back_requested.connect(lambda: self.stack.setCurrentWidget(self.machines))
        self.machine_config.undo_requested.connect(self.open_undo)
        self.machine_config.apply_requested.connect(self.apply_machine_apps)
        self.presets.deploy_requested.connect(lambda _preset: self.go_to("Updates"))
        self.updates.undo_requested.connect(self.open_undo)
        self.updates.configure_requested.connect(self.open_machine_config)
        self.updates.message.connect(lambda text: self.statusBar().showMessage(text, 5000))

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.sidebar_column = self._sidebar_column()
        self.sidebar_rail = self._sidebar_rail()
        layout.addWidget(self.sidebar_column)
        layout.addWidget(self.sidebar_rail)
        self.set_sidebar_visible(self.settings.value("sidebar/visible", True, type=bool))
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)  # deletes the previous one when rebuilding
        self.update_request_counts()

    def toggle_theme(self):
        theme = "light" if style.IS_DARK else "dark"
        self.settings.setValue("appearance/theme", theme)

        # Remember where the user is, then rebuild the pages in the new colors.
        on_device = self.stack.currentWidget() is self.machine_config and self.machine_config.machine
        device = self.machine_config.machine.name if on_device else None
        index = self.stack.currentIndex()
        request_filter = self.requests.machine_filter

        was_active = self.isActiveWindow()
        self.setUpdatesEnabled(False)
        style.apply(QApplication.instance(), theme)
        self._build_ui()
        if request_filter:
            self.requests.filter_machine(request_filter)
        if device:
            self.open_machine_config(device)
        else:
            self.sidebar.setCurrentRow(min(index, len(self.PAGES) - 1))
            self.stack.setCurrentIndex(index)
        if self._last_status:
            self._on_status(*self._last_status)
        else:
            self.connection_dot.setStyleSheet(f"background: {style.OFFLINE}; border-radius: 4px;")
        self.setUpdatesEnabled(True)
        # Rebuilding deleted the focused widget (the theme button), which drops the window's
        # active state; restore it so keyboard shortcuts like Ctrl+B keep working.
        if was_active:
            self.activateWindow()
            self.stack.setFocus()

    def _sidebar_column(self) -> QWidget:
        column = QWidget()
        column.setObjectName("SidebarColumn")
        column.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        column.setFixedWidth(self.SIDEBAR_WIDTH)
        layout = QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        brand = QWidget()
        brand_layout = QHBoxLayout(brand)
        brand_layout.setContentsMargins(18, 18, 16, 8)
        brand_layout.setSpacing(10)
        logo = QLabel()
        pixmap = QPixmap(str(style.logo_path()))
        ratio = self.devicePixelRatioF()
        logo_px = pixmap.scaled(int(36 * ratio), int(36 * ratio), Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation)
        logo_px.setDevicePixelRatio(ratio)
        logo.setPixmap(logo_px)
        name = QLabel("Nixync")
        name.setObjectName("BrandName")
        brand_layout.addWidget(logo)
        brand_layout.addWidget(name)
        brand_layout.addStretch()
        brand_layout.addWidget(self._sidebar_button("Hide sidebar (Ctrl+B)"))
        layout.addWidget(brand)
        layout.addWidget(self.sidebar, 1)

        theme = QPushButton("  Light mode" if style.IS_DARK else "  Dark mode")
        theme.setObjectName("ThemeToggle")
        theme.setIcon(sun_icon(style.MUTED) if style.IS_DARK else moon_icon(style.MUTED))
        theme.setIconSize(QSize(18, 18))
        theme.setToolTip("Switch to the light theme" if style.IS_DARK else "Switch to the dark theme")
        theme.clicked.connect(self.toggle_theme)
        footer = QVBoxLayout()
        footer.setContentsMargins(10, 0, 10, 14)
        footer.addWidget(theme)
        layout.addLayout(footer)
        return column

    def _sidebar_rail(self) -> QWidget:
        """Slim strip shown instead of the sidebar while it's hidden, with a button to bring it back."""
        rail = QWidget()
        rail.setObjectName("SidebarColumn")
        rail.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        rail.setFixedWidth(52)
        layout = QVBoxLayout(rail)
        layout.setContentsMargins(0, 20, 0, 0)
        layout.addWidget(self._sidebar_button("Show sidebar (Ctrl+B)"), 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch()
        theme = QToolButton()
        theme.setObjectName("SidebarToggle")
        theme.setIcon(sun_icon(style.MUTED) if style.IS_DARK else moon_icon(style.MUTED))
        theme.setIconSize(QSize(18, 18))
        theme.setToolTip("Switch to the light theme" if style.IS_DARK else "Switch to the dark theme")
        theme.clicked.connect(self.toggle_theme)
        layout.addWidget(theme, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addSpacing(14)
        return rail

    def _sidebar_button(self, tip: str) -> QToolButton:
        button = QToolButton()
        button.setObjectName("SidebarToggle")
        button.setIcon(panel_icon(style.MUTED))
        button.setIconSize(QSize(18, 18))
        button.setToolTip(tip)
        button.clicked.connect(self.toggle_sidebar)
        return button

    def toggle_sidebar(self):
        self.set_sidebar_visible(not self.sidebar_column.isVisible())

    def set_sidebar_visible(self, visible: bool):
        self.sidebar_column.setVisible(visible)
        self.sidebar_rail.setVisible(not visible)
        self.settings.setValue("sidebar/visible", visible)

    def go_to(self, name: str):
        row = self.PAGES.index(name)
        self.sidebar.setCurrentRow(row)
        # The row may already be selected (e.g. Devices while a device's settings are open).
        self.stack.setCurrentIndex(row)

    def open_requests(self, machine: str | None = None):
        self.requests.filter_machine(machine)
        self.go_to("Requests")
        self.stack.setCurrentWidget(self.requests)

    def update_request_counts(self):
        pending = len(self.client.pending_requests())
        item = self.sidebar.item(self.PAGES.index("Requests"))
        item.setText(f"Requests ({pending})" if pending else "Requests")
        self.machines.refresh()

    def open_machine_config(self, name: str):
        self.machine_config.show_machine(name)
        # A device's settings belong under Devices in the sidebar.
        self.sidebar.blockSignals(True)
        self.sidebar.setCurrentRow(self.PAGES.index("Devices"))
        self.sidebar.blockSignals(False)
        self.stack.setCurrentWidget(self.machine_config)

    def apply_machine_apps(self, name: str, apps: list):
        # TODO: send the machine's new app list to the server and start a build.
        self.statusBar().showMessage(f"Updating {name}: {', '.join(apps) or 'no extra apps'}", 5000)

    def open_add_apps(self, devices: list):
        if not devices:
            return
        dialog = AddAppsDialog(self.client, devices, self)
        if not dialog.exec():
            return
        # TODO: the server should build each device after this.
        added = self.client.add_apps(devices, dialog.apps)
        parts = []
        for app in dialog.apps:
            got = [d for d in devices if app in added[d]]
            had = [d for d in devices if app not in added[d]]
            if not got:
                parts.append(f"every selected device already has {app}")
            elif had:
                parts.append(f"{app} to {len(got)} of {len(devices)} ({', '.join(had)} already had it)")
            else:
                parts.append(f"{app} to {len(got)} device{'' if len(got) == 1 else 's'}")
        self.statusBar().showMessage("Adding " + "; ".join(parts) + ".", 10000)
        self.machines.clear_selected()

    def open_add_machine(self):
        dialog = AddMachineDialog([r.name for r in self.client.list_presets()], self)
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
        self._last_status = (ok, detail)
        color = style.OK if ok else style.PROBLEM
        self.connection_dot.setStyleSheet(f"background: {color}; border-radius: 4px;")
        if ok:
            self.connection_label.setText(f"Connected to {detail} ({self.config.server_url})")
        else:
            self.connection_label.setText(f"Can't reach server at {self.config.server_url}")
            self.connection_label.setToolTip(detail)
