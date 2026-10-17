"""The three pages of the device app: Apps, My requests, This machine."""

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

import nixos_search
from nixync_client import NixyncApiError
from nixync_ui import style
from nixync_ui.widgets import (
    Panel, RingGauge, ago, cancel_box, clear_layout, page_header, primary_button,
    status_text,
)

RESULT_LIMIT = 20
SEARCH_DEBOUNCE_MS = 300


def scroll_page() -> tuple[QWidget, QVBoxLayout]:
    page = QWidget()
    outer = QVBoxLayout(page)
    outer.setContentsMargins(0, 0, 0, 0)
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.Shape.NoFrame)
    outer.addWidget(area)
    body = QWidget()
    layout = QVBoxLayout(body)
    layout.setContentsMargins(28, 24, 28, 24)
    layout.setSpacing(18)
    area.setWidget(body)
    return page, layout


class _SearchSignals(QObject):
    done = Signal(int, list, str)


class _Search(QRunnable):
    """nixpkgs search off the UI thread; it is a network call to search.nixos.org."""

    def __init__(self, query: str, index: str, sequence: int):
        super().__init__()
        self.query, self.index, self.sequence = query, index, sequence
        self.signals = _SearchSignals()

    def run(self):
        try:
            packages = nixos_search.search(self.query, self.index)[:RESULT_LIMIT]
            self.signals.done.emit(self.sequence, packages, "")
        except Exception as problem:  # noqa: BLE001 — surfaced to the user, not swallowed
            self.signals.done.emit(self.sequence, [], str(problem))


