from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QPushButton, QVBoxLayout, QWidget,
)

from nixync_front.api import NixyncClient
from nixync_front.sample_data import Role
from nixync_front.widgets import Panel, page_header, primary_button


class RolesPage(QWidget):
    deploy_requested = Signal(str)

    def __init__(self, client: NixyncClient):
        super().__init__()
        self.client = client
        self.roles = client.list_roles()
        self.machines = client.list_machines()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        left = QWidget()
        left.setFixedWidth(240)
        left.setObjectName("RoleColumn")
        left.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        left.setStyleSheet("#RoleColumn { border-right: 1px solid #D4D7DD; }")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(12, 24, 12, 24)
        hint = QLabel("A role is a setup shared by a group of machines.")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        left_layout.addWidget(hint)
        self.role_list = QListWidget()
        self.role_list.setObjectName("RoleList")
        self.role_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        for role in self.roles:
            self.role_list.addItem(f"{role.name}\n{self._count(role)}")
        left_layout.addWidget(self.role_list, 1)
        left_layout.addWidget(QPushButton("New role"))
        layout.addWidget(left)

        self.detail = QWidget()
        self.detail_layout = QVBoxLayout(self.detail)
        self.detail_layout.setContentsMargins(28, 24, 28, 24)
        self.detail_layout.setSpacing(20)
        layout.addWidget(self.detail, 1)

        self.role_list.currentRowChanged.connect(self._show_role)
        self.role_list.setCurrentRow(0)

    def _members(self, role: Role) -> list[str]:
        return [m.name for m in self.machines if m.role == role.name]

    def _count(self, role: Role) -> str:
        n = len(self._members(role))
        return f"{n} machine" + ("" if n == 1 else "s")

    def _show_role(self, row: int):
        while (child := self.detail_layout.takeAt(0)) is not None:
            if child.widget():
                child.widget().deleteLater()
            elif child.layout():
                QWidget().setLayout(child.layout())
        if row < 0:
            return
        role = self.roles[row]
        members = self._members(role)

        self.detail_layout.addWidget(page_header(role.name, "Used by " + ", ".join(members)))

        heading = QLabel("What's included")
        heading.setStyleSheet("font-size: 16px; font-weight: 600;")
        self.detail_layout.addWidget(heading)
        grid = QGridLayout()
        grid.setSpacing(10)
        for i, bundle in enumerate(role.bundles):
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

        apps = QLabel("Extra apps: " + (", ".join(role.extra_apps) or "none"))
        self.detail_layout.addWidget(apps)
        add_row = QHBoxLayout()
        pkg = QLineEdit()
        pkg.setPlaceholderText("Search for an app to add")
        pkg.setMaximumWidth(360)
        add_row.addWidget(pkg)
        add_row.addWidget(QPushButton("Add"))
        add_row.addStretch()
        self.detail_layout.addLayout(add_row)
        self.detail_layout.addWidget(QLabel('<a href="#">Advanced: edit the Nix code for this role</a>'))
        self.detail_layout.addStretch()

        bar = Panel()
        bar_row = QHBoxLayout()
        bar_row.addWidget(QLabel("Nixync tries changes on one machine first, then updates the rest."), 1)
        bar_row.addWidget(QPushButton("Discard"))
        deploy = primary_button(f"Update {len(members)} machines")
        deploy.clicked.connect(lambda: self.deploy_requested.emit(role.name))
        bar_row.addWidget(deploy)
        bar.body.addLayout(bar_row)
        self.detail_layout.addWidget(bar)
