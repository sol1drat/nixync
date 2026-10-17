from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from nixync_front import style
from nixync_front.api import NixyncClient
from nixync_front.sample_data import AppRequest, RequestStatus
from nixync_front.widgets import Panel, SegmentButton, ago, clear_layout, page_header, primary_button, status_text

def status_color(status: RequestStatus) -> str:
    return {RequestStatus.PENDING: style.PENDING, RequestStatus.APPROVED: style.OK,
            RequestStatus.DECLINED: style.OFFLINE}[status]


class RequestsPage(QWidget):
    """App install requests sent by people using the managed machines."""

    changed = Signal()
    machine_requested = Signal(str)
    message = Signal(str)

    def __init__(self, client: NixyncClient):
        super().__init__()
        self.client = client
        self.machine_filter: str | None = None
        self.show_pending = True

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(20)
        outer.addWidget(page_header("Requests", "Apps people have asked to have installed on their device."))

        filters = QHBoxLayout()
        self.segments = QButtonGroup(self)
        self.pending_button = self._segment(True)
        self.handled_button = self._segment(False)
        filters.addWidget(self.pending_button)
        filters.addWidget(self.handled_button)
        filters.addSpacing(12)
        self.filter_label = QLabel()
        self.filter_label.setObjectName("Muted")
        filters.addWidget(self.filter_label)
        self.filter_clear = QPushButton("Show all")
        self.filter_clear.setProperty("link", True)
        self.filter_clear.setToolTip("Show requests from every device")
        self.filter_clear.clicked.connect(lambda: self.filter_machine(None))
        filters.addWidget(self.filter_clear)
        filters.addStretch()
        outer.addLayout(filters)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        self.list = QVBoxLayout(content)
        self.list.setContentsMargins(0, 0, 0, 0)
        self.list.setSpacing(10)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        self.refresh()

    def _segment(self, pending: bool) -> QPushButton:
        button = SegmentButton()
        button.setChecked(pending)
        button.clicked.connect(lambda: self._set_pending(pending))
        self.segments.addButton(button)
        return button

    def _set_pending(self, pending: bool):
        self.show_pending = pending
        self.refresh()

    def filter_machine(self, machine: str | None):
        self.machine_filter = machine
        self.show_pending = True
        self.pending_button.setChecked(True)
        self.refresh()

    def refresh(self):
        everything = [r for r in self.client.list_requests() if self.machine_filter in (None, r.machine)]
        pending = [r for r in everything if r.status is RequestStatus.PENDING]
        handled = [r for r in everything if r.status is not RequestStatus.PENDING]
        self.pending_button.setText(f"Pending ({len(pending)})")
        self.handled_button.setText(f"Handled ({len(handled)})")
        self.filter_label.setText(f"Only {self.machine_filter} ·")
        self.filter_label.setVisible(self.machine_filter is not None)
        self.filter_clear.setVisible(self.machine_filter is not None)

        clear_layout(self.list)
        shown = pending if self.show_pending else handled
        for request in shown:
            self.list.addWidget(self._card(request))
        if not shown:
            where = f" from {self.machine_filter}" if self.machine_filter else ""
            empty = QLabel(f"No pending requests{where}. You're all caught up."
                           if self.show_pending else f"No handled requests{where} yet.")
            empty.setObjectName("Muted")
            self.list.addWidget(empty)
        self.list.addStretch()

    def _card(self, request: AppRequest) -> Panel:
        card = Panel("Card")
        row = QHBoxLayout()
        row.setSpacing(16)

        text = QVBoxLayout()
        text.setSpacing(4)
        description = self.client.describe_app(request.app)
        title = QLabel(f"<b>{request.app}</b>" + (f"  <span style='color:{style.MUTED}'>{description}</span>"
                                                   if description else ""))
        title.setStyleSheet("font-size: 15px; border: none;")
        text.addWidget(title)
        meta = QLabel(f"Requested by <b>{request.requested_by}</b> on "
                      f"<a href='#'>{request.machine}</a> · {ago(request.when)}")
        meta.setStyleSheet("border: none;")
        meta.linkActivated.connect(lambda _: self.machine_requested.emit(request.machine))
        text.addWidget(meta)
        if request.reason:
            reason = QLabel(f"“{request.reason}”")
            reason.setObjectName("Muted")
            reason.setWordWrap(True)
            reason.setStyleSheet("border: none; font-style: italic;")
            text.addWidget(reason)
        row.addLayout(text, 1)

        if request.status is RequestStatus.PENDING:
            decline = QPushButton("Decline")
            decline.clicked.connect(lambda: self._decide(request, approve=False))
            approve = primary_button("Approve and install")
            approve.clicked.connect(lambda: self._decide(request, approve=True))
            row.addWidget(decline, 0, Qt.AlignmentFlag.AlignVCenter)
            row.addWidget(approve, 0, Qt.AlignmentFlag.AlignVCenter)
        else:
            row.addWidget(status_text(status_color(request.status), request.status.value), 0,
                          Qt.AlignmentFlag.AlignVCenter)

        card.body.addLayout(row)
        return card

    def _decide(self, request: AppRequest, approve: bool):
        if approve:
            self.client.approve_request(request.id)
            self.message.emit(f"Approved {request.app} for {request.machine}. It will be installed on the next update.")
        else:
            self.client.decline_request(request.id)
            self.message.emit(f"Declined {request.app} for {request.machine}.")
        self.refresh()
        self.changed.emit()
