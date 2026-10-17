from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout

from nixync_front.api import NixyncClient
from nixync_front.app_picker import AppPicker
from nixync_front.sample_data import Health


class AddAppsDialog(QDialog):
    """Pick apps from search.nixos.org and add them to several devices at once."""

    def __init__(self, client: NixyncClient, devices: list[str], parent=None):
        super().__init__(parent)
        self.devices = devices
        count = len(devices)
        plural = "" if count == 1 else "s"
        self.setWindowTitle("Add apps")
        self.setMinimumWidth(600)
        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        title = QLabel(f"Add apps to {count} device{plural}")
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        names = QLabel(", ".join(devices))
        names.setObjectName("Muted")
        names.setWordWrap(True)
        layout.addWidget(names)

        offline = [d for d in devices if client.get_machine(d).health is Health.UNREACHABLE]
        if offline:
            note = QLabel(f"{', '.join(offline)} {'is' if len(offline) == 1 else 'are'} offline and will get "
                          "the apps the next time Nixync reaches them.")
            note.setWordWrap(True)
            layout.addWidget(note)

        hint = QLabel("Devices that already have an app, from their preset or their own list, are skipped for it.")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.picker = AppPicker(client, [], "Search nixpkgs for an app to add", "No apps picked yet.",
                                mark_unsaved=False)
        layout.addWidget(self.picker)
        layout.addStretch()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.add = buttons.addButton(f"Add to {count} device{plural}", QDialogButtonBox.ButtonRole.AcceptRole)
        self.add.setProperty("primary", True)
        self.add.setEnabled(False)
        # Enter in the search box adds the top result; it must not also press the default button.
        self.add.setAutoDefault(False)
        self.add.setDefault(False)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.picker.changed.connect(lambda: self.add.setEnabled(bool(self.picker.apps)))

    @property
    def apps(self) -> list[str]:
        return list(self.picker.apps)
