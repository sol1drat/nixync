from datetime import datetime

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QHeaderView, QLabel,
    QPlainTextEdit, QPushButton, QScrollArea, QTableWidget, QToolButton, QVBoxLayout, QWidget,
)

from nixync_front import style
from nixync_front.api import NixyncClient
from nixync_front.dialogs.ask_ai import AskAIDialog
from nixync_front.sample_data import Build, Health, Machine, MachineError, Preset
from nixync_front.widgets import SegmentButton, ago, centered, gear_icon, page_header, status_text, themed_icon

ROW_HEIGHT = 50
RECENT_LIMIT = 15


def section_title(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet("font-size: 16px; font-weight: 600;")
    return label


def data_table(columns: list[str], stretch: int) -> QTableWidget:
    """A table in the same style as the Devices list; sized to its rows, so the page scrolls instead."""
    table = QTableWidget(0, len(columns))
    table.setObjectName("DeviceTable")
    table.setHorizontalHeaderLabels([c.upper() for c in columns])
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
    table.setShowGrid(False)
    table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    header = table.horizontalHeader()
    header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    header.setHighlightSections(False)
    for col in range(len(columns)):
        header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(stretch, QHeaderView.ResizeMode.Stretch)
    return table


def fit_height(table: QTableWidget):
    rows = max(table.rowCount(), 1)
    table.setFixedHeight(table.horizontalHeader().sizeHint().height() + rows * ROW_HEIGHT + 2)


def empty_row(table: QTableWidget, text: str):
    table.setRowCount(1)
    label = QLabel(text)
    label.setObjectName("Muted")
    table.setSpan(0, 0, 1, table.columnCount())
    table.setCellWidget(0, 0, centered(label, Qt.AlignmentFlag.AlignCenter))


def when_cell(when: datetime) -> QLabel:
    label = QLabel(ago(when))
    label.setToolTip(f"{when:%d %b %Y, %H:%M}")
    return label


def host_cell(name: str) -> QLabel:
    label = QLabel(name)
    label.setStyleSheet("font-weight: 600;")
    return label


class LogDialog(QDialog):
    def __init__(self, device: Machine, error: MachineError, preset: Preset | None, parent=None):
        super().__init__(parent)
        machine = device.name
        self.setWindowTitle(f"{machine}: technical details")
        self.setMinimumSize(640, 300)
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        title = QLabel(f"<b>{machine}</b> · {error.title}")
        title.setWordWrap(True)
        layout.addWidget(title)
        when = QLabel(f"{error.when:%d %b %Y, %H:%M} ({ago(error.when)})")
        when.setObjectName("Muted")
        layout.addWidget(when)
        log = QPlainTextEdit(error.log or "No log was recorded.")
        log.setObjectName("Log")
        log.setReadOnly(True)
        layout.addWidget(log, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        ask = buttons.addButton("Ask AI", QDialogButtonBox.ButtonRole.ActionRole)
        ask.setToolTip("Get an explanation and a suggested fix from Claude")
        ask.clicked.connect(lambda: AskAIDialog(device, error, preset, self).exec())
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


def _safe_preset(client, name):
    """Presets come from the server now, so looking one up can fail."""
    try:
        return client.get_preset(name)
    except ApiError:
        return None


class UpdatesPage(QWidget):
    """Devices that aren't up to date, plus recent successful builds and errors across all devices."""

    undo_requested = Signal(str)
    configure_requested = Signal(str)
    message = Signal(str)

    def __init__(self, client: NixyncClient):
        super().__init__()
        self.client = client
        self.show_errors = False

        outer = QVBoxLayout(self)
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

        layout.addWidget(page_header("Updates", "What changed on your devices, and what still needs attention."))
        self.summary = QLabel()
        self.summary.setObjectName("Muted")
        layout.addWidget(self.summary)

        layout.addSpacing(8)
        layout.addWidget(section_title("Not up to date"))
        self.behind = data_table(["Hostname", "Preset", "Status", "Running", "Why", ""], stretch=4)
        layout.addWidget(self.behind)

        layout.addSpacing(8)
        recent = QHBoxLayout()
        recent.addWidget(section_title("Recent builds"))
        recent.addSpacing(12)
        self.segments = QButtonGroup(self)
        self.ok_tab = SegmentButton()
        self.ok_tab.setChecked(True)
        self.ok_tab.clicked.connect(lambda: self._set_errors(False))
        self.error_tab = SegmentButton()
        self.error_tab.clicked.connect(lambda: self._set_errors(True))
        for tab in (self.ok_tab, self.error_tab):
            self.segments.addButton(tab)
            recent.addWidget(tab)
        recent.addStretch()
        layout.addLayout(recent)

        self.builds = data_table(["When", "Hostname", "Generation", "What changed"], stretch=3)
        self.errors = data_table(["When", "Hostname", "Problem", ""], stretch=2)
        layout.addWidget(self.builds)
        layout.addWidget(self.errors)
        layout.addStretch()

        self.refresh()

    # --- data ------------------------------------------------------------

    def _machines(self) -> list[Machine]:
        return self.client.list_machines()

    def _successful(self) -> list[tuple[Machine, Build]]:
        builds = [(m, b) for m in self._machines() for b in m.builds if b.ok]
        return sorted(builds, key=lambda mb: mb[1].finished, reverse=True)[:RECENT_LIMIT]

    def _errors(self) -> list[tuple[Machine, MachineError]]:
        errors = [(m, e) for m in self._machines() for e in m.errors]
        return sorted(errors, key=lambda me: me[1].when, reverse=True)

    @staticmethod
    def _why(m: Machine) -> str:
        running = m.last_successful_build
        latest = m.builds[0] if m.builds else None
        if m.health is Health.PROBLEM and latest and not latest.ok:
            return (f"Update to generation {latest.generation} failed, "
                    f"still running {running.generation if running else 'an older one'}")
        if m.health is Health.UNREACHABLE:
            since = f" for {ago(m.last_seen).removesuffix(' ago')}" if m.last_seen else ""
            return f"Offline{since}, will update when it's back"
        return m.note or m.health.value

    # --- rendering -------------------------------------------------------

    def refresh(self):
        behind = [m for m in self._machines() if m.health is not Health.OK]
        successful, errors = self._successful(), self._errors()
        total = len(self._machines())
        self.summary.setText(f"{total - len(behind)} of {total} devices up to date · "
                             f"{len(successful)} recent successful builds · {len(errors)} errors")
        self.ok_tab.setText(f"Successful ({len(successful)})")
        self.error_tab.setText(f"Errors ({len(errors)})")

        self._fill_behind(behind)
        self._fill_builds(successful)
        self._fill_errors(errors)
        self.builds.setVisible(not self.show_errors)
        self.errors.setVisible(self.show_errors)

    def _set_errors(self, show: bool):
        self.show_errors = show
        self.refresh()

    def _fill_behind(self, machines: list[Machine]):
        t = self.behind
        t.clearSpans()
        t.setRowCount(0)  # drop old cell widgets before refilling
        t.setRowCount(len(machines))
        for row, m in enumerate(machines):
            t.setCellWidget(row, 0, centered(host_cell(m.name)))
            t.setCellWidget(row, 1, centered(QLabel(m.preset)))
            if m.health is Health.PROBLEM:
                status = status_text(style.PROBLEM, "Update failed")
            else:
                status = status_text(style.OFFLINE, "Offline")
            t.setCellWidget(row, 2, centered(status))
            running = m.last_successful_build
            t.setCellWidget(row, 3, centered(QLabel(f"Gen {running.generation}" if running else "—")))
            why = QLabel(self._why(m))
            why.setToolTip(m.note)
            t.setCellWidget(row, 4, centered(why))
            t.setCellWidget(row, 5, self._actions(m))
        if not machines:
            empty_row(t, "Every device is up to date.")
        fit_height(t)

    def _actions(self, m: Machine) -> QWidget:
        box = QWidget()
        layout = QHBoxLayout(box)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(6)
        if m.health is Health.PROBLEM:
            undo = QPushButton("Undo update")
            undo.clicked.connect(lambda: self.undo_requested.emit(m.name))
            layout.addWidget(undo)
        else:
            retry = QPushButton("Retry")
            # TODO: ask the server to try reaching the device again.
            retry.clicked.connect(lambda: self.message.emit(f"Trying to reach {m.name} again…"))
            layout.addWidget(retry)
        settings = QToolButton()
        settings.setObjectName("SettingsButton")
        themed_icon(settings, gear_icon)
        settings.setIconSize(QSize(18, 18))
        settings.setToolTip(f"Settings for {m.name}")
        settings.clicked.connect(lambda: self.configure_requested.emit(m.name))
        layout.addWidget(settings)
        return box

    def _fill_builds(self, builds: list[tuple[Machine, Build]]):
        t = self.builds
        t.clearSpans()
        t.setRowCount(0)  # drop old cell widgets before refilling
        t.setRowCount(len(builds))
        for row, (m, b) in enumerate(builds):
            t.setCellWidget(row, 0, centered(when_cell(b.finished)))
            t.setCellWidget(row, 1, centered(host_cell(m.name)))
            gen = QLabel(f"Gen {b.generation}")
            gen.setObjectName("Muted")
            t.setCellWidget(row, 2, centered(gen))
            t.setCellWidget(row, 3, centered(QLabel(b.summary)))
        if not builds:
            empty_row(t, "No successful builds yet.")
        fit_height(t)

    def _fill_errors(self, errors: list[tuple[Machine, MachineError]]):
        t = self.errors
        t.clearSpans()
        t.setRowCount(0)  # drop old cell widgets before refilling
        t.setRowCount(len(errors))
        for row, (m, e) in enumerate(errors):
            t.setCellWidget(row, 0, centered(when_cell(e.when)))
            t.setCellWidget(row, 1, centered(host_cell(m.name)))
            t.setCellWidget(row, 2, centered(status_text(style.PROBLEM, e.title)))
            details = QPushButton("Details")
            details.setProperty("link", True)
            details.clicked.connect(lambda _=False, m=m, e=e: LogDialog(m, e, self._preset(m.preset), self).exec())
            t.setCellWidget(row, 3, centered(details, Qt.AlignmentFlag.AlignRight))
        if not errors:
            empty_row(t, "No errors.")
        fit_height(t)

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()  # pick up changes made on other pages
