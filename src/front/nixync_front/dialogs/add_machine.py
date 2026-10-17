from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel,
    QLineEdit, QPlainTextEdit, QPushButton, QVBoxLayout,
)

# TODO: fetch the server's real public key and the host's fingerprint.
AUTHORIZED_KEY_SNIPPET = (
    "users.users.nixync.openssh.authorizedKeys.keys =\n"
    '  [ "ssh-ed25519 AAAA... nixync-server" ];'
)


class AddMachineDialog(QDialog):
    def __init__(self, roles: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add machine")
        self.setMinimumWidth(620)
        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        layout.addWidget(QLabel("<b>1. Which machine?</b>"))
        form = QFormLayout()
        self.name = QLineEdit()
        self.name.setPlaceholderText("lab-05")
        self.address = QLineEdit()
        self.address.setPlaceholderText("10.0.4.15")
        self.role = QComboBox()
        self.role.addItems(roles)
        form.addRow("Name", self.name)
        form.addRow("IP address or hostname", self.address)
        form.addRow("Role", self.role)
        layout.addLayout(form)

        layout.addWidget(QLabel("<b>2. Let Nixync log in to it</b>"))
        layout.addWidget(QLabel("Add these lines to the machine's configuration once, then rebuild it."))
        snippet = QPlainTextEdit(AUTHORIZED_KEY_SNIPPET)
        snippet.setReadOnly(True)
        snippet.setFixedHeight(60)
        layout.addWidget(snippet)
        copy = QPushButton("Copy")
        copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(AUTHORIZED_KEY_SNIPPET))
        layout.addWidget(copy)

        layout.addWidget(QLabel("<b>3. Check it's the right machine</b>"))
        layout.addWidget(QLabel("This code should match the one the machine shows for its SSH key."))
        layout.addWidget(QLabel("<tt>SHA256:(fetched when the machine is reached)</tt>"))
        self.match = QCheckBox("The codes match")
        layout.addWidget(self.match)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.add = buttons.addButton("Add machine", QDialogButtonBox.ButtonRole.AcceptRole)
        self.add.setProperty("primary", True)
        self.add.setEnabled(False)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        for signal in (self.name.textChanged, self.address.textChanged, self.match.toggled):
            signal.connect(self._validate)

    def _validate(self):
        self.add.setEnabled(bool(self.name.text().strip() and self.address.text().strip() and self.match.isChecked()))

    def values(self) -> dict:
        return {"name": self.name.text().strip(), "address": self.address.text().strip(), "role": self.role.currentText()}
