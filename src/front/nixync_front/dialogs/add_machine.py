from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QVBoxLayout


class AddMachineDialog(QDialog):
    def __init__(self, presets: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add device")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        title = QLabel("Add device")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        form = QFormLayout()
        form.setVerticalSpacing(12)
        self.name = QLineEdit()
        self.name.setPlaceholderText("lab-05")
        self.address = QLineEdit()
        self.address.setPlaceholderText("10.0.4.15")
        self.preset = QComboBox()
        self.preset.addItems(presets)
        form.addRow("Name", self.name)
        form.addRow("IP address or hostname", self.address)
        form.addRow("Preset", self.preset)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.add = buttons.addButton("Add device", QDialogButtonBox.ButtonRole.AcceptRole)
        self.add.setProperty("primary", True)
        self.add.setEnabled(False)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        for field in (self.name, self.address):
            field.textChanged.connect(self._validate)

    def _validate(self):
        self.add.setEnabled(bool(self.name.text().strip() and self.address.text().strip()))

    def values(self) -> dict:
        return {"name": self.name.text().strip(), "address": self.address.text().strip(), "preset": self.preset.currentText()}
