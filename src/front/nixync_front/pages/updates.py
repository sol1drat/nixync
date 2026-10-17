from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from nixync_front import style
from nixync_front.api import NixyncClient
from nixync_front.sample_data import HostResult, Step
from nixync_front.widgets import Panel, dot, page_header, primary_button

STEP_COLOR = {Step.DONE: style.OK, Step.FAILED: style.PROBLEM, Step.PENDING: style.PENDING}


def step_bar(result: HostResult) -> QWidget:
    bar = QWidget()
    layout = QHBoxLayout(bar)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
    for step in result.steps:
        seg = QLabel()
        seg.setFixedSize(34, 6)
        seg.setStyleSheet(f"background: {STEP_COLOR[step]}; border-radius: 3px;")
        layout.addWidget(seg)
    return bar


def row_color(result: HostResult) -> str:
    if Step.FAILED not in result.steps:
        return style.OK
    # A failure before install means the host was never changed.
    return style.PROBLEM if result.steps.index(Step.FAILED) >= 2 else style.OFFLINE


class UpdatesPage(QWidget):
    undo_requested = Signal(str)

    def __init__(self, client: NixyncClient):
        super().__init__()
        update = client.current_update()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(20)
        layout.addWidget(page_header(update.title, update.started))

        stages = QHBoxLayout()
        test = Panel("Card")
        test.body.addWidget(QLabel(f"<b>1. Try on one machine</b><br>{update.test_host} worked"))
        rest = Panel("Card")
        rest.body.addWidget(QLabel("<b>2. Update the rest</b><br>" + ("Paused" if update.paused else "Running")))
        stages.addWidget(test)
        stages.addWidget(rest)
        layout.addLayout(stages)

        failed = [r for r in update.results if row_color(r) == style.PROBLEM]
        if update.paused and failed:
            host = failed[0].name
            paused = Panel()
            row = QHBoxLayout()
            row.addWidget(QLabel(f"<b>Update paused.</b> {host}: {failed[0].text}."), 1)
            undo = primary_button(f"Undo on {host}")
            undo.clicked.connect(lambda: self.undo_requested.emit(host))
            row.addWidget(undo)
            row.addWidget(QPushButton(f"Try {host} again"))
            row.addWidget(QPushButton("Continue anyway"))
            paused.body.addLayout(row)
            layout.addWidget(paused)

        hosts = Panel()
        header = QHBoxLayout()
        header.addWidget(QLabel("<b>Machines</b>"))
        header.addStretch()
        legend = QLabel("Each bar: prepare · connect · install · check")
        legend.setObjectName("Muted")
        header.addWidget(legend)
        hosts.body.addLayout(header)
        for result in update.results:
            row = QHBoxLayout()
            row.addWidget(dot(row_color(result)))
            name = QLabel(f"<b>{result.name}</b>")
            name.setFixedWidth(80)
            row.addWidget(name)
            row.addWidget(QLabel(result.text), 1)
            row.addWidget(step_bar(result))
            hosts.body.addLayout(row)

        for result in update.results:
            if not result.log:
                continue
            toggle = QPushButton(f"Show technical details for {result.name}")
            toggle.setCheckable(True)
            log = QPlainTextEdit(result.log)
            log.setObjectName("Log")
            log.setReadOnly(True)
            log.setVisible(False)
            log.setFixedHeight(110)
            toggle.toggled.connect(log.setVisible)
            hosts.body.addWidget(toggle)
            hosts.body.addWidget(log)
        layout.addWidget(hosts)
        layout.addStretch()
