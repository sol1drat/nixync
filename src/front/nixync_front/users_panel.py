from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QVBoxLayout, QWidget,
)

from nixync_front import nix_config
from nixync_ui import style
from nixync_front.api import ApiError, NixyncClient
from nixync_front.sample_data import LocalUser, Machine
from nixync_ui.widgets import Panel, cancel_box, clear_layout, primary_button, status_text

MIN_PASSWORD = 8


class AddUserDialog(QDialog):
    def __init__(self, device: str, taken: list[str], can_grant_admin: bool, parent=None):
        super().__init__(parent)
        self.taken = taken
        self.setWindowTitle(f"Add user · {device}")
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        title = QLabel("Add user")
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        intro = QLabel(f"A new login account on {device}.")
        intro.setObjectName("Muted")
        layout.addWidget(intro)

        form = QFormLayout()
        form.setVerticalSpacing(10)
        self.username = QLineEdit()
        self.username.setPlaceholderText("nino")
        self.full_name = QLineEdit()
        self.full_name.setPlaceholderText("Nino Beridze (optional)")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirm = QLineEdit()
        self.confirm.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Username", self.username)
        form.addRow("Full name", self.full_name)
        form.addRow("Password", self.password)
        form.addRow("Repeat password", self.confirm)
        layout.addLayout(form)

        self.admin = QCheckBox("Administrator (can use sudo)")
        self.admin.setVisible(can_grant_admin)
        layout.addWidget(self.admin)

        note = QLabel("The password is set on the device itself. Nixync doesn't keep it in the configuration.")
        note.setObjectName("Muted")
        note.setWordWrap(True)
        note.setStyleSheet("font-size: 12px;")
        layout.addWidget(note)

        self.problem = QLabel()
        self.problem.setWordWrap(True)
        style.themed(self.problem, lambda: self.problem.setStyleSheet(f"color: {style.PROBLEM};"))
        layout.addWidget(self.problem)

        buttons = cancel_box()
        self.add = buttons.addButton("Add user", QDialogButtonBox.ButtonRole.AcceptRole)
        self.add.setProperty("primary", True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        for field in (self.username, self.password, self.confirm):
            field.textChanged.connect(self._validate)
        self._validate()

    def _error(self) -> str:
        name = self.username.text().strip()
        if not name:
            return ""  # nothing typed yet: just keep the button disabled
        if error := nix_config.username_error(name, self.taken):
            return error
        if not self.password.text():
            return ""
        if len(self.password.text()) < MIN_PASSWORD:
            return f"Use at least {MIN_PASSWORD} characters for the password."
        if self.confirm.text() and self.confirm.text() != self.password.text():
            return "The passwords don't match."
        return ""

    def _validate(self):
        error = self._error()
        self.problem.setText(error)
        self.problem.setVisible(bool(error))
        complete = (self.username.text().strip() and len(self.password.text()) >= MIN_PASSWORD
                    and self.confirm.text() == self.password.text())
        self.add.setEnabled(bool(complete) and not error)

    def user(self) -> LocalUser:
        return LocalUser(self.username.text().strip(), self.full_name.text().strip(), self.admin.isChecked())


class UsersPanel(Panel):
    """Login accounts on one device (users.users.<name>).

    Clients (can_grant_admin=False) can add and remove regular users; administrator accounts
    and admin rights are left to the Nixync administrator.
    """

    message = Signal(str)

    def __init__(self, client: NixyncClient, machine: Machine, can_grant_admin: bool, current_user: str = "",
                 show_title: bool = True):
        super().__init__()
        self.client = client
        self.machine = machine
        self.can_grant_admin = can_grant_admin
        self.current_user = current_user

        header = QHBoxLayout()
        if show_title:  # the client's Users page already has the title as its page header
            title = QLabel("Users")
            title.setStyleSheet("font-size: 16px; font-weight: 600; border: none;")
            header.addWidget(title)
        header.addStretch()
        add = QPushButton("Add user")
        add.clicked.connect(self._add)
        header.addWidget(add)
        self.body.addLayout(header)

        rows = QWidget()
        self.rows = QVBoxLayout(rows)
        self.rows.setContentsMargins(0, 0, 0, 0)
        self.rows.setSpacing(0)
        self.body.addWidget(rows)
        self._render()

    @property
    def users(self) -> list[LocalUser]:
        return self.machine.settings.users  # shared with the settings panel; edited in place

    def _render(self):
        clear_layout(self.rows)
        if not self.users:
            empty = QLabel("No user accounts yet.")
            empty.setObjectName("Muted")
            self.rows.addWidget(empty)
        for user in self.users:
            row = QWidget()
            line = QHBoxLayout(row)
            line.setContentsMargins(0, 8, 0, 8)
            line.setSpacing(12)
            name = QLabel(user.name)
            name.setStyleSheet("font-weight: 600; border: none;")
            name.setMinimumWidth(120)
            line.addWidget(name)
            full = QLabel(user.full_name)
            full.setObjectName("Muted")
            line.addWidget(full, 1)
            if user.name == self.current_user:
                you = QLabel("You")
                you.setObjectName("Muted")
                line.addWidget(you)
            if self.can_grant_admin:
                admin = QCheckBox("Administrator")
                admin.setChecked(user.admin)
                admin.toggled.connect(lambda on, u=user: self._set_admin(u, on))
                line.addWidget(admin)
            elif user.admin:
                line.addWidget(status_text(style.ACCENT, "Administrator"))
            remove = QPushButton("Remove")
            remove.setProperty("link", True)
            if user.name == self.current_user:
                remove.setEnabled(False)
                remove.setToolTip("You can't remove your own account.")
            elif user.admin and not self.can_grant_admin:
                remove.setEnabled(False)
                remove.setToolTip("Only your Nixync administrator can remove administrator accounts.")
            remove.clicked.connect(lambda _=False, u=user: self._remove(u))
            line.addWidget(remove)
            self.rows.addWidget(row)

    def _save(self, text: str, passwords: dict[str, str] | None = None):
        try:
            self.client.save_settings(self.machine.name, self.machine.settings, passwords)
        except ApiError as e:
            self.message.emit(f"Couldn't update users on {self.machine.name}: {e}")
            return
        self._render()
        self.message.emit(text)

    def _add(self):
        dialog = AddUserDialog(self.machine.name, [u.name for u in self.users], self.can_grant_admin, self)
        if dialog.exec():
            user = dialog.user()
            self.users.append(user)
            self._save(f"Adding user {user.name} on {self.machine.name}…", {user.name: dialog.password.text()})

    def _remove(self, user: LocalUser):
        answer = QMessageBox.question(
            self, "Remove user",
            f"Remove {user.name} from {self.machine.name}?\n\nThey won't be able to log in any more. "
            "Their files in /home stay on the device.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.users.remove(user)
        self._save(f"Removing user {user.name} from {self.machine.name}…")

    def _set_admin(self, user: LocalUser, admin: bool):
        user.admin = admin
        self._save(f"{user.name} is {'now' if admin else 'no longer'} an administrator on {self.machine.name}.")
