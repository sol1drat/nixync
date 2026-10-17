from dataclasses import replace

from PySide6.QtCore import QSettings, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QToolButton, QVBoxLayout, QWidget,
)

from nixync_front import __version__, style
from nixync_front.api import ApiError, NixyncClient
from nixync_front.config import Config
from nixync_front.widgets import eye_icon, moon_icon, primary_button, sun_icon

CARD_WIDTH = 400


def field_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet("font-size: 13px; font-weight: 600;")
    return label


class LoginWindow(QWidget):
    """Sign-in screen shown before the main window."""

    signed_in = Signal(object, str, str)  # Config (with the chosen server), username, device ("" = admin)

    def __init__(self, config: Config):
        super().__init__()
        self.config = config
        self.settings = QSettings("Nixync", "Nixync")
        self.setObjectName("LoginWindow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setWindowTitle("Sign in · Nixync")
        self.setWindowIcon(QIcon(str(style.ICONS / "app-icon.png")))
        self.resize(1000, 720)
        self._build()
        style.styled(self)

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 20)

        top = QHBoxLayout()
        top.addStretch()
        self.theme = QToolButton()
        self.theme.setObjectName("SidebarToggle")
        self.theme.setIconSize(QSize(18, 18))
        self.theme.clicked.connect(self._toggle_theme)
        top.addWidget(self.theme)
        outer.addLayout(top)
        outer.addStretch(1)

        card = QFrame()
        card.setObjectName("LoginCard")
        card.setFixedWidth(CARD_WIDTH)
        body = QVBoxLayout(card)
        body.setContentsMargins(32, 32, 32, 28)
        body.setSpacing(6)

        self.logo = QLabel()
        self.logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body.addWidget(self.logo)
        body.addSpacing(10)
        title = QLabel("Sign in to Nixync")
        title.setObjectName("PageTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body.addWidget(title)
        subtitle = QLabel("Manage and update your NixOS devices.")
        subtitle.setObjectName("Muted")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body.addWidget(subtitle)
        body.addSpacing(18)

        saved_server = self.settings.value("login/server", self.config.server_url, type=str)
        saved_user = self.settings.value("login/username", "", type=str)

        body.addWidget(field_label("Server"))
        self.server = QLineEdit(saved_server)
        self.server.setPlaceholderText("http://nixync.local:8000")
        body.addWidget(self.server)
        body.addSpacing(8)

        body.addWidget(field_label("Username"))
        self.username = QLineEdit(saved_user)
        self.username.setPlaceholderText("admin")
        body.addWidget(self.username)
        body.addSpacing(8)

        body.addWidget(field_label("Password"))
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("••••••••")
        self.reveal = self.password.addAction(eye_icon(style.MUTED), QLineEdit.ActionPosition.TrailingPosition)
        self.reveal.setToolTip("Show password")
        self.reveal.triggered.connect(self._toggle_password)
        body.addWidget(self.password)
        body.addSpacing(10)

        self.as_client = QCheckBox("Log in as client")
        self.as_client.setToolTip("Use the app for one device: request apps and change its settings")
        self.as_client.setChecked(self.settings.value("login/as_client", False, type=bool))
        body.addWidget(self.as_client)
        self.device_label = field_label("Device")
        self.device = QComboBox()
        # TODO: the client app runs on the device, so it should use its own hostname instead.
        self.device.addItems([m.name for m in NixyncClient(self.config).list_machines()])
        saved_device = self.settings.value("login/device", "", type=str)
        if saved_device:
            self.device.setCurrentText(saved_device)
        body.addWidget(self.device_label)
        body.addWidget(self.device)
        self.as_client.toggled.connect(self._show_device)
        self._show_device(self.as_client.isChecked())
        body.addSpacing(4)

        self.remember = QCheckBox("Remember server and username")
        self.remember.setChecked(bool(saved_user))
        body.addWidget(self.remember)

        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setVisible(False)
        body.addWidget(self.error)
        body.addSpacing(12)

        self.sign_in = primary_button("Sign in")
        self.sign_in.setMinimumHeight(40)
        self.sign_in.clicked.connect(self._submit)
        body.addWidget(self.sign_in)

        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(card)
        row.addStretch()
        outer.addLayout(row)
        outer.addStretch(1)

        footer = QLabel(f"Nixync {__version__}")
        footer.setObjectName("Muted")
        footer.setStyleSheet("font-size: 12px;")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(footer)

        for field in (self.server, self.username, self.password):
            field.returnPressed.connect(self._submit)
            field.textChanged.connect(lambda: self.error.setVisible(False))
        self._apply_theme_icons()
        (self.password if saved_user else self.username).setFocus()

    def _apply_theme_icons(self):
        ratio = self.devicePixelRatioF()
        logo = QPixmap(str(style.logo_path())).scaled(
            int(64 * ratio), int(64 * ratio), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        logo.setDevicePixelRatio(ratio)
        self.logo.setPixmap(logo)
        self.theme.setIcon(sun_icon(style.MUTED) if style.IS_DARK else moon_icon(style.MUTED))
        self.theme.setToolTip("Switch to the light theme" if style.IS_DARK else "Switch to the dark theme")
        self.reveal.setIcon(eye_icon(style.MUTED, self.password.echoMode() == QLineEdit.EchoMode.Password))
        self.error.setStyleSheet(f"color: {style.PROBLEM};")

    def _toggle_theme(self):
        theme = "light" if style.IS_DARK else "dark"
        self.settings.setValue("appearance/theme", theme)
        style.apply(QApplication.instance(), theme)
        self._apply_theme_icons()

    def _show_device(self, on: bool):
        self.device_label.setVisible(on)
        self.device.setVisible(on)

    def _toggle_password(self):
        hidden = self.password.echoMode() == QLineEdit.EchoMode.Password
        self.password.setEchoMode(QLineEdit.EchoMode.Normal if hidden else QLineEdit.EchoMode.Password)
        self.reveal.setToolTip("Hide password" if hidden else "Show password")
        self.reveal.setIcon(eye_icon(style.MUTED, not hidden))

    def _show_error(self, text: str):
        self.error.setText(text)
        self.error.setVisible(True)

    def _submit(self):
        server = self.server.text().strip().rstrip("/")
        username = self.username.text().strip()
        password = self.password.text()
        if not server.startswith(("http://", "https://")):
            self._show_error("The server address should start with http:// or https://.")
            self.server.setFocus()
            return
        if not username or not password:
            self._show_error("Enter your username and password.")
            (self.username if not username else self.password).setFocus()
            return

        config = replace(self.config, server_url=server)
        try:
            user = NixyncClient(config).login(username, password)
        except ApiError as e:
            self._show_error(str(e))
            return

        device = self.device.currentText() if self.as_client.isChecked() else ""
        if self.remember.isChecked():
            self.settings.setValue("login/server", server)
            self.settings.setValue("login/username", username)
            self.settings.setValue("login/as_client", self.as_client.isChecked())
            self.settings.setValue("login/device", device)
        else:
            for key in ("server", "username", "as_client", "device"):
                self.settings.remove(f"login/{key}")
        self.password.clear()
        self.signed_in.emit(config, user["username"], device)
