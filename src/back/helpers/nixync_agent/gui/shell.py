"""The window frame: sidebar, pages, theme toggle, connection status.

A deliberately small shell rather than the host app's MainWindow. Inheriting that
would make the device package depend on the whole admin application, which it has no
business shipping. Both draw from `nixync_ui`, so they still look like one product —
the stylesheet is what makes them match, not a shared base class.
"""

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QListWidget, QMainWindow, QStackedWidget, QToolButton,
    QVBoxLayout, QWidget,
)

from nixync_ui import style
from nixync_ui.widgets import dot, moon_icon, sun_icon, themed_icon

SIDEBAR_WIDTH = 210


class AgentShell(QMainWindow):
    """Sidebar plus a stack of pages. Subclasses supply PAGES and build them."""

    PAGES: list[str] = []
    refreshed = Signal()

    def __init__(self, title: str, subtitle: str = ""):
        super().__init__()
        self.setWindowTitle(title)
        self.setWindowIcon(QIcon(str(style.ICONS / "app-icon.png")))
        self.resize(1040, 720)

        self.sidebar = QListWidget()
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.sidebar.addItems(self.PAGES)

        self.stack = QStackedWidget()
        for page in self.make_pages():
            self.stack.addWidget(page)
        self.sidebar.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.sidebar.setCurrentRow(0)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._sidebar_column(title, subtitle))
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        # Set before the dot exists: style.themed() calls the paint callback straight
        # away, and that callback reads this.
        self._online: bool | None = None
        self.connection_dot = dot(style.OFFLINE, 8)
        style.themed(self.connection_dot, self._paint_dot)
        self.connection_label = QLabel("Connecting…")
        bar = QWidget()
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(6, 0, 6, 0)
        bar_layout.addWidget(self.connection_dot)
        bar_layout.addWidget(self.connection_label)
        self.statusBar().addWidget(bar, 1)

        for part in (self.sidebar.parentWidget(), self.statusBar()):
            style.styled(part)
        for index in range(self.stack.count()):
            style.styled(self.stack.widget(index), lazy=True)
        # Hidden pages are styled lazily, so a theme switch leaves them carrying the
        # old sheet until they are shown again. Without this the device app came up
        # in dark mode with light-mode pages — the window chrome switched, the
        # content did not.
        self.stack.currentChanged.connect(
            lambda _index: style.restyle_if_stale(self.stack.currentWidget())
        )

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(10_000)
        QTimer.singleShot(0, self.refresh)

    # -- for subclasses ----------------------------------------------------

    def make_pages(self) -> list[QWidget]:
        raise NotImplementedError

    def refresh(self) -> None:
        """Re-read everything on screen. Called on a timer and by the Refresh button."""
        self.refreshed.emit()

    def show_message(self, text: str) -> None:
        self.statusBar().showMessage(text, 6000)

    def set_connected(self, online: bool, detail: str = "") -> None:
        self._online = online
        self.connection_label.setText(detail or ("Connected" if online else "Not connected"))
        self._paint_dot()

    # -- chrome ------------------------------------------------------------

    def _paint_dot(self) -> None:
        colour = style.OFFLINE if self._online is None else style.OK if self._online else style.PROBLEM
        self.connection_dot.setStyleSheet(f"background: {colour}; border-radius: 4px;")

    def _sidebar_column(self, title: str, subtitle: str) -> QWidget:
        column = QWidget()
        column.setObjectName("SidebarColumn")
        column.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        column.setFixedWidth(SIDEBAR_WIDTH)
        layout = QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        brand = QWidget()
        brand_layout = QVBoxLayout(brand)
        brand_layout.setContentsMargins(18, 18, 16, 10)
        brand_layout.setSpacing(2)
        name = QLabel(title)
        name.setStyleSheet("font-size: 16px; font-weight: 600;")
        brand_layout.addWidget(name)
        if subtitle:
            where = QLabel(subtitle)
            where.setObjectName("Muted")
            where.setStyleSheet("font-size: 12px;")
            brand_layout.addWidget(where)
        layout.addWidget(brand)
        layout.addWidget(self.sidebar, 1)

        footer = QWidget()
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(14, 8, 14, 14)
        self.theme = QToolButton()
        self.theme.setObjectName("ThemeToggle")
        themed_icon(self.theme, lambda c: moon_icon(c) if not style.IS_DARK else sun_icon(c))
        self.theme.setToolTip("Switch between light and dark")
        self.theme.clicked.connect(self._toggle_theme)
        footer_layout.addWidget(self.theme)
        footer_layout.addStretch()
        layout.addWidget(footer)
        return column

    def _toggle_theme(self) -> None:
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QApplication

        theme = "light" if style.IS_DARK else "dark"
        # Remembered, so the app does not snap back to light on the next launch.
        QSettings("Nixync", "NixyncAgent").setValue("theme", theme)
        style.apply(QApplication.instance(), theme)
        style.restyle_if_stale(self.stack.currentWidget())
