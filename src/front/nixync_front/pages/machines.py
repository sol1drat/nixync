from PySide6.QtCore import QSize, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QVBoxLayout, QWidget,
)

from nixync_front import style
from nixync_front.api import NixyncClient
from nixync_front.sample_data import Health, Machine
from nixync_front.widgets import Panel, page_header, primary_button, status_row

HEALTH_COLOR = {Health.OK: style.OK, Health.PROBLEM: style.PROBLEM, Health.UNREACHABLE: style.OFFLINE}


class MachineCard(Panel):
    def __init__(self, machine: Machine):
        super().__init__("Card")
        name = QLabel(machine.name)
        name.setStyleSheet("font-size: 16px; font-weight: 600; border: none;")
        role = QLabel(machine.role)
        role.setObjectName("Muted")
        self.body.addWidget(name)
        self.body.addWidget(role)
        self.body.addWidget(status_row(HEALTH_COLOR[machine.health], machine.health.value))


class MachinesPage(QWidget):
    add_machine_requested = Signal()
    change_roles_requested = Signal()
    show_update_requested = Signal()
    undo_requested = Signal(str)

    def __init__(self, client: NixyncClient):
        super().__init__()
        self.client = client
        self.machines = client.list_machines()
        self.group = "All"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(20)

        top = QHBoxLayout()
        top.addWidget(page_header("Machines"))
        top.addStretch()
        add = QPushButton("Add machine")
        add.clicked.connect(self.add_machine_requested)
        change = primary_button("Change what's installed")
        change.clicked.connect(self.change_roles_requested)
        top.addWidget(add)
        top.addWidget(change)
        layout.addLayout(top)

        layout.addWidget(self._attention_panel())

        filters = QHBoxLayout()
        self.segments = QButtonGroup(self)
        groups = ["All"] + sorted({m.group for m in self.machines})
        for group in groups:
            count = len(self._in_group(group))
            button = QPushButton(f"{group} ({count})")
            button.setProperty("segment", True)
            button.setCheckable(True)
            button.setChecked(group == "All")
            button.clicked.connect(lambda _=False, g=group: self._set_group(g))
            self.segments.addButton(button)
            filters.addWidget(button)
        filters.addStretch()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Find a machine")
        self.search.setFixedWidth(220)
        self.search.textChanged.connect(self._refresh)
        filters.addWidget(self.search)
        layout.addLayout(filters)

        self.grid = QListWidget()
        self.grid.setViewMode(QListWidget.ViewMode.IconMode)
        self.grid.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.grid.setMovement(QListWidget.Movement.Static)
        self.grid.setSpacing(7)
        self.grid.setGridSize(QSize(244, 120))
        self.grid.setStyleSheet("QListWidget { background: transparent; border: none; }")
        layout.addWidget(self.grid, 1)
        self._refresh()

    def _attention_panel(self) -> Panel:
        panel = Panel("Attention")
        broken = [m for m in self.machines if m.health is not Health.OK]
        panel.setVisible(bool(broken))
        title = QLabel(f"{len(broken)} machines need your attention")
        title.setStyleSheet("font-size: 16px; font-weight: 600; border: none;")
        panel.body.addWidget(title)
        for machine in broken:
            row = QHBoxLayout()
            row.addWidget(status_row(HEALTH_COLOR[machine.health], f"<b>{machine.name}</b> {machine.note}"), 1)
            if machine.health is Health.PROBLEM:
                details = QPushButton("See what happened")
                details.clicked.connect(self.show_update_requested)
                undo = QPushButton("Undo update")
                undo.clicked.connect(lambda _=False, n=machine.name: self.undo_requested.emit(n))
                row.addWidget(details)
                row.addWidget(undo)
            else:
                row.addWidget(QPushButton("Try again"))
            panel.body.addLayout(row)
        return panel

    def _in_group(self, group: str) -> list[Machine]:
        return [m for m in self.machines if group == "All" or m.group == group]

    def _set_group(self, group: str):
        self.group = group
        self._refresh()

    def _refresh(self):
        needle = self.search.text().strip().lower()
        self.grid.clear()
        for machine in self._in_group(self.group):
            if needle and needle not in machine.name.lower():
                continue
            item = QListWidgetItem(self.grid)
            item.setSizeHint(QSize(230, 106))
            self.grid.setItemWidget(item, MachineCard(machine))
