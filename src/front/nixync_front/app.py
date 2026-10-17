import sys

from PySide6.QtWidgets import QApplication

from nixync_front.config import load_config
from nixync_front.main_window import MainWindow
from nixync_front.style import STYLESHEET


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Nixync")
    app.setStyleSheet(STYLESHEET)
    window = MainWindow(load_config())
    window.show()
    return app.exec()
