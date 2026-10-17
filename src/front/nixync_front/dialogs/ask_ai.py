import anthropic
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QTextBrowser, QVBoxLayout

from nixync_front import ai, style
from nixync_front.widgets import safe_emit
from nixync_front.sample_data import Machine, MachineError, Preset


class _AskSignals(QObject):
    chunk = Signal(str)
    done = Signal()
    failed = Signal(str)


class _Ask(QRunnable):
    """Streams Claude's answer off the UI thread."""

    def __init__(self, machine: Machine, error: MachineError, preset: Preset | None):
        super().__init__()
        self.machine, self.error, self.preset = machine, error, preset
        self.signals = _AskSignals()
        self.cancelled = False

    def run(self):
        try:
            for text in ai.explain(self.machine, self.error, self.preset):
                if self.cancelled:
                    return  # leaving the generator closes the stream
                safe_emit(self.signals.chunk, text)
            safe_emit(self.signals.done)
        except ai.NotConfigured:
            safe_emit(self.signals.failed, "Ask AI needs an Anthropic API key. Set ANTHROPIC_API_KEY in the "
                                     "environment you start Nixync from, then restart it.")
        except anthropic.AuthenticationError:
            safe_emit(self.signals.failed, "The Anthropic API key was rejected. Check ANTHROPIC_API_KEY.")
        except anthropic.PermissionDeniedError:
            safe_emit(self.signals.failed, "This Anthropic API key isn't allowed to use this model.")
        except anthropic.RateLimitError:
            safe_emit(self.signals.failed, "Too many requests right now. Try again in a minute.")
        except anthropic.APIConnectionError:
            safe_emit(self.signals.failed, "Couldn't reach the Anthropic API. Check your internet connection.")
        except anthropic.APIStatusError as e:
            safe_emit(self.signals.failed, f"The Anthropic API returned an error ({e.status_code}). Try again later.")


class AskAIDialog(QDialog):
    def __init__(self, machine: Machine, error: MachineError, preset: Preset | None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Ask AI · {machine.name}")
        self.setMinimumSize(680, 520)
        self.answer = ""

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        title = QLabel("Ask AI")
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        about = QLabel(f"<b>{machine.name}</b> · {error.title}")
        about.setWordWrap(True)
        layout.addWidget(about)
        note = QLabel(f"Sends this error, its log and the device's setup to Claude ({ai.MODEL}).")
        note.setObjectName("Muted")
        note.setStyleSheet("font-size: 12px;")
        layout.addWidget(note)

        self.status = QLabel("Asking Claude…")
        self.status.setObjectName("Muted")
        layout.addWidget(self.status)
        self.view = QTextBrowser()
        self.view.setObjectName("AIAnswer")
        self.view.setOpenExternalLinks(True)
        layout.addWidget(self.view, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.copy = buttons.addButton("Copy answer", QDialogButtonBox.ButtonRole.ActionRole)
        self.copy.setEnabled(False)
        self.copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.answer))
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.job = _Ask(machine, error, preset)
        self.job.signals.chunk.connect(self._on_chunk, Qt.ConnectionType.QueuedConnection)
        self.job.signals.done.connect(self._on_done, Qt.ConnectionType.QueuedConnection)
        self.job.signals.failed.connect(self._on_failed, Qt.ConnectionType.QueuedConnection)
        QThreadPool.globalInstance().start(self.job)

    def _on_chunk(self, text: str):
        if self.job.cancelled:
            return  # a chunk already in flight when the window closed
        self.answer += text
        self.status.setText("Claude is writing…")
        bar = self.view.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - 4
        self.view.setMarkdown(self.answer)
        if at_bottom:
            bar.setValue(bar.maximum())

    def _on_done(self):
        self.status.setText("Answer from Claude. Check it before acting on it.")
        self.copy.setEnabled(bool(self.answer))

    def _on_failed(self, message: str):
        self.status.setText(message)
        self.status.setObjectName("")
        style.themed(self.status, lambda: self.status.setStyleSheet(f"color: {style.PROBLEM}; font-weight: 600;"))
        self.status.setWordWrap(True)

    def done(self, result: int):
        self.job.cancelled = True  # stop streaming if the window closes early
        super().done(result)
