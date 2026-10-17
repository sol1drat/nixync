import sys

from PySide6.QtCore import QSettings
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from nixync_ui import style
from nixync_front.config import load_config
from nixync_front.login import LoginWindow
from nixync_front.client_window import ClientWindow
from nixync_front.main_window import MainWindow
from nixync_ui.widgets import PointerCursors, ThemedDialogs

DEFAULT_THEME = "dark"


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Nixync")
    app.setDesktopFileName("nixync")
    # White logo on a black circle, used for the taskbar and window switcher in both themes.
    app.setWindowIcon(QIcon(str(style.ICONS / "app-icon.png")))
    app.installEventFilter(PointerCursors(app))
    app.installEventFilter(ThemedDialogs(app))
    # The window switches themes itself (MainWindow.toggle_theme); start with the saved one.
    style.apply(app, QSettings("Nixync", "Nixync").value("appearance/theme", DEFAULT_THEME, type=str))
    windows = {}

    def show_login():
        login = LoginWindow(load_config())
        login.signed_in.connect(open_main)
        if "main" in windows:  # coming back from Sign out: keep the window where it was
            login.setGeometry(windows["main"].geometry())
            windows.pop("main").close()
        windows["login"] = login
        login.show()

    def open_main(config, username, device):
        # A device means "log in as client": the per-device app instead of the admin panel.
        window = ClientWindow(config, username, device) if device else MainWindow(config, username)
        window.sign_out_requested.connect(show_login)
        # Open at its own (larger) default size, centred where the login window was.
        frame = window.frameGeometry()
        frame.moveCenter(windows["login"].frameGeometry().center())
        window.move(frame.topLeft())
        windows["main"] = window
        window.show()
        windows.pop("login").close()

    show_login()
    return app.exec()
