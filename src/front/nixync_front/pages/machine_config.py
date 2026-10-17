from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel,
    QPlainTextEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from nixync_ui import style
from nixync_front.api import ApiError, NixyncClient
from nixync_front.app_picker import AppPicker, static_tags
from nixync_front.dialogs.ask_ai import AskAIDialog
from nixync_front.settings_panel import SettingsPanel
from nixync_front.users_panel import UsersPanel
from nixync_front.pages.machines import gb
from nixync_front.sample_data import Health, Machine
from nixync_ui.widgets import (
    Panel, RingGauge, ago, clear_layout, page_header, primary_button, status_row, status_text, timestamp,
)

def health_color(health: Health) -> str:
    return {Health.OK: style.OK, Health.PROBLEM: style.PROBLEM, Health.UNREACHABLE: style.OFFLINE}[health]


def section_title(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet("font-size: 16px; font-weight: 600; border: none;")
    return label


def fact(label: str, value: str) -> QWidget:
    box = QWidget()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(2)
    name = QLabel(label)
    name.setObjectName("Muted")
    name.setStyleSheet("border: none;")
    text = QLabel(value)
    text.setStyleSheet("font-weight: 600; border: none;")
    text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    layout.addWidget(name)
    layout.addWidget(text)
    return box


class MachineConfigPage(QWidget):
    """Settings for one machine: status, build history, errors and its apps."""

    back_requested = Signal()
    message = Signal(str)
    requests_requested = Signal(str)
    undo_requested = Signal(str)
    apply_requested = Signal(str, list)
    remove_requested = Signal(str)

    def __init__(self, client: NixyncClient):
        super().__init__()
        self.client = client
        self.machine: Machine | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)

        self.content = QWidget()
        self.layout_ = QVBoxLayout(self.content)
        self.layout_.setContentsMargins(28, 24, 28, 24)
        self.layout_.setSpacing(20)
        scroll.setWidget(self.content)

    def show_machine(self, name: str):
        self.machine = self.client.get_machine(name)
        self._build()

    def refresh(self):
        """Re-read this device from the server and redraw.

        Telemetry, deployment status and the installed app list all change while the
        page is open, so this refetches rather than just repainting what it had.
        """
        if self.machine is None:
            return
        try:
            self.machine = self.client.get_machine(self.machine.name)
        except ApiError as e:
            self.message.emit(f"Couldn't refresh: {e}")
            return
        self._build()

    def _preset(self):
        """This device's preset, or None if it has none or the server is unreachable."""
        try:
            return self.client.get_preset(self.machine.preset)
        except ApiError:
            return None

    def _agent_id(self) -> str:
        """The id this device's agent connects with — unknown if the server is down."""
        try:
            return self.client.machine_id(self.machine.name)
        except ApiError:
            return "Unavailable"

    def _build(self):
        clear_layout(self.layout_)
        m = self.machine

        back = QPushButton("← Devices")
        back.setProperty("link", True)
        back.clicked.connect(self.back_requested)
        remove = QPushButton("Remove device")
        remove.setProperty("link", True)
        remove.setToolTip("Unregister this device from the fleet")
        remove.clicked.connect(lambda: self.remove_requested.emit(m.name))
        refresh = QPushButton("Refresh")
        refresh.setProperty("link", True)
        refresh.setToolTip("Re-read this device from the server")
        refresh.clicked.connect(self.refresh)
        top = QHBoxLayout()
        top.addWidget(back)
        top.addStretch()
        top.addWidget(refresh)
        top.addWidget(remove)
        self.layout_.addLayout(top)

        header = QHBoxLayout()
        header.addWidget(page_header(m.name, f"{m.preset} · {m.group}"), 1)
        header.addWidget(status_text(health_color(m.health), m.health.value))
        self.layout_.addLayout(header)

        self.layout_.addWidget(self._overview())
        if m.errors:
            self.layout_.addWidget(self._errors())
        settings = SettingsPanel(m.name, m.settings)
        settings.applied.connect(self._apply_settings)
        self.layout_.addWidget(settings)
        users = UsersPanel(self.client, m, can_grant_admin=True)
        users.message.connect(self.message)
        self.layout_.addWidget(users)
        self.layout_.addWidget(self._apps_panel())
        self.layout_.addWidget(self._history())
        self.layout_.addStretch()

    def _overview(self) -> Panel:
        m = self.machine
        panel = Panel()
        grid = QGridLayout()
        grid.setHorizontalSpacing(32)
        grid.setVerticalSpacing(14)
        last_ok = m.last_successful_build
        latest = m.builds[0] if m.builds else None
        grid.addWidget(fact("Last successful build",
                            timestamp(last_ok.finished) if last_ok else "Never"), 0, 0)
        grid.addWidget(fact("Running generation",
                            str(last_ok.generation) if last_ok else "Unknown"), 0, 1)
        grid.addWidget(fact("Last attempt",
                            f"{'Succeeded' if latest.ok else 'Failed'}, {ago(latest.finished)}"
                            if latest else "None yet"), 0, 2)
        grid.addWidget(fact("Address", m.address or "Not set"), 1, 0)
        grid.addWidget(fact("NixOS", m.nixos_version), 1, 1)
        grid.addWidget(fact("Preset", m.preset or "None"), 1, 2)
        # The operator has to type this into the agent on the device itself, so it is
        # shown in full and stays selectable rather than being truncated.
        grid.addWidget(fact("Agent ID", self._agent_id()), 2, 0, 1, 3)
        row = QHBoxLayout()
        row.setSpacing(24)
        row.addLayout(grid, 1)
        disk = ""
        if m.disk_used_gb is not None and m.disk_total_gb:
            disk = f"{gb(m.disk_used_gb)} / {gb(m.disk_total_gb)}"
        for gauge in (RingGauge("CPU", m.cpu_percent), RingGauge("RAM", m.ram_percent),
                      RingGauge("Disk", m.disk_percent, disk)):
            row.addWidget(gauge, 0, Qt.AlignmentFlag.AlignVCenter)
        panel.body.addLayout(row)
        return panel

    def _errors(self) -> Panel:
        m = self.machine
        panel = Panel()
        count = len(m.errors)
        panel.body.addWidget(section_title(f"{count} problem{'' if count == 1 else 's'}"))
        for error in m.errors:
            row = QHBoxLayout()
            row.addWidget(status_row(style.PROBLEM, f"<b>{error.title}</b> · {ago(error.when)}"), 1)
            if m.health is Health.PROBLEM:
                undo = QPushButton("Undo update")
                undo.clicked.connect(lambda: self.undo_requested.emit(m.name))
                row.addWidget(undo)
            panel.body.addLayout(row)
            details = QHBoxLayout()
            if error.log:
                toggle = QPushButton("Show technical details")
                toggle.setCheckable(True)
                log = QPlainTextEdit(error.log)
                log.setObjectName("Log")
                log.setReadOnly(True)
                log.setVisible(False)
                log.setFixedHeight(96)
                toggle.toggled.connect(log.setVisible)
                toggle.toggled.connect(lambda on, t=toggle: t.setText(
                    "Hide technical details" if on else "Show technical details"))
                details.addWidget(toggle)
            ask = QPushButton("Ask AI")
            ask.setToolTip("Get an explanation and a suggested fix from Claude")
            ask.clicked.connect(lambda _=False, e=error: self._ask_ai(e))
            details.addWidget(ask)
            details.addStretch()
            panel.body.addLayout(details)
            if error.log:
                panel.body.addWidget(log)
        return panel

    def _apply_settings(self, settings):
        try:
            self.client.save_settings(self.machine.name, settings)
        except ApiError as e:
            self.message.emit(f"Couldn't apply settings to {self.machine.name}: {e}")
            return
        self.machine.settings = settings
        self.message.emit(f"Applying system settings to {self.machine.name}…")

    def _ask_ai(self, error):
        AskAIDialog(self.machine, error, self._preset(), self).exec()

    def _apps_panel(self) -> Panel:
        panel = Panel()
        panel.body.addWidget(section_title("Apps"))

        preset = self._preset()
        from_preset = preset.extra_apps if preset else []
        count = len(from_preset)
        line = QHBoxLayout()
        line.setSpacing(6)
        note = QLabel(f"Includes {count} app{'' if count == 1 else 's'} from the {self.machine.preset} preset"
                      + (" ·" if count else ". Change those on the Presets page."))
        note.setObjectName("Muted")
        line.addWidget(note)
        if count:
            preset_tags = static_tags(from_preset)
            preset_tags.setVisible(False)
            toggle = QPushButton("Show")
            toggle.setProperty("link", True)
            toggle.clicked.connect(lambda: (preset_tags.setVisible(not preset_tags.isVisible()),
                                            toggle.setText("Hide" if preset_tags.isVisible() else "Show")))
            line.addWidget(toggle)
        line.addStretch()
        panel.body.addLayout(line)
        if count:
            panel.body.addWidget(preset_tags)

        pending = self.client.pending_requests(self.machine.name)
        if pending:
            count = len(pending)
            row = QHBoxLayout()
            text = QLabel(f"<b>{count} pending request{'' if count == 1 else 's'}</b> from people on "
                          f"{self.machine.name}: " + ", ".join(r.app for r in pending))
            text.setWordWrap(True)
            row.addWidget(text, 1)
            review = QPushButton("Review")
            review.clicked.connect(lambda: self.requests_requested.emit(self.machine.name))
            row.addWidget(review)
            panel.body.addLayout(row)

        panel.body.addSpacing(4)
        own = QLabel("On this device only")
        own.setStyleSheet("font-weight: 600;")
        panel.body.addWidget(own)
        self.picker = AppPicker(self.client, self.machine.extra_apps,
                                f"Search nixpkgs for an app to add to {self.machine.name}",
                                "No extra apps on this device yet.")
        self.picker.changed.connect(self._on_apps_changed)
        panel.body.addWidget(self.picker)

        footer = QHBoxLayout()
        self.pending = QLabel()
        self.pending.setObjectName("Muted")
        self.pending.setStyleSheet("border: none;")
        footer.addWidget(self.pending, 1)
        self.discard = QPushButton("Discard")
        self.discard.clicked.connect(self.picker.discard)
        self.apply = primary_button(f"Update {self.machine.name}")
        self.apply.clicked.connect(lambda: self.apply_requested.emit(self.machine.name, list(self.picker.apps)))
        footer.addWidget(self.discard)
        footer.addWidget(self.apply)
        panel.body.addLayout(footer)

        self._on_apps_changed()
        return panel

    def _on_apps_changed(self):
        text = self.picker.changes_text()
        self.pending.setText(text)
        self.apply.setEnabled(bool(text))
        self.discard.setEnabled(bool(text))

    def _history(self) -> Panel:
        panel = Panel()
        panel.body.addWidget(section_title("Recent builds"))
        for build in self.machine.builds:
            row = QHBoxLayout()
            when = QLabel(timestamp(build.finished))
            when.setFixedWidth(280)
            row.addWidget(when)
            gen = QLabel(f"Generation {build.generation}")
            gen.setObjectName("Muted")
            gen.setFixedWidth(120)
            row.addWidget(gen)
            row.addWidget(QLabel(build.summary) if build.ok else status_text(style.PROBLEM, build.summary), 1)
            panel.body.addLayout(row)
        if not self.machine.builds:
            panel.body.addWidget(QLabel("No builds yet."))
        return panel
