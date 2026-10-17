from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget,
)

from nixync_front.api import NixyncClient
from nixync_front.nixos_search import SearchError
from nixync_front.widgets import clear_layout

WIDTH = 520


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
            self.signals.done.emit(self.seq, self.client.search_apps(self.query), "", False)
        except SearchError as e:
            self.signals.done.emit(self.seq, [], str(e), e.offline)


class AppPicker(QWidget):
    """A list of apps with Remove buttons and a search.nixos.org search box to add more.

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
        self._seq = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        rows = QWidget()
        self.rows = QVBoxLayout(rows)
        self.rows.setContentsMargins(0, 0, 0, 0)
        self.rows.setSpacing(6)
        layout.addWidget(rows)

        self.search = QLineEdit()
        self.search.setPlaceholderText(placeholder)
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(WIDTH)
        self.search.textChanged.connect(self._schedule_search)
        self.search.returnPressed.connect(self._add_first_result)
        layout.addWidget(self.search)

        self.status = QLabel()
        self.status.setObjectName("Muted")
        self.status.setStyleSheet("border: none;")
        self.status.setVisible(False)
        layout.addWidget(self.status)

        self.results = QListWidget()
        self.results.setMaximumWidth(WIDTH)
        self.results.setVisible(False)
        self.results.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.results.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.results.itemClicked.connect(lambda item: self.add(item.data(Qt.ItemDataRole.UserRole)))
        layout.addWidget(self.results)

        # Wait for a pause in typing before hitting the network.
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(300)
        self.debounce.timeout.connect(self._run_search)

        self._render_rows()

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
        self.search.clear()
        self._render_rows()
        self.changed.emit()

    def remove(self, name: str):
        self.apps.remove(name)
        self._render_rows()
        self.changed.emit()

    def discard(self):
        self.apps = list(self.saved)
        self._render_rows()
        self.changed.emit()

    def mark_saved(self):
        self.saved = list(self.apps)
        self._render_rows()
        self.changed.emit()

    def _render_rows(self):
        clear_layout(self.rows)
        if not self.apps:
            empty = QLabel(self.empty_text)
            empty.setObjectName("Muted")
            empty.setStyleSheet("border: none;")
            self.rows.addWidget(empty)
        for app in self.apps:
            row = QWidget()
            row.setMaximumWidth(WIDTH)
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            note = "" if app in self.saved or not self.mark_unsaved else "  <i>(not applied yet)</i>"
            label = QLabel(f"<b>{app}</b>{note}")
            label.setStyleSheet("border: none;")
            layout.addWidget(label, 1)
            remove = QPushButton("Remove")
            remove.clicked.connect(lambda _=False, a=app: self.remove(a))
            layout.addWidget(remove)
            self.rows.addWidget(row)

    # --- search ----------------------------------------------------------

    def _schedule_search(self, text: str):
        self._seq += 1  # drop any search still in flight
        if not text.strip():
            self.debounce.stop()
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
        self.results.clear()
        if error:
            self._show_status("Couldn't reach search.nixos.org. Check your internet connection." if offline else
                              "search.nixos.org didn't accept the search. Its index may have changed: "
                              "check nixos_search_index in config.toml.")
            self.status.setToolTip(error)
            self.results.setVisible(False)
            return
        matches = [p for p in packages if p.name not in self.apps]
        if not matches:
            self._show_status(f"No packages match “{self.search.text().strip()}” on search.nixos.org.")
            self.results.setVisible(False)
            return
        self._show_status("Click a package to add it, or press Enter to add the first one.")
        for package in matches:
            version = f"  {package.version}" if package.version else ""
            item = QListWidgetItem(f"{package.name}{version} — {package.description or 'No description'}")
            item.setData(Qt.ItemDataRole.UserRole, package.name)
            item.setToolTip(f"Add {package.name}{version}\n{package.description}")
            self.results.addItem(item)
        rows = min(self.results.count(), 8)
        self.results.setFixedHeight(rows * self.results.sizeHintForRow(0) + 2 * self.results.frameWidth() + 4)
        self.results.setVisible(True)

    def _show_status(self, text: str):
        self.status.setText(text)
        self.status.setToolTip("")
        self.status.setVisible(True)

    def _add_first_result(self):
        if self.results.isVisible() and self.results.count():
            self.add(self.results.item(0).data(Qt.ItemDataRole.UserRole))
