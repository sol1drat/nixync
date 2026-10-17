from PySide6.QtCore import QEvent, QObject, QRunnable, QSize, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QToolButton,
    QVBoxLayout, QWidget,
)

from nixync_front import style
from nixync_front.api import NixyncClient
from nixync_front.nixos_search import Package, SearchError
from nixync_front.widgets import FlowLayout, close_icon, safe_emit, search_icon, themed_icon

WIDTH = 560
RESULT_ROW_HEIGHT = 54
VISIBLE_RESULTS = 6


class _SearchSignals(QObject):
    done = Signal(int, list, str, bool)


class _Search(QRunnable):
    """Runs one search.nixos.org query off the UI thread."""

    def __init__(self, client: NixyncClient, query: str, seq: int):
        super().__init__()
        self.client, self.query, self.seq = client, query, seq
        self.signals = _SearchSignals()

    def run(self):
        try:
            safe_emit(self.signals.done, self.seq, self.client.search_apps(self.query), "", False)
        except SearchError as e:
            safe_emit(self.signals.done, self.seq, [], str(e), e.offline)


def static_tags(names: list[str]) -> QWidget:
    """Read-only app tags, e.g. the apps a device gets from its preset."""
    box = QWidget()
    flow = FlowLayout(box, spacing=6)
    for name in names:
        tag = QLabel(name)
        tag.setObjectName("AppTagStatic")
        flow.addWidget(tag)
    return box


class AppTag(QFrame):
    """One app in the list: its name and a small × to remove it."""

    removed = Signal(str)

    def __init__(self, name: str, pending: bool):
        super().__init__()
        self.setObjectName("AppTag")
        self.setProperty("pending", pending)
        if pending:
            self.setToolTip(f"{name}: not applied yet")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(9, 2, 3, 2)
        layout.setSpacing(2)
        label = QLabel(name)
        label.setObjectName("AppTagName")
        layout.addWidget(label)
        remove = QToolButton()
        remove.setObjectName("TagRemove")
        themed_icon(remove, close_icon)
        remove.setIconSize(QSize(10, 10))
        remove.setToolTip(f"Remove {name}")
        remove.clicked.connect(lambda: self.removed.emit(name))
        layout.addWidget(remove)


class ResultRow(QWidget):
    """A search result: name and version on top, description below, Add on the right."""

    add_clicked = Signal(str)

    def __init__(self, package: Package, added: bool, text_width: int):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 10, 6)
        layout.setSpacing(12)

        text = QVBoxLayout()
        text.setSpacing(1)
        title = QHBoxLayout()
        title.setSpacing(8)
        name = QLabel(package.name)
        name.setStyleSheet("font-weight: 600;")
        title.addWidget(name)
        if package.version:
            version = QLabel(package.version)
            version.setObjectName("Muted")
            version.setStyleSheet("font-size: 12px;")
            title.addWidget(version)
        title.addStretch()
        text.addLayout(title)
        description = package.description or "No description"
        desc = QLabel()
        desc.setObjectName("Muted")
        desc.setStyleSheet("font-size: 12px;")
        desc.setText(desc.fontMetrics().elidedText(description, Qt.TextElideMode.ElideRight, text_width))
        desc.setToolTip(description)
        text.addWidget(desc)
        layout.addLayout(text, 1)

        if added:
            done = QLabel("Added")
            done.setObjectName("Muted")
            layout.addWidget(done)
        else:
            add = QPushButton("Add")
            add.setObjectName("SmallButton")
            add.clicked.connect(lambda: self.add_clicked.emit(package.name))
            layout.addWidget(add)


