from dataclasses import replace
from zoneinfo import available_timezones

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QCompleter, QFormLayout, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from nixync_front import nix_config, style
from nixync_front.sample_data import SystemSettings
from nixync_front.widgets import Panel, primary_button

TIMEZONES = sorted(available_timezones())


def group_title(text: str) -> QLabel:
    label = QLabel(text.upper())
    label.setObjectName("Muted")
    label.setStyleSheet("font-size: 12px; font-weight: 600;")
    return label


class SettingsPanel(Panel):
    """Editable NixOS settings for one device: hostname, network, SSH and services."""

    applied = Signal(object)  # SystemSettings

    def __init__(self, device: str, settings: SystemSettings, admin: bool = True):
        """With admin=False (the client app), only settings a device's user may change are shown:
        hostname, time zone, DNS, Bluetooth and sound. Firewall, SSH, Docker and unfree packages
        stay with the administrator, since they can lock Nixync out or grant root-level access."""
        super().__init__()
        self.device = device
        self.saved = settings
        self.admin = admin

        header = QHBoxLayout()
        title = QLabel("System settings")
        title.setStyleSheet("font-size: 16px; font-weight: 600; border: none;")
        header.addWidget(title)
        header.addStretch()
        self.nix_toggle = QPushButton("Show Nix")
        self.nix_toggle.setProperty("link", True)
        self.nix_toggle.clicked.connect(self._toggle_nix)
        header.addWidget(self.nix_toggle)
        self.body.addLayout(header)

        columns = QGridLayout()
        columns.setHorizontalSpacing(40)
        columns.setColumnStretch(0, 1)
        columns.setColumnStretch(1, 1)

        # --- network ---
        network = QVBoxLayout()
        network.setSpacing(8)
        network.addWidget(group_title("Network"))
        form = QFormLayout()
        form.setVerticalSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        self.hostname = QLineEdit(settings.hostname)
        self.hostname.setPlaceholderText("lab-05")
        self.hostname.setToolTip("networking.hostName")
        form.addRow("Hostname", self.hostname)
        self.timezone = QComboBox()
        self.timezone.setEditable(True)
        self.timezone.addItems(TIMEZONES)
        self.timezone.setCurrentText(settings.timezone)
        completer = QCompleter(TIMEZONES, self.timezone)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.timezone.setCompleter(completer)
        self.timezone.setToolTip("time.timeZone")
        form.addRow("Time zone", self.timezone)
        self.nameservers = QLineEdit(", ".join(settings.nameservers))
        self.nameservers.setPlaceholderText("9.9.9.9, 1.1.1.1")
        self.nameservers.setToolTip("networking.nameservers")
        form.addRow("DNS servers", self.nameservers)
        self.firewall = QCheckBox("On")
        self.firewall.setChecked(settings.firewall)
        self.firewall.setToolTip("networking.firewall.enable")
        form.addRow("Firewall", self.firewall)
        self.ports = QLineEdit(", ".join(str(p) for p in settings.open_tcp_ports))
        self.ports.setPlaceholderText("22, 80, 443")
        self.ports.setToolTip("networking.firewall.allowedTCPPorts")
        form.addRow("Open TCP ports", self.ports)
        network.addLayout(form)
        network.addStretch()
        columns.addLayout(network, 0, 0)

        # --- access & services ---
        services = QVBoxLayout()
        services.setSpacing(8)
        self.access_title = group_title("Remote access")
        services.addWidget(self.access_title)
        self.ssh = QCheckBox("SSH server")
        self.ssh.setChecked(settings.ssh)
        self.ssh.setToolTip("services.openssh.enable")
        services.addWidget(self.ssh)
        self.ssh_password = QCheckBox("Allow password login")
        self.ssh_password.setChecked(settings.ssh_password_login)
        self.ssh_password.setToolTip("services.openssh.settings.PasswordAuthentication")
        services.addWidget(self.ssh_password)
        root = QFormLayout()
        self.root_login = QComboBox()
        self.root_login.addItems(nix_config.ROOT_LOGIN)
        self.root_login.setCurrentText(settings.ssh_root_login)
        self.root_login.setToolTip("services.openssh.settings.PermitRootLogin")
        self.root_login.setMaximumWidth(240)
        self.root_label = QLabel("Root login")
        root.addRow(self.root_label, self.root_login)
        services.addLayout(root)
        services.addSpacing(6)
        services.addWidget(group_title("Services"))
        self.bluetooth = QCheckBox("Bluetooth")
        self.bluetooth.setChecked(settings.bluetooth)
        self.bluetooth.setToolTip("hardware.bluetooth.enable")
        self.sound = QCheckBox("Sound (PipeWire)")
        self.sound.setChecked(settings.sound)
        self.sound.setToolTip("services.pipewire.enable")
        self.docker = QCheckBox("Docker")
        self.docker.setChecked(settings.docker)
        self.docker.setToolTip("virtualisation.docker.enable")
        self.unfree = QCheckBox("Allow unfree packages")
        self.unfree.setChecked(settings.allow_unfree)
        self.unfree.setToolTip("nixpkgs.config.allowUnfree")
        for box in (self.bluetooth, self.sound, self.docker, self.unfree):
            services.addWidget(box)
        services.addStretch()
        columns.addLayout(services, 0, 1)
        self.body.addLayout(columns)

        if not admin:
            form.setRowVisible(self.firewall, False)
            form.setRowVisible(self.ports, False)
            for widget in (self.access_title, self.ssh, self.ssh_password, self.root_login, self.root_label,
                           self.docker, self.unfree, self.nix_toggle):
                widget.setVisible(False)
            note = QLabel("Firewall, remote access, Docker and unfree packages are managed by your administrator.")
            note.setObjectName("Muted")
            note.setWordWrap(True)
            note.setStyleSheet("font-size: 12px; border: none;")
            self.body.addWidget(note)

        self.problem = QLabel()
        self.problem.setStyleSheet(f"color: {style.PROBLEM}; border: none;")
        self.problem.setWordWrap(True)
        self.body.addWidget(self.problem)

        self.nix = QPlainTextEdit()
        self.nix.setObjectName("Log")
        self.nix.setReadOnly(True)
        self.nix.setFixedHeight(320)
        self.nix.setVisible(False)
        self.body.addWidget(self.nix)

        footer = QHBoxLayout()
        self.pending = QLabel()
        self.pending.setObjectName("Muted")
        self.pending.setStyleSheet("border: none;")
        self.pending.setWordWrap(True)
        footer.addWidget(self.pending, 1)
        self.discard = QPushButton("Discard")
        self.discard.clicked.connect(self._discard)
        self.apply = primary_button("Apply settings")
        self.apply.clicked.connect(self._apply)
        footer.addWidget(self.discard)
        footer.addWidget(self.apply)
        self.body.addLayout(footer)

        for edit in (self.hostname, self.nameservers, self.ports):
            edit.textChanged.connect(self._update)
        for combo in (self.timezone, self.root_login):
            combo.currentTextChanged.connect(self._update)
        for box in (self.firewall, self.ssh, self.ssh_password, self.bluetooth, self.sound, self.docker,
                    self.unfree):
            box.toggled.connect(self._update)
        self.ssh.toggled.connect(lambda on: (self.ssh_password.setEnabled(on), self.root_login.setEnabled(on)))
        self.firewall.toggled.connect(self.ports.setEnabled)
        self.ssh_password.setEnabled(settings.ssh)
        self.root_login.setEnabled(settings.ssh)
        self.ports.setEnabled(settings.firewall)
        style.themed(self, self._update)  # the warning color follows the theme

    # --- state -----------------------------------------------------------

    def _current(self) -> tuple[SystemSettings, str, str]:
        """The settings as edited, the first validation error (blocks applying) and a warning."""
        hostname = self.hostname.text().strip()
        nameservers, ns_error = nix_config.parse_nameservers(self.nameservers.text())
        ports, port_error = nix_config.parse_ports(self.ports.text())
        timezone = self.timezone.currentText().strip()
        settings = replace(
            self.saved, hostname=hostname, timezone=timezone, nameservers=nameservers,
            firewall=self.firewall.isChecked(), open_tcp_ports=ports, ssh=self.ssh.isChecked(),
            ssh_password_login=self.ssh_password.isChecked(), ssh_root_login=self.root_login.currentText(),
            bluetooth=self.bluetooth.isChecked(), sound=self.sound.isChecked(), docker=self.docker.isChecked(),
            allow_unfree=self.unfree.isChecked(),
        )
        tz_error = "" if timezone in TIMEZONES else f"“{timezone}” isn't a known time zone."
        # NixOS opens port 22 itself (services.openssh.openFirewall), but without SSH
        # Nixync can't reach the device at all.
        warning = "" if settings.ssh else "With SSH off, Nixync can't reach this device to update it again."
        error = nix_config.hostname_error(hostname) or tz_error or ns_error or port_error
        return settings, error, warning

    def _update(self):
        settings, error, warning = self._current()
        self.problem.setText(error or warning)
        self.problem.setStyleSheet(f"color: {style.PROBLEM if error else style.WARNING}; border: none;")
        self.problem.setVisible(bool(error or warning))
        changes = nix_config.changed_fields(self.saved, settings)
        self.pending.setText(("Not applied yet: " + ", ".join(changes) + ".") if changes else "")
        self.apply.setEnabled(bool(changes) and not error)
        self.discard.setEnabled(bool(changes))
        self.nix.setPlainText(nix_config.render(settings))

    def _toggle_nix(self):
        self.nix.setVisible(not self.nix.isVisible())
        self.nix_toggle.setText("Hide Nix" if self.nix.isVisible() else "Show Nix")

    def _discard(self):
        s = self.saved
        self.hostname.setText(s.hostname)
        self.timezone.setCurrentText(s.timezone)
        self.nameservers.setText(", ".join(s.nameservers))
        self.firewall.setChecked(s.firewall)
        self.ports.setText(", ".join(str(p) for p in s.open_tcp_ports))
        self.ssh.setChecked(s.ssh)
        self.ssh_password.setChecked(s.ssh_password_login)
        self.root_login.setCurrentText(s.ssh_root_login)
        self.bluetooth.setChecked(s.bluetooth)
        self.sound.setChecked(s.sound)
        self.docker.setChecked(s.docker)
        self.unfree.setChecked(s.allow_unfree)
        self._update()

    def _apply(self):
        settings, error, _warning = self._current()
        if error:
            return
        self.saved = settings
        self.applied.emit(settings)
        self._update()
