import sys

from PySide6.QtCore import QSettings
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from nixync_front import style
from nixync_front.config import load_config
from nixync_front.main_window import MainWindow
from nixync_front.widgets import PointerCursors

DEFAULT_THEME = "dark"


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Nixync")
    app.setDesktopFileName("nixync")
    # White logo on a black circle, used for the taskbar and window switcher in both themes.
    app.setWindowIcon(QIcon(str(style.ICONS / "app-icon.png")))
    app.installEventFilter(PointerCursors(app))
    # The window switches themes itself (MainWindow.toggle_theme); start with the saved one.
    style.apply(app, QSettings("Nixync", "Nixync").value("appearance/theme", DEFAULT_THEME, type=str))
    window = MainWindow(load_config())
    window.show()
    return app.exec()
