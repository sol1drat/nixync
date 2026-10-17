from functools import lru_cache
from datetime import datetime, timezone

from PySide6.QtCore import QByteArray, QEvent, QObject, QPoint, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractButton, QComboBox, QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel, QLayout, QLayoutItem, QListWidget, QPushButton,
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
    # Server timestamps are timezone-aware ISO 8601; sample_data uses naive local times.
    now = datetime.now(timezone.utc if when.tzinfo is not None else None)
    seconds = int((now - when).total_seconds())
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


@lru_cache(maxsize=256)
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


_CLOSE_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24"
fill="none" stroke="{color}" stroke-width="2.4" stroke-linecap="round"><line x1="6" y1="6" x2="18" y2="18"/>
<line x1="18" y1="6" x2="6" y2="18"/></svg>"""


def close_icon(color: str) -> QIcon:
    return _svg_icon(_CLOSE_SVG, color)


_EYE_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24"
fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>"""

_EYE_OFF_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24"
fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/>
<path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/>
<path d="M14.12 14.12a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>"""


def eye_icon(color: str, open_: bool = True) -> QIcon:
    return _svg_icon(_EYE_SVG if open_ else _EYE_OFF_SVG, color)


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
    """A small colored circle. Theme colors are applied by the stylesheet (QLabel#Dot[tone=...]),
    so dots follow theme switches without any per-widget work."""
    from nixync_ui import style
    label = QLabel()
    label.setObjectName("Dot")
    label.setFixedSize(size, size)
    role = style.role_of(color)
    if role:
        label.setProperty("tone", role)
        label.setStyleSheet(f"border-radius: {size // 2}px;")
    else:
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


def strip_icons(widget) -> None:
    """Remove the themed icons Qt puts on standard dialog buttons.

    The native style decorates Cancel with a cross and OK with a tick. Nothing else
    in this app has an icon inside a button, so they look out of place — Cancel
    should just read "Cancel".
    """
    for button in widget.findChildren(QPushButton):
        if not button.icon().isNull():
            button.setIcon(QIcon())


def cancel_box(*, parent=None) -> QDialogButtonBox:
    """A button box whose Cancel is plain text; add accept buttons to the result."""
    box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel, parent)
    strip_icons(box)
    return box


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


def safe_emit(signal, *args):
    """Emit from a background job; if its window was closed meanwhile, drop the result."""
    try:
        signal.emit(*args)
    except RuntimeError:  # "Signal source has been deleted"
        pass


def usage_color(percent: float) -> str:
    """Green under 60%, amber from 60%, red from 80%: the same rule for bars and rings."""
    from nixync_ui import style
    if percent >= 80:
        return style.PROBLEM
    if percent >= 60:
        return style.WARNING
    return style.OK


class RingGauge(QWidget):
    """A circular usage meter: a ring filled to `percent`, the value in the middle, a label below."""

    def __init__(self, label: str, percent: float | None, detail: str = "", size: int = 92):
        super().__init__()
        self.label, self.percent, self.detail, self.ring = label, percent, detail, size
        self.setToolTip(detail or ("Not reporting" if percent is None else f"{label}: {percent:.1f}%"))

    def sizeHint(self) -> QSize:
        # Always leave room for the detail line so a row of gauges lines up.
        return QSize(max(self.ring, 110), self.ring + 8 + 2 * (self.fontMetrics().height() + 2))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def paintEvent(self, _event):
        from nixync_ui import style
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = 8
        x = (self.width() - self.ring) / 2
        box = QRectF(x + width / 2, width / 2, self.ring - width, self.ring - width)

        pen = QPen(QColor(style.PENDING), width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(box, 0, 360 * 16)
        if self.percent is not None:
            pen.setColor(QColor(usage_color(self.percent)))
            painter.setPen(pen)
            span = int(-360 * 16 * min(self.percent, 100) / 100)  # clockwise from 12 o'clock
            painter.drawArc(box, 90 * 16, span)

        value = "—" if self.percent is None else f"{self.percent:.0f}%"
        big = QFont(self.font())
        big.setPixelSize(20)
        big.setWeight(QFont.Weight.DemiBold)
        painter.setFont(big)
        painter.setPen(QColor(style.MUTED if self.percent is None else style.TEXT))
        painter.drawText(QRectF(x, 0, self.ring, self.ring), Qt.AlignmentFlag.AlignCenter, value)

        painter.setFont(self.font())
        line = self.fontMetrics().height() + 2
        top = self.ring + 8
        painter.setPen(QColor(style.TEXT))
        painter.drawText(QRectF(0, top, self.width(), line), Qt.AlignmentFlag.AlignHCenter, self.label)
        if self.detail:
            painter.setPen(QColor(style.MUTED))
            painter.drawText(QRectF(0, top + line, self.width(), line), Qt.AlignmentFlag.AlignHCenter, self.detail)


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
    """A status word shown in its status color, e.g. "Problem" in red. Follows theme switches."""
    from nixync_ui import style
    label = QLabel(text)
    label.setObjectName("StatusText")
    role = style.role_of(color)
    if role:
        label.setProperty("tone", role)  # colored by the stylesheet (QLabel#StatusText[tone=...])
    else:
        label.setStyleSheet(f"color: {color};")
    return label


def themed_icon(target, maker, role: str = "muted", owner=None):
    """Give a button or action an icon drawn in a theme color, redrawn on theme switches.
    `owner` is the widget whose lifetime the icon follows (defaults to `target`)."""
    from nixync_ui import style
    style.themed(owner or target, lambda: target.setIcon(maker(style.color(role))))


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


class ThemedDialogs(QObject):
    """App-wide event filter: dialogs pick up the current theme stylesheet as they open
    (there is no app-wide stylesheet; see style.styled)."""

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Polish and isinstance(obj, QDialog):
            from nixync_ui import style
            style.restyle_if_stale(obj)
        return False


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


class FlowLayout(QLayout):
    """Lays widgets out left to right and wraps onto new lines, like words in a paragraph."""

    def __init__(self, parent=None, spacing: int = 6):
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item: QLayoutItem):
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._arrange(QRect(0, 0, width, 0), move=False)

    def setGeometry(self, rect: QRect):
        super().setGeometry(rect)
        self._arrange(rect, move=True)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _arrange(self, rect: QRect, move: bool) -> int:
        x, y, line_height = rect.x(), rect.y(), 0
        for item in self._items:
            if item.widget() and item.widget().isHidden():  # removed tags, until deleted
                continue
            hint = item.sizeHint()
            if x + hint.width() > rect.right() + 1 and line_height:
                x, y = rect.x(), y + line_height + self._spacing
                line_height = 0
            if move:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._spacing
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y()
