from PySide6.QtCore import QEvent, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QPushButton, QTableWidget, QToolButton, QVBoxLayout, QWidget,
)

from nixync_front import style
from nixync_front.api import ApiError, NixyncClient
from nixync_front.sample_data import Health, Machine
from nixync_front.widgets import (
    usage_color,
    ago, centered, download_icon, gear_icon, page_header, primary_button, search_icon,
    status_text, themed_icon,
)

WITH_ISSUES = "With issues"  # status filter option: Problem or Offline

STATUS = {
    Health.OK: ("Online", "ok"),
    Health.PROBLEM: ("Problem", "problem"),
    Health.UNREACHABLE: ("Offline", "offline"),
}

COLUMNS = ["", "Hostname", "Group", "Preset", "NixOS", "Status", "Requests", "CPU %", "RAM %", "Disk %", ""]
CHECK, HOST, GROUP, PRESET, NIXOS, STATUS_COL, REQUESTS, CPU, RAM, DISK, SETTINGS = range(len(COLUMNS))


def gb(value: float) -> str:
    """Disk sizes: "842 GB", "1.2 TB"."""
    return f"{value / 1000:.1f} TB" if value >= 1000 else f"{value:.0f} GB"


class UsageBar(QWidget):
    """A small horizontal bar with the percentage next to it, like a resource meter."""

    BAR_WIDTH = 52

    def __init__(self, percent: float | None, detail: str = ""):
        super().__init__()
        self.percent = percent
        self.setToolTip("Not reporting" if percent is None else detail or f"{percent:.1f}%")

    def sizeHint(self) -> QSize:
        # Room for the bar, a gap and the widest label ("100.0%") in the current font.
        return QSize(self.BAR_WIDTH + 10 + self.fontMetrics().horizontalAdvance("100.0%") + 2, 24)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        mid = self.height() / 2
        if self.percent is None:
            painter.setPen(QColor(style.MUTED))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "—")
            return
        track = QRectF(0, mid - 3, self.BAR_WIDTH, 6)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(style.PENDING))
        painter.drawRoundedRect(track, 3, 3)
        fill = QRectF(track)
        fill.setWidth(max(6.0, self.BAR_WIDTH * min(self.percent, 100) / 100))
        painter.setBrush(QColor(usage_color(self.percent)))
        painter.drawRoundedRect(fill, 3, 3)
        painter.setPen(QColor(style.TEXT))
        text_rect = self.rect().adjusted(self.BAR_WIDTH + 10, 0, 0, 0)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         f"{self.percent:.1f}%")


def status_cell(text: str, tone: str) -> QLabel:
    return status_text({"ok": style.OK, "problem": style.PROBLEM, "offline": style.OFFLINE}[tone], text)


