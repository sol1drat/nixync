from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QRadioButton, QVBoxLayout

from nixync_ui.widgets import cancel_box


class UndoUpdateDialog(QDialog):
    def __init__(self, host: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Undo update")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        title = QLabel(f"Undo the update on {host}?")
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        intro = QLabel(f"{host} will go back to its previous NixOS generation, the last time it was working.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.now = QRadioButton("Now (recommended). Anyone using it may see the screen restart.")
        self.now.setChecked(True)
        self.on_boot = QRadioButton("Next time it restarts. Nothing changes until it is rebooted.")
        layout.addWidget(self.now)
        layout.addWidget(self.on_boot)

        note = QLabel("Files and data saved since then are kept. Only the system setup goes back.")
        note.setObjectName("Muted")
        note.setWordWrap(True)
        layout.addWidget(note)

        buttons = cancel_box()
        undo = buttons.addButton("Undo update", QDialogButtonBox.ButtonRole.AcceptRole)
        undo.setProperty("primary", True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
