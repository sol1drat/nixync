from datetime import datetime

from PySide6.QtCore import QByteArray, QEvent, QObject, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractButton, QComboBox, QFrame, QHBoxLayout, QLabel, QLayout, QListWidget, QPushButton,
    QVBoxLayout, QWidget,
)

# Feather "settings" gear, drawn in the muted text color.
_GEAR_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24"
fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06
a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0
0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09
A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65
1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83
2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>"""


def ago(when: datetime) -> str:
    """Short relative time: "recently", "5m ago", "5h 2m ago", "2d 3h ago"."""
    seconds = int((datetime.now() - when).total_seconds())
    if seconds < 60:
        return "recently"
    minutes, hours, days = seconds // 60, seconds // 3600, seconds // 86400
    if hours < 1:
        return f"{minutes}m ago"
    if days < 1:
        rest = minutes % 60
        return f"{hours}h {rest}m ago" if rest else f"{hours}h ago"
    rest = hours % 24
    return f"{days}d {rest}h ago" if rest else f"{days}d ago"


def timestamp(when: datetime) -> str:
    return f"{when:%d %b %Y, %H:%M} ({ago(when)})"


_SEARCH_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24"
fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>"""


def _svg_icon(svg: str, color: str) -> QIcon:
    pixmap = QPixmap()
    pixmap.loadFromData(QByteArray(svg.format(color=color).encode()), "SVG")
    return QIcon(pixmap)


_DOWNLOAD_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24"
fill="none" stroke="{color}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/>
<line x1="12" y1="15" x2="12" y2="3"/></svg>"""


def download_icon(color: str) -> QIcon:
    return _svg_icon(_DOWNLOAD_SVG, color)


_PANEL_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24"
fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<rect x="3" y="3" width="18" height="18" rx="2"/><line x1="9" y1="3" x2="9" y2="21"/></svg>"""


def panel_icon(color: str) -> QIcon:
    return _svg_icon(_PANEL_SVG, color)


_MOON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24"
fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>"""

_SUN_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24"
fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2
M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/></svg>"""


def moon_icon(color: str) -> QIcon:
    return _svg_icon(_MOON_SVG, color)


def sun_icon(color: str) -> QIcon:
    return _svg_icon(_SUN_SVG, color)


def dot_icon(color: str, size: int = 16) -> QIcon:
    """A filled circle, for small status markers inside buttons."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawEllipse(0, 0, size, size)
    painter.end()
    return QIcon(pixmap)


def search_icon(color: str) -> QIcon:
    return _svg_icon(_SEARCH_SVG, color)


def gear_icon(color: str) -> QIcon:
    return _svg_icon(_GEAR_SVG, color)


def clear_layout(layout: QLayout):
    """Remove and delete everything in a layout, including nested layouts."""
    while (child := layout.takeAt(0)) is not None:
        if widget := child.widget():
            widget.hide()
            widget.deleteLater()
        elif inner := child.layout():
            clear_layout(inner)
            inner.deleteLater()


def dot(color: str, size: int = 10) -> QLabel:
    label = QLabel()
    label.setFixedSize(size, size)
    label.setStyleSheet(f"background: {color}; border-radius: {size // 2}px;")
    return label


class SegmentButton(QPushButton):
    """A checkable filter tab. It turns bold when checked, so size it for bold text."""

    def __init__(self, text: str = ""):
        super().__init__(text)
        self.setProperty("segment", True)
        self.setCheckable(True)

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        bold = QFont(self.font())
        bold.setWeight(QFont.Weight.DemiBold)
        extra = QFontMetrics(bold).horizontalAdvance(self.text()) - self.fontMetrics().horizontalAdvance(self.text())
        return QSize(hint.width() + max(extra, 0) + 2, hint.height())

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()


def primary_button(text: str) -> QPushButton:
    button = QPushButton(text)
    button.setProperty("primary", True)
    return button


def page_header(title: str, subtitle: str = "") -> QWidget:
    header = QWidget()
    layout = QVBoxLayout(header)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
    label = QLabel(title)
    label.setObjectName("PageTitle")
    layout.addWidget(label)
    if subtitle:
        sub = QLabel(subtitle)
        sub.setObjectName("Muted")
        layout.addWidget(sub)
    return header


CELL_PAD = 8  # left/right padding in each cell; matches the header's padding in style.py


def centered(widget: QWidget, align=Qt.AlignmentFlag.AlignLeft) -> QWidget:
    """Wrap a widget so it sits vertically centered (and aligned) inside a table cell."""
    box = QWidget()
    layout = QHBoxLayout(box)
    layout.setContentsMargins(CELL_PAD, 0, CELL_PAD, 0)
    layout.addWidget(widget, 0, align | Qt.AlignmentFlag.AlignVCenter)
    if align == Qt.AlignmentFlag.AlignLeft:
        layout.addStretch()
    return box


def status_text(color: str, text: str) -> QLabel:
    """A status word shown in its status color, e.g. "Problem" in red."""
    label = QLabel(text)
    label.setStyleSheet(f"color: {color}; font-weight: 600;")
    return label


def status_row(color: str, text: str) -> QWidget:
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    layout.addWidget(dot(color))
    label = QLabel(text)
    label.setWordWrap(True)
    layout.addWidget(label, 1)
    return row


class Panel(QFrame):
    def __init__(self, object_name: str = "Panel", parent=None):
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(16, 14, 16, 14)
        self.body.setSpacing(10)


# Lists whose rows act when clicked (sidebar, preset list, app search results).
_CLICKABLE_LISTS = (QListWidget,)


class PointerCursors(QObject):
    """App-wide event filter: a pointing hand over anything clickable, the arrow when it's disabled.

    Install once with app.installEventFilter(PointerCursors(app)).
    """

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Type.Polish, QEvent.Type.EnabledChange):
            if isinstance(obj, (QAbstractButton, QComboBox)):
                if obj.isEnabled():
                    obj.setCursor(Qt.CursorShape.PointingHandCursor)
                else:
                    obj.unsetCursor()
            elif isinstance(obj, _CLICKABLE_LISTS):
                obj.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        return False