class MachinesPage(QWidget):
    """The Devices page: a filterable table of every managed device."""

    add_machine_requested = Signal()
    change_presets_requested = Signal()
    configure_requested = Signal(str)
    requests_requested = Signal(str)
    add_apps_requested = Signal(list)

    def __init__(self, client: NixyncClient):
        super().__init__()
        self.client = client
        self.machines: list[Machine] = []
        self.load_error = ""
        self.selected: set[str] = set()
        self.shown: list[Machine] = []
        self._reload()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)

        top = QHBoxLayout()
        top.setSpacing(16)
        top.addWidget(page_header("Devices"))
        self.attention = self._attention_count()
        top.addWidget(self.attention, 0, Qt.AlignmentFlag.AlignVCenter)
        top.addStretch()
        add = QPushButton("Add device")
        add.clicked.connect(self.add_machine_requested)
        change = primary_button("Change what's installed")
        change.clicked.connect(self.change_presets_requested)
        top.addWidget(add)
        top.addWidget(change)
        layout.addLayout(top)

        tab_row = QWidget()
        tab_row.setFixedHeight(36)
        tabs = QHBoxLayout(tab_row)
        tabs.setContentsMargins(0, 0, 0, 0)
        self.count = QLabel()
        self.count.setObjectName("Muted")
        tabs.addWidget(self.count)
        self.clear_selection = QPushButton("Clear selection")
        self.clear_selection.setProperty("link", True)
        self.clear_selection.clicked.connect(lambda: self._select_all(False))
        tabs.addWidget(self.clear_selection)
        tabs.addSpacing(8)
        self.add_apps = QPushButton(" Add apps…")
        self.add_apps.setStyleSheet("min-height: 30px; max-height: 30px; padding: 0 12px;")
        themed_icon(self.add_apps, download_icon, "text")
        self.add_apps.setIconSize(QSize(16, 16))
        self.add_apps.setToolTip("Add apps to every selected device")
        self.add_apps.clicked.connect(lambda: self.add_apps_requested.emit(self.selected_names()))
        tabs.addWidget(self.add_apps)
        tabs.addStretch()
        layout.addWidget(tab_row)

        filters = QHBoxLayout()
        filters.setSpacing(10)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search by hostname")
        themed_icon(self.search.addAction(QIcon(), QLineEdit.ActionPosition.LeadingPosition), search_icon,
                    owner=self.search)
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(240)
        self.search.textChanged.connect(self.refresh)
        filters.addWidget(self.search, 1)
        self.status_filter = self._combo("All statuses", [label for label, _ in STATUS.values()] + [WITH_ISSUES])
        self.group_filter = self._combo("All groups", sorted({m.group for m in self.machines}))
        self.preset_filter = self._combo("All presets", sorted({m.preset for m in self.machines}))
        for combo in (self.status_filter, self.group_filter, self.preset_filter):
            filters.addWidget(combo)
        layout.addLayout(filters)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setObjectName("DeviceTable")
        self.table.setHorizontalHeaderLabels([c.upper() for c in COLUMNS])
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(54)
        self.table.setShowGrid(False)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.cellDoubleClicked.connect(lambda row, _col: self._open_row(row))
        header = self.table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setHighlightSections(False)
        header.setMinimumSectionSize(40)
        # Text columns size to their content so pills and labels never get cut off; the
        # last (settings) column takes up whatever space is left.
        for col in (GROUP, PRESET, NIXOS, STATUS_COL, REQUESTS, CPU, RAM, DISK):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(CHECK, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(CHECK, 40)
        # Hostname and settings are sized by hand in _fit_columns: Stretch columns would shrink
        # below their content on narrow windows instead of letting the table scroll.
        header.setSectionResizeMode(HOST, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(SETTINGS, QHeaderView.ResizeMode.Fixed)
        header.sectionResized.connect(lambda col, *_: col not in (HOST, SETTINGS) and self._fit_columns())
        self.table.viewport().installEventFilter(self)

        # Select-all checkbox sitting in the first header cell.
        self.select_all = QCheckBox(header)
        self.select_all.setToolTip("Select all shown devices")
        self.select_all.clicked.connect(lambda on: self._select_all(on))
        header.sectionResized.connect(self._place_select_all)
        header.geometriesChanged.connect(self._place_select_all)

        layout.addWidget(self.table, 1)
        self.refresh()

    def _combo(self, everything: str, options: list[str]) -> QComboBox:
        combo = QComboBox()
        combo.addItem(everything, None)
        for option in options:
            combo.addItem(option, option)
        combo.setMinimumWidth(150)
        combo.currentIndexChanged.connect(self.refresh)
        return combo

    def _attention_count(self) -> QPushButton:
        count = len([m for m in self.machines if m.health is not Health.OK])
        button = QPushButton(f"{count} with issues")
        button.setObjectName("AttentionCount")
        button.setToolTip("Show only devices with problems")
        button.setVisible(bool(count))
        button.clicked.connect(lambda: self.status_filter.setCurrentText(WITH_ISSUES))
        return button

    @staticmethod
    def _status_matches(m: Machine, status: str | None) -> bool:
        if status is None:
            return True
        if status == WITH_ISSUES:
            return m.health is not Health.OK
        return STATUS[m.health][0] == status

    def _visible(self) -> list[Machine]:
        needle = self.search.text().strip().lower()
        status = self.status_filter.currentData()
        group = self.group_filter.currentData()
        preset = self.preset_filter.currentData()
        return [m for m in self.machines
                if (not needle or needle in m.name.lower())
                and self._status_matches(m, status)
                and group in (None, m.group)
                and preset in (None, m.preset)]

    def _reload(self):
        """Re-read the fleet from the server.

        The devices, their telemetry and their deployment state all change while the
        app is open, so this has to run on every refresh — rendering the list captured
        at construction would freeze the view at whatever was true when it launched.

        A failure leaves the page empty rather than raising: an unreachable server must
        not stop the app from starting, and `load_error` keeps the reason so the view
        can say the fleet is unknown instead of pretending it is empty.
        """
        try:
            self.machines = self.client.list_machines()
            self.load_error = ""
        except ApiError as e:
            self.machines = []
            self.load_error = str(e)

    def refresh(self):
        self._reload()
        self.shown = self._visible()
        self.table.clearSpans()
        self.table.setRowCount(0)
        self.table.setRowCount(len(self.shown))
        for row, machine in enumerate(self.shown):
            self._fill_row(row, machine)
        if not self.shown:
            self.table.setRowCount(1)
            # Don't blame the filters when the fleet simply could not be read.
            empty = QLabel(
                f"Can't reach the server, so the fleet is unknown.\n{self.load_error}"
                if self.load_error
                else "No devices match these filters."
            )
            empty.setObjectName("Muted")
            self.table.setSpan(0, 0, 1, len(COLUMNS))
            self.table.setCellWidget(0, 0, centered(empty, Qt.AlignmentFlag.AlignCenter))
        self._update_selection_ui()
        # Content columns resize once the new cells are laid out; refit after that.
        QTimer.singleShot(0, self._fit_columns)

    def _fill_row(self, row: int, m: Machine):
        box = QCheckBox()
        box.setStyleSheet("spacing: 0;")  # no label, so no gap after the box
        box.setChecked(m.name in self.selected)
        box.toggled.connect(lambda on, n=m.name: self._toggle(n, on))
        self.table.setCellWidget(row, CHECK, centered(box, Qt.AlignmentFlag.AlignCenter))

        name = QLabel(m.name)
        name.setStyleSheet("font-weight: 600;")
        name.setToolTip(m.address)
        self.table.setCellWidget(row, HOST, centered(name))

        group = QLabel(m.group)
        group.setObjectName("Muted")
        self.table.setCellWidget(row, GROUP, centered(group))
        self.table.setCellWidget(row, PRESET, centered(QLabel(m.preset)))
        self.table.setCellWidget(row, NIXOS, centered(QLabel(m.nixos_version)))
        label, tone = STATUS[m.health]
        status = status_cell(label, tone)
        tip = m.note or m.health.value
        if m.health is Health.UNREACHABLE and m.last_seen:
            tip = f"Last seen {ago(m.last_seen)}. {tip[0].upper()}{tip[1:]}"
        status.setToolTip(tip)
        self.table.setCellWidget(row, STATUS_COL, centered(status))
        pending = len(self.client.pending_requests(m.name))
        if pending:
            plural = "" if pending == 1 else "s"
            requests = QPushButton(f"{pending} pending")
            requests.setProperty("link", True)
            requests.setToolTip(f"{pending} app request{plural} waiting from {m.name}. Click to review.")
            requests.clicked.connect(lambda _=False, n=m.name: self.requests_requested.emit(n))
            self.table.setCellWidget(row, REQUESTS, centered(requests))
        self.table.setCellWidget(row, CPU, centered(UsageBar(m.cpu_percent)))
        self.table.setCellWidget(row, RAM, centered(UsageBar(m.ram_percent)))
        disk = ""
        if m.disk_percent is not None:
            free = m.disk_total_gb - m.disk_used_gb
            disk = f"{gb(m.disk_used_gb)} of {gb(m.disk_total_gb)} used, {gb(free)} free"
        self.table.setCellWidget(row, DISK, centered(UsageBar(m.disk_percent, disk)))

        settings = QToolButton()
        settings.setObjectName("SettingsButton")
        themed_icon(settings, gear_icon)
        settings.setIconSize(QSize(18, 18))
        settings.setToolTip(f"Settings for {m.name}")
        settings.clicked.connect(lambda _=False, n=m.name: self.configure_requested.emit(n))
        self.table.setCellWidget(row, SETTINGS, centered(settings, Qt.AlignmentFlag.AlignRight))

    def _open_row(self, row: int):
        if row < len(self.shown):
            self.configure_requested.emit(self.shown[row].name)

    # --- selection -------------------------------------------------------

    def _toggle(self, name: str, on: bool):
        if on:
            self.selected.add(name)
        else:
            self.selected.discard(name)
        self._update_selection_ui()

    def selected_names(self) -> list[str]:
        """Selected devices that are currently shown, in table order."""
        return [m.name for m in self.shown if m.name in self.selected]

    def clear_selected(self):
        self.selected.clear()
        self.refresh()

    def _select_all(self, on: bool):
        names = {m.name for m in self.shown}
        self.selected = (self.selected | names) if on else (self.selected - names)
        self.refresh()

    def _update_selection_ui(self):
        shown = {m.name for m in self.shown}
        picked = len(self.selected & shown)
        total = len(self.machines)
        if picked:
            self.count.setText(f"{picked} of {len(shown)} selected")
        else:
            self.count.setText(f"{len(shown)} of {total} device{'' if total == 1 else 's'}")
        self.clear_selection.setVisible(bool(picked))
        self.add_apps.setVisible(bool(picked))
        self.select_all.blockSignals(True)
        self.select_all.setCheckState(
            Qt.CheckState.Checked if shown and picked == len(shown)
            else Qt.CheckState.PartiallyChecked if picked else Qt.CheckState.Unchecked)
        self.select_all.blockSignals(False)

    def _place_select_all(self, *_):
        header = self.table.horizontalHeader()
        size = self.select_all.sizeHint()
        x = header.sectionViewportPosition(CHECK) + (header.sectionSize(CHECK) - size.width()) // 2
        self.select_all.setGeometry(x, (header.height() - size.height()) // 2, size.width(), size.height())

    SETTINGS_WIDTH = 52

    def _fit_columns(self):
        header = self.table.horizontalHeader()
        content = max(self.table.sizeHintForColumn(HOST), header.sectionSizeFromContents(HOST).width())
        others = sum(self.table.columnWidth(c) for c in range(len(COLUMNS)) if c not in (HOST, SETTINGS))
        room = self.table.viewport().width() - others
        # Hostname takes all the spare room, but never less than its content.
        self.table.setColumnWidth(SETTINGS, self.SETTINGS_WIDTH)
        self.table.setColumnWidth(HOST, max(content, room - self.SETTINGS_WIDTH))

    def eventFilter(self, obj, event):
        if obj is self.table.viewport() and event.type() == QEvent.Type.Resize:
            self._fit_columns()
        return super().eventFilter(obj, event)

    def showEvent(self, event):
        super().showEvent(event)
        self._place_select_all()
        QTimer.singleShot(0, self._fit_columns)