class RequestDialog(QDialog):
    """Why someone wants an app. The reason is what an admin decides on."""

    def __init__(self, app: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Request {app}")
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        title = QLabel(f"Request {app}")
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        intro = QLabel("Your administrator decides whether to install it on this machine.")
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.reason = QPlainTextEdit()
        self.reason.setPlaceholderText("What do you need it for?")
        self.reason.setFixedHeight(96)
        layout.addWidget(self.reason)
        buttons = cancel_box()
        self.send = buttons.addButton("Send request", QDialogButtonBox.ButtonRole.AcceptRole)
        self.send.setProperty("primary", True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def text(self) -> str:
        return self.reason.toPlainText().strip()


class AppsPage(QWidget):
    """Search nixpkgs and ask for something this machine does not have."""

    requested = Signal(str, str)  # app, reason

    def __init__(self, search_index: str):
        super().__init__()
        self.search_index = search_index
        self.installed: set[str] = set()
        self.pending: set[str] = set()
        self._sequence = 0

        page, self.layout_ = scroll_page()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(page)

        self.layout_.addWidget(page_header("Apps", "Ask your administrator to install software"))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search nixpkgs — try “blender”")
        self.search.textChanged.connect(self._schedule)
        self.layout_.addWidget(self.search)

        self.results = QVBoxLayout()
        self.results.setSpacing(10)
        self.layout_.addLayout(self.results)
        self.layout_.addStretch()

        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.timeout.connect(self._run_search)
        self._show_message("Search for an app to get started.")

    def set_state(self, installed: set[str], pending: set[str]) -> None:
        self.installed, self.pending = installed, pending

    def _schedule(self):
        self.debounce.start(SEARCH_DEBOUNCE_MS)

    def _run_search(self):
        query = self.search.text().strip()
        if not query:
            self._show_message("Search for an app to get started.")
            return
        self._sequence += 1
        self._show_message("Searching…")
        job = _Search(query, self.search_index, self._sequence)
        job.signals.done.connect(self._on_results, Qt.ConnectionType.QueuedConnection)
        QThreadPool.globalInstance().start(job)

    def _on_results(self, sequence: int, packages: list, error: str):
        # Results from an earlier keystroke would overwrite newer ones.
        if sequence != self._sequence:
            return
        if error:
            self._show_message(f"Couldn't search: {error}")
            return
        if not packages:
            self._show_message("Nothing found.")
            return
        clear_layout(self.results)
        for package in packages:
            self.results.addWidget(self._card(package))

    def _show_message(self, text: str):
        clear_layout(self.results)
        label = QLabel(text)
        label.setObjectName("Muted")
        self.results.addWidget(label)

    def _card(self, package) -> Panel:
        panel = Panel()
        row = QHBoxLayout()
        left = QVBoxLayout()
        left.setSpacing(2)
        name = QLabel(package.name)
        name.setStyleSheet("font-weight: 600; border: none;")
        left.addWidget(name)
        if package.description:
            blurb = QLabel(package.description)
            blurb.setObjectName("Muted")
            blurb.setWordWrap(True)
            left.addWidget(blurb)
        row.addLayout(left, 1)

        if package.name in self.installed:
            row.addWidget(status_text(style.OK, "Installed"))
        elif package.name in self.pending:
            row.addWidget(status_text(style.PENDING, "Requested"))
        else:
            ask = primary_button("Request")
            ask.clicked.connect(lambda _=False, p=package.name: self._ask(p))
            row.addWidget(ask)
        panel.body.addLayout(row)
        return panel

    def _ask(self, app: str):
        dialog = RequestDialog(app, self)
        if dialog.exec():
            self.requested.emit(app, dialog.text)


class MyRequestsPage(QWidget):
    """What this user asked for, and what the admin decided."""

    TONES = {"pending": style.PENDING, "approved": style.OK, "declined": style.PROBLEM}

    def __init__(self):
        super().__init__()
        page, self.layout_ = scroll_page()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(page)
        self.layout_.addWidget(page_header("My requests"))
        self.rows = QVBoxLayout()
        self.rows.setSpacing(10)
        self.layout_.addLayout(self.rows)
        self.layout_.addStretch()

    def show_requests(self, requests: list) -> None:
        clear_layout(self.rows)
        if not requests:
            empty = QLabel("You haven't asked for anything yet.")
            empty.setObjectName("Muted")
            self.rows.addWidget(empty)
            return
        for request in requests:
            panel = Panel()
            row = QHBoxLayout()
            left = QVBoxLayout()
            left.setSpacing(2)
            name = QLabel(request.app)
            name.setStyleSheet("font-weight: 600; border: none;")
            left.addWidget(name)
            if request.reason:
                why = QLabel(request.reason)
                why.setObjectName("Muted")
                why.setWordWrap(True)
                left.addWidget(why)
            row.addLayout(left, 1)
            tone = self.TONES.get(request.status, style.MUTED)
            row.addWidget(status_text(tone, request.status.capitalize()))
            panel.body.addLayout(row)
            self.rows.addWidget(panel)


class MachinePage(QWidget):
    """What this machine is and how it is doing."""

    def __init__(self):
        super().__init__()
        page, self.layout_ = scroll_page()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(page)
        self.body = QVBoxLayout()
        self.layout_.addLayout(self.body)
        self.layout_.addStretch()

    def show_machine(self, machine, agent_id: str, error: str = "") -> None:
        clear_layout(self.body)
        if machine is None:
            # Whoever is sitting at this machine is not an administrator. Lead with a
            # plain sentence and keep the transport error underneath for whoever is.
            self.body.addWidget(page_header("This machine"))
            headline = QLabel("Can't reach the Nixync server.")
            headline.setWordWrap(True)
            self.body.addWidget(headline)
            hint = QLabel(
                "Your machine still works normally — only Nixync is unreachable. "
                "If this lasts, tell your administrator."
            )
            hint.setObjectName("Muted")
            hint.setWordWrap(True)
            self.body.addWidget(hint)
            if error:
                detail = QLabel(error)
                detail.setObjectName("Muted")
                detail.setWordWrap(True)
                detail.setStyleSheet("font-size: 11px;")
                self.body.addWidget(detail)
            return

        online = machine.online
        self.body.addWidget(page_header(machine.name, machine.preset or "No preset"))
        header = QHBoxLayout()
        header.addWidget(
            status_text(style.OK if online else style.OFFLINE,
                        "Managed by Nixync" if online else "Agent not connected")
        )
        header.addStretch()
        self.body.addLayout(header)

        overview = Panel()
        grid = QGridLayout()
        grid.setHorizontalSpacing(32)
        grid.setVerticalSpacing(12)
        last = machine.last_apply_status
        grid.addWidget(_fact("Last change", {
            "applied": "Applied", "failed": "Failed", "pending": "Waiting to apply",
        }.get(last, "None yet")), 0, 0)
        grid.addWidget(
            _fact("Last reported", ago(machine.metrics_reported_at) if machine.metrics_reported_at else "Never"),
            0, 1,
        )
        grid.addWidget(_fact("Agent ID", agent_id), 1, 0, 1, 2)
        row = QHBoxLayout()
        row.addLayout(grid, 1)
        ram = None
        if machine.ram_used_mb is not None and machine.ram_total_mb:
            ram = 100 * machine.ram_used_mb / machine.ram_total_mb
        disk = None
        if machine.disk_used_gb is not None and machine.disk_total_gb:
            disk = 100 * machine.disk_used_gb / machine.disk_total_gb
        for gauge in (RingGauge("CPU", machine.cpu_percent), RingGauge("RAM", ram),
                      RingGauge("Disk", disk)):
            row.addWidget(gauge, 0, Qt.AlignmentFlag.AlignVCenter)
        overview.body.addLayout(row)
        self.body.addWidget(overview)

        if last == "failed" and machine.last_apply_message:
            problem = Panel()
            problem.body.addWidget(status_text(style.PROBLEM, "The last change didn't apply"))
            detail = QPlainTextEdit(machine.last_apply_message)
            detail.setReadOnly(True)
            detail.setFixedHeight(110)
            problem.body.addWidget(detail)
            self.body.addWidget(problem)

        apps = Panel()
        title = QLabel("Installed by Nixync")
        title.setStyleSheet("font-size: 16px; font-weight: 600; border: none;")
        apps.body.addWidget(title)
        packages = machine.config.packages
        listing = QLabel(", ".join(packages) if packages else "Nothing yet.")
        listing.setObjectName("" if packages else "Muted")
        listing.setWordWrap(True)
        apps.body.addWidget(listing)
        self.body.addWidget(apps)


def _fact(label: str, value: str) -> QWidget:
    box = QWidget()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(2)
    name = QLabel(label)
    name.setObjectName("Muted")
    name.setStyleSheet("border: none;")
    text = QLabel(value)
    text.setStyleSheet("font-weight: 600; border: none;")
    text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    layout.addWidget(name)
    layout.addWidget(text)
    return box
