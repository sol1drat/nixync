from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QGridLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget,
)

from nixync_front import style
from nixync_front.api import NixyncClient
from nixync_front.app_picker import AppPicker
from nixync_front.sample_data import Preset
from nixync_front.widgets import Panel, clear_layout, page_header, primary_button


class PresetsPage(QWidget):
    deploy_requested = Signal(str)

    def __init__(self, client: NixyncClient):
        super().__init__()
        self.client = client
        self.presets = client.list_presets()
        self.machines = client.list_machines()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        left = QWidget()
        left.setFixedWidth(240)
        left.setObjectName("PresetColumn")
        left.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        style.themed(left, lambda: left.setStyleSheet(
            f"#PresetColumn {{ border-right: 1px solid {style.color('border')}; }}"))
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(12, 24, 12, 24)
        hint = QLabel("A preset is a setup shared by a group of devices.")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        left_layout.addWidget(hint)
        self.preset_list = QListWidget()
        self.preset_list.setObjectName("PresetList")
        self.preset_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.preset_list.setTextElideMode(Qt.TextElideMode.ElideNone)
        for preset in self.presets:
            item = QListWidgetItem(f"{preset.name}\n{self._count(preset)}")
            item.setSizeHint(QSize(200, 68))
            self.preset_list.addItem(item)
        left_layout.addWidget(self.preset_list, 1)
        left_layout.addWidget(QPushButton("New preset"))
        layout.addWidget(left)

        self.detail = QWidget()
        self.detail_layout = QVBoxLayout(self.detail)
        self.detail_layout.setContentsMargins(28, 24, 28, 24)
        self.detail_layout.setSpacing(20)
        layout.addWidget(self.detail, 1)

        self.preset_list.currentRowChanged.connect(self._show_preset)
        self.preset_list.setCurrentRow(0)

    def _members(self, preset: Preset) -> list[str]:
        return [m.name for m in self.machines if m.preset == preset.name]

    def _count(self, preset: Preset) -> str:
        n = len(self._members(preset))
        return f"{n} device" + ("" if n == 1 else "s")

    def _show_preset(self, row: int):
        clear_layout(self.detail_layout)
        if row < 0:
            return
        preset = self.presets[row]
        members = self._members(preset)

        self.detail_layout.addWidget(page_header(preset.name, "Used by " + ", ".join(members)))

        heading = QLabel("What's included")
        heading.setStyleSheet("font-size: 16px; font-weight: 600;")
        self.detail_layout.addWidget(heading)
        grid = QGridLayout()
        grid.setSpacing(10)
        for i, bundle in enumerate(preset.bundles):
            card = Panel("Card")
            box = QCheckBox(bundle.name)
            box.setChecked(bundle.enabled)
            box.setStyleSheet("font-weight: 600; border: none;")
            desc = QLabel(bundle.description)
            desc.setObjectName("Muted")
            desc.setStyleSheet("border: none;")
            card.body.addWidget(box)
            card.body.addWidget(desc)
            grid.addWidget(card, i // 2, i % 2)
        self.detail_layout.addLayout(grid)

        apps_heading = QLabel("Extra apps")
        apps_heading.setStyleSheet("font-size: 16px; font-weight: 600;")
        self.detail_layout.addWidget(apps_heading)
        self.picker = AppPicker(self.client, preset.extra_apps,
                                f"Search nixpkgs for an app to add to every {preset.name}",
                                "No extra apps in this preset yet.")
        self.detail_layout.addWidget(self.picker)
        self.detail_layout.addWidget(QLabel('<a href="#">Advanced: edit the Nix code for this preset</a>'))
        self.detail_layout.addStretch()

        bar = Panel()
        bar_row = QHBoxLayout()
        info = QVBoxLayout()
        info.setSpacing(2)
        info.addWidget(QLabel("Nixync tries changes on one device first, then updates the rest."))
        pending = QLabel()
        pending.setObjectName("Muted")
        info.addWidget(pending)
        bar_row.addLayout(info, 1)
        discard = QPushButton("Discard")
        discard.clicked.connect(self.picker.discard)
        bar_row.addWidget(discard)
        deploy = primary_button(f"Update {len(members)} device" + ("" if len(members) == 1 else "s"))
        deploy.clicked.connect(lambda: self._deploy(preset))
        bar_row.addWidget(deploy)

        def on_changed():
            text = self.picker.changes_text()
            pending.setText(text)
            pending.setVisible(bool(text))
            discard.setEnabled(bool(text))
        self.picker.changed.connect(on_changed)
        on_changed()
        bar.body.addLayout(bar_row)
        self.detail_layout.addWidget(bar)

    def _deploy(self, preset: Preset):
        # TODO: send the preset's new app list to the server, which then rolls it out.
        preset.extra_apps[:] = self.picker.apps
        self.picker.mark_saved()
        self.deploy_requested.emit(preset.name)