class AppPicker(QWidget):
    """A compact list of apps (tags) and a search.nixos.org search box to add more.

    `saved` is what is currently applied; `apps` is the edited list. Emits
    `changed` whenever `apps` changes.
    """

    changed = Signal()

    def __init__(self, client: NixyncClient, saved: list[str], placeholder: str, empty_text: str,
                 mark_unsaved: bool = True):
        super().__init__()
        self.client = client
        self.saved = list(saved)
        self.apps = list(saved)
        self.empty_text = empty_text
        self.mark_unsaved = mark_unsaved
        self.packages: list[Package] = []
        self._seq = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.empty = QLabel(empty_text)
        self.empty.setObjectName("Muted")
        layout.addWidget(self.empty)
        self.tags = QWidget()
        self.tag_layout = FlowLayout(self.tags, spacing=6)
        layout.addWidget(self.tags)

        self.search = QLineEdit()
        self.search.setPlaceholderText(placeholder)
        themed_icon(self.search.addAction(QIcon(), QLineEdit.ActionPosition.LeadingPosition), search_icon,
                    owner=self.search)
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(WIDTH)
        self.search.textChanged.connect(self._schedule_search)
        self.search.returnPressed.connect(self._add_current)
        self.search.installEventFilter(self)  # arrow keys move through the results
        layout.addWidget(self.search)

        self.status = QLabel()
        self.status.setObjectName("Muted")
        self.status.setStyleSheet("font-size: 12px;")
        self.status.setVisible(False)
        layout.addWidget(self.status)

        self.results = QListWidget()
        self.results.setObjectName("SearchResults")
        self.results.setMaximumWidth(WIDTH)
        self.results.setVisible(False)
        self.results.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.results.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.results.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.results.itemClicked.connect(lambda item: self.add(item.data(Qt.ItemDataRole.UserRole)))
        layout.addWidget(self.results)

        # Wait for a pause in typing before hitting the network.
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(300)
        self.debounce.timeout.connect(self._run_search)

        self._render_tags()

    # --- the edited list -------------------------------------------------

    @property
    def added(self) -> list[str]:
        return [a for a in self.apps if a not in self.saved]

    @property
    def removed(self) -> list[str]:
        return [a for a in self.saved if a not in self.apps]

    def changes_text(self) -> str:
        changes = ([f"add {', '.join(self.added)}"] if self.added else []) + \
                  ([f"remove {', '.join(self.removed)}"] if self.removed else [])
        return ("Not applied yet: " + "; ".join(changes) + ".") if changes else ""

    def add(self, name: str | None):
        if not name or name in self.apps:
            return
        self.apps.append(name)
        self._render_tags()
        self._render_results()  # the row now shows "Added"; keep the results open for more
        self.changed.emit()

    def remove(self, name: str):
        self.apps.remove(name)
        self._render_tags()
        self._render_results()
        self.changed.emit()

    def discard(self):
        self.apps = list(self.saved)
        self._render_tags()
        self._render_results()
        self.changed.emit()

    def mark_saved(self):
        self.saved = list(self.apps)
        self._render_tags()
        self.changed.emit()

    def _render_tags(self):
        while (item := self.tag_layout.takeAt(0)) is not None:
            if widget := item.widget():
                widget.hide()
                widget.deleteLater()
        for app in self.apps:
            tag = AppTag(app, pending=self.mark_unsaved and app not in self.saved)
            tag.removed.connect(self.remove)
            self.tag_layout.addWidget(tag)
        self.empty.setVisible(not self.apps)
        self.tags.setVisible(bool(self.apps))
        self.tags.updateGeometry()

    # --- search ----------------------------------------------------------

    def _schedule_search(self, text: str):
        self._seq += 1  # drop any search still in flight
        if not text.strip():
            self.debounce.stop()
            self.packages = []
            self.results.clear()
            self.results.setVisible(False)
            self.status.setVisible(False)
            return
        self._show_status("Searching search.nixos.org…")
        self.debounce.start()

    def _run_search(self):
        job = _Search(self.client, self.search.text(), self._seq)
        job.signals.done.connect(self._on_results, Qt.ConnectionType.QueuedConnection)
        QThreadPool.globalInstance().start(job)

    def _on_results(self, seq: int, packages: list, error: str, offline: bool):
        if seq != self._seq:
            return
        self.packages = packages
        if error:
            self.packages = []
            self.results.setVisible(False)
            self._show_status("Couldn't reach search.nixos.org. Check your internet connection." if offline else
                              "search.nixos.org didn't accept the search. Its index may have changed: "
                              "check nixos_search_index in config.toml.")
            self.status.setToolTip(error)
            return
        self._render_results()

    def _render_results(self):
        if not self.search.text().strip():
            return
        current = self.results.currentRow()
        self.results.clear()
        if not self.packages:
            self.results.setVisible(False)
            self._show_status(f"No packages match “{self.search.text().strip()}”.")
            return
        text_width = WIDTH - 150
        for package in self.packages:
            added = package.name in self.apps
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, RESULT_ROW_HEIGHT))
            item.setData(Qt.ItemDataRole.UserRole, None if added else package.name)
            if added:
                item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.results.addItem(item)
            row = ResultRow(package, added, text_width)
            row.add_clicked.connect(self.add)
            self.results.setItemWidget(item, row)
        self.results.setFixedHeight(min(len(self.packages), VISIBLE_RESULTS) * RESULT_ROW_HEIGHT
                                    + 2 * self.results.frameWidth())
        self.results.setVisible(True)
        self._select(current if current >= 0 else 0, step=1)
        self._show_status(f"{len(self.packages)} results from search.nixos.org · ↑↓ to choose, Enter to add")

    def _select(self, row: int, step: int):
        """Highlight the nearest addable result from `row`, moving in `step` direction."""
        count = self.results.count()
        while 0 <= row < count:
            if self.results.item(row).data(Qt.ItemDataRole.UserRole):
                self.results.setCurrentRow(row)
                self.results.scrollToItem(self.results.item(row))
                return
            row += step
        if step == 1 and count:
            self._select(min(row, count) - 1, -1)  # nothing below; fall back upwards

    def _add_current(self):
        item = self.results.currentItem() if self.results.isVisible() else None
        if item:
            self.add(item.data(Qt.ItemDataRole.UserRole))

    def _show_status(self, text: str):
        self.status.setText(text)
        self.status.setToolTip("")
        self.status.setVisible(True)

    def eventFilter(self, obj, event):
        if obj is self.search and event.type() == QEvent.Type.KeyPress and self.results.isVisible():
            if event.key() == Qt.Key.Key_Down:
                self._select(self.results.currentRow() + 1, 1)
                return True
            if event.key() == Qt.Key.Key_Up:
                self._select(self.results.currentRow() - 1, -1)
                return True
            if event.key() == Qt.Key.Key_Escape:
                self.search.clear()
                return True
        return super().eventFilter(obj, event)
