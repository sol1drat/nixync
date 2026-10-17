from PySide6.QtCore import QObject, QRunnable, QSettings, QSize, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QListWidget, QMainWindow, QMessageBox, QPushButton, QStackedWidget, QToolButton,
    QVBoxLayout, QWidget,
)

from nixync_ui import style
from nixync_front.api import ApiError, NixyncClient
from nixync_front.config import Config
from nixync_front.dialogs import AddAppsDialog, AddMachineDialog, UndoUpdateDialog
from nixync_front.pages import MachineConfigPage, MachinesPage, PresetsPage, RequestsPage, UpdatesPage
from nixync_ui.widgets import dot, moon_icon, panel_icon, safe_emit, sun_icon, themed_icon


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
            safe_emit(self.signals.done, True, status.get("hostname", "server"))
        except ApiError as e:
            safe_emit(self.signals.done, False, str(e))


class MainWindow(QMainWindow):
    PAGES = ["Devices", "Requests", "Presets", "Updates"]
    SIDEBAR_WIDTH = 230

    sign_out_requested = Signal()

    def __init__(self, config: Config, username: str = ""):
        super().__init__()
        self.username = username
        self.config = config
        self.client = NixyncClient(config)
        self.setWindowTitle("Nixync")
        self.setWindowIcon(QIcon(str(style.ICONS / "app-icon.png")))
        # Signing out closes this window; make sure it's really gone (timers, polling).
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.settings = QSettings("Nixync", "Nixync")
        self.resize(1360, 860)
        self._last_status: tuple[bool, str] | None = None

        self._build_ui()
        QShortcut(QKeySequence("Ctrl+B"), self, activated=self.toggle_sidebar)

        self.connection_dot = dot(style.OFFLINE, 8)
        style.themed(self.connection_dot, self._paint_connection_dot)
        self.connection_label = QLabel(f"Connecting to {config.server_url}")
        status = QWidget()
        status_layout = QHBoxLayout(status)
        status_layout.setContentsMargins(6, 0, 6, 0)
        status_layout.addWidget(self.connection_dot)
        status_layout.addWidget(self.connection_label)
        self.statusBar().addWidget(status, 1)
        style.styled(self.statusBar())

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.check_server)
        self.timer.start(config.poll_interval_seconds * 1000)
        QTimer.singleShot(0, self.check_server)

    def _build_ui(self):
        """Sidebar and pages. Theme switches restyle these in place (see style.themed)."""
        self.sidebar = QListWidget()
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.sidebar.addItems(self.PAGES)

        pages = self._make_pages()  # one per PAGES entry, in order, plus any extra pages after
        self.stack = QStackedWidget()
        for page in pages:
            self.stack.addWidget(page)

        self.sidebar.currentRowChanged.connect(self.stack.setCurrentIndex)
        # Clicking the current entry again (e.g. Devices while a device's settings are open)
        # doesn't change the row, so switch pages on click too.
        self.sidebar.itemClicked.connect(lambda item: self.stack.setCurrentIndex(self.sidebar.row(item)))
        self.sidebar.setCurrentRow(0)

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
        self.setCentralWidget(central)
        # Each part carries the theme stylesheet itself (see style.styled); hidden pages are
        # restyled when they're shown, so a theme switch only touches what's on screen.
        for part in (self.sidebar_column, self.sidebar_rail):
            style.styled(part)
        for page in pages:
            style.styled(page, lazy=True)
        self.stack.currentChanged.connect(lambda _i: style.restyle_if_stale(self.stack.currentWidget()))
        self._after_build()

    def show_message(self, text: str):
        self.statusBar().showMessage(text, 5000)

    def _make_pages(self) -> list[QWidget]:
        self.machines = MachinesPage(self.client)
        self.requests = RequestsPage(self.client)
        self.presets = PresetsPage(self.client)
        self.updates = UpdatesPage(self.client)
        # Not in the sidebar; reached from a device's settings button.
        self.machine_config = MachineConfigPage(self.client)

        self.machines.add_machine_requested.connect(self.open_add_machine)
        self.machines.change_presets_requested.connect(lambda: self.go_to("Presets"))
        self.machines.configure_requested.connect(self.open_machine_config)
        self.machines.requests_requested.connect(self.open_requests)
        self.machines.add_apps_requested.connect(self.open_add_apps)
        self.machine_config.requests_requested.connect(self.open_requests)
        self.requests.machine_requested.connect(self.open_machine_config)
        self.requests.changed.connect(self.update_request_counts)
        self.requests.message.connect(self.show_message)
        self.machine_config.back_requested.connect(lambda: self.stack.setCurrentWidget(self.machines))
        self.machine_config.undo_requested.connect(self.open_undo)
        self.machine_config.apply_requested.connect(self.apply_machine_apps)
        self.machine_config.remove_requested.connect(self.remove_machine)
        self.machine_config.message.connect(self.show_message)
        self.presets.deploy_requested.connect(lambda _preset: self.go_to("Updates"))
        self.updates.undo_requested.connect(self.open_undo)
        self.updates.configure_requested.connect(self.open_machine_config)
        self.updates.message.connect(self.show_message)
        return [self.machines, self.requests, self.presets, self.updates, self.machine_config]

    def _after_build(self):
        self.update_request_counts()

    def toggle_theme(self):
        """Switch theme in place: restyle, and let themed widgets redraw their icons and colors."""
        theme = "light" if style.IS_DARK else "dark"
        self.settings.setValue("appearance/theme", theme)
        style.apply(QApplication.instance(), theme)

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

        def paint_logo():
            ratio = self.devicePixelRatioF()
            pixmap = QPixmap(str(style.logo_path())).scaled(
                int(36 * ratio), int(36 * ratio), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
            pixmap.setDevicePixelRatio(ratio)
            logo.setPixmap(pixmap)
        style.themed(logo, paint_logo)
        name = QLabel("Nixync")
        name.setObjectName("BrandName")
        brand_layout.addWidget(logo)
        brand_layout.addWidget(name)
        brand_layout.addStretch()
        brand_layout.addWidget(self._sidebar_button("Hide sidebar (Ctrl+B)"))
        layout.addWidget(brand)
        layout.addWidget(self.sidebar, 1)

        theme = QPushButton()
        theme.setObjectName("ThemeToggle")
        theme.setIconSize(QSize(18, 18))
        theme.clicked.connect(self.toggle_theme)
        style.themed(theme, lambda: (theme.setText("  Light mode" if style.IS_DARK else "  Dark mode"),
                                     self._paint_theme_button(theme)))
        footer = QVBoxLayout()
        footer.setContentsMargins(10, 0, 10, 14)
        footer.setSpacing(4)
        footer.addWidget(theme)
        if self.username:
            account = QHBoxLayout()
            account.setContentsMargins(12, 6, 4, 0)
            who = QLabel(self.username)
            who.setObjectName("Muted")
            who.setToolTip(f"Signed in to {self.config.server_url}")
            account.addWidget(who, 1)
            sign_out = QPushButton("Sign out")
            sign_out.setProperty("link", True)
            sign_out.clicked.connect(self.sign_out_requested)
            account.addWidget(sign_out)
            footer.addLayout(account)
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
        theme.setIconSize(QSize(18, 18))
        theme.clicked.connect(self.toggle_theme)
        style.themed(theme, lambda: self._paint_theme_button(theme))
        layout.addWidget(theme, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addSpacing(14)
        return rail

    @staticmethod
    def _paint_theme_button(button):
        button.setIcon(sun_icon(style.MUTED) if style.IS_DARK else moon_icon(style.MUTED))
        button.setToolTip("Switch to the light theme" if style.IS_DARK else "Switch to the dark theme")

    def _sidebar_button(self, tip: str) -> QToolButton:
        button = QToolButton()
        button.setObjectName("SidebarToggle")
        themed_icon(button, panel_icon)
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
        try:
            added, removed = self.client.set_apps(name, apps)
        except ApiError as e:
            self.statusBar().showMessage(f"Couldn't update {name}: {e}", 10000)
            return
        parts = []
        if added:
            parts.append(f"adding {', '.join(added)}")
        if removed:
            parts.append(f"removing {', '.join(removed)}")
        detail = "; ".join(parts) if parts else "no changes"
        self.statusBar().showMessage(f"Updating {name}: {detail}", 10000)
        self.machine_config.show_machine(name)
        self.machines.refresh()

    def open_add_apps(self, devices: list):
        if not devices:
            return
        dialog = AddAppsDialog(self.client, devices, self)
        if not dialog.exec():
            return
        try:
            added = self.client.add_apps(devices, dialog.apps)
        except ApiError as e:
            self.statusBar().showMessage(f"Couldn't add apps: {e}", 10000)
            return
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
        try:
            presets = [r.name for r in self.client.list_presets()]
        except ApiError as e:
            self.statusBar().showMessage(f"Couldn't load presets: {e}", 10000)
            return
        dialog = AddMachineDialog(presets, self)
        if not dialog.exec():
            return

        values = dialog.values()
        name = values["name"]
        try:
            self.client.add_machine(
                name, preset=values["preset"], address=values["address"]
            )
            machine_id = self.client.machine_id(name)
        except ApiError as e:
            self.statusBar().showMessage(f"Couldn't add {name}: {e}", 10000)
            return

        # The operator needs this id to point that device's agent at the server, and
        # there is no provisioning channel yet — so show it long enough to copy.
        self.statusBar().showMessage(f"Added {name}. Agent id: {machine_id}", 60000)
        self.machines.refresh()

    def remove_machine(self, name: str):
        answer = QMessageBox.question(
            self,
            "Remove device",
            f"Remove {name} from the fleet?\n\n"
            "Its agent will no longer be able to connect. Configuration on the "
            "device itself is not changed.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.client.remove_machine(name)
        except ApiError as e:
            self.statusBar().showMessage(f"Couldn't remove {name}: {e}", 10000)
            return
        self.statusBar().showMessage(f"Removed {name}", 5000)
        self.stack.setCurrentWidget(self.machines)
        self.machines.refresh()

    def open_undo(self, host: str):
        if UndoUpdateDialog(host, self).exec():
            # TODO: ask the server to roll the host back.
            self.statusBar().showMessage(f"Undoing update on {host}", 5000)

    def check_server(self):
        job = _StatusCheck(self.client)
        job.signals.done.connect(self._on_status, Qt.ConnectionType.QueuedConnection)
        QThreadPool.globalInstance().start(job)

    def _paint_connection_dot(self):
        ok = self._last_status[0] if self._last_status else None
        color = style.OFFLINE if ok is None else style.OK if ok else style.PROBLEM
        self.connection_dot.setStyleSheet(f"background: {color}; border-radius: 4px;")

    def _on_status(self, ok: bool, detail: str):
        self._last_status = (ok, detail)
        self._paint_connection_dot()
        if ok:
            self.connection_label.setText(f"Connected to {detail} ({self.config.server_url})")
        else:
            self.connection_label.setText(f"Can't reach server at {self.config.server_url}")
            self.connection_label.setToolTip(detail)

    def closeEvent(self, event):
        self.timer.stop()  # no more server polling once the window is closed
        super().closeEvent(event)
