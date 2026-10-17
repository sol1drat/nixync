"""Colors and the Qt stylesheet, for a light and a dark theme.

Call apply(app, "dark" | "light") to switch. Modules read colors through this module
(style.OK, style.MUTED, ...) at the time they draw, so build widgets after apply().
"""

from pathlib import Path

import shiboken6
from PySide6.QtGui import QColor, QPalette

ICONS = Path(__file__).resolve().parent / "icons"

LIGHT = {
    "bg": "#F3F4F6", "surface": "#FFFFFF", "surface_alt": "#F7F8FA", "hover": "#F3F4F6",
    "sidebar": "#FFFFFF", "sidebar_border": "#E1E4E8", "border": "#D4D7DD", "border_strong": "#C3C8D0",
    "row_line": "#ECEEF1", "text": "#1F2328", "text_soft": "#3D444D", "muted": "#57606A",
    "accent": "#1D5FD1", "on_accent": "#FFFFFF", "accent_disabled": "#9DB7E6", "on_accent_disabled": "#FFFFFF",
    "accent_soft": "#EAF1FD", "accent_soft_border": "#C4D7F7",
    "ok": "#1A7F37", "problem": "#CF222E", "warning": "#D4A72C", "offline": "#8C959F", "track": "#D4D7DD",
    "log": ("#16191D", "#D7DCE2"),
    "statusbar": "#E9EBEE",
}

DARK = {
    "bg": "#0F1115", "surface": "#171A21", "surface_alt": "#1B1F27", "hover": "#1F232C",
    "sidebar": "#13161C", "sidebar_border": "#232833", "border": "#2A2F3A", "border_strong": "#3A404C",
    "row_line": "#222731", "text": "#E6E8EB", "text_soft": "#C3C8D0", "muted": "#8B93A1",
    "accent": "#4C8DFF", "on_accent": "#FFFFFF", "accent_disabled": "#1F2A3D", "on_accent_disabled": "#6E7D96",
    "accent_soft": "#18243A", "accent_soft_border": "#2C4572",
    "ok": "#3FB950", "problem": "#F85149", "warning": "#D29922", "offline": "#6E7681", "track": "#2D333D",
    "log": ("#0B0D10", "#D7DCE2"),
    "statusbar": "#13161C",
}

THEMES = {"light": LIGHT, "dark": DARK}

# Current theme; filled in by apply(). Defaults to light so imports work before apply().
THEME = "light"
IS_DARK = False
ACCENT = OK = PROBLEM = WARNING = OFFLINE = PENDING = MUTED = TEXT = ""
STYLESHEET = ""


# Widgets that bake a theme color in (icons, colored text) register a callback here;
# apply() re-runs them so a theme switch updates everything in place, without a rebuild.
_listeners: list[tuple[object, object]] = []
_STATUS_ROLES = ("ok", "problem", "warning", "offline", "muted", "text", "accent", "track")
_fusion_set = False


def themed(widget, update) -> None:
    """Run `update()` now and again after every theme switch, for as long as `widget` exists."""
    update()
    _listeners.append((widget, update))
    if len(_listeners) % 200 == 0:  # tables rebuild often; drop entries for deleted widgets
        _listeners[:] = [(w, u) for w, u in _listeners if shiboken6.isValid(w)]


def _notify() -> None:
    alive = []
    for widget, update in _listeners:
        if shiboken6.isValid(widget):
            update()
            alive.append((widget, update))
    _listeners[:] = alive


def styled(widget, lazy: bool = False) -> None:
    """Give `widget` (and its children) the theme stylesheet, and keep it current.

    There is deliberately no app-wide stylesheet: changing one re-polishes every widget in the
    app (~300 ms here). Instead each part of the window carries the sheet itself. With
    `lazy=True` a hidden widget is restyled when it is next shown (see restyle_if_stale).
    """
    def update():
        if lazy and not widget.isVisible() and widget.property("sheet_theme"):
            return  # restyled on show instead
        widget.setStyleSheet(STYLESHEET)
        widget.setProperty("sheet_theme", THEME)
    themed(widget, update)


def restyle_if_stale(widget) -> None:
    if widget.property("sheet_theme") != THEME:
        widget.setStyleSheet(STYLESHEET)
        widget.setProperty("sheet_theme", THEME)


def role_of(value: str) -> str | None:
    """Which palette entry a color came from (e.g. style.PROBLEM -> "problem"), so it can follow the theme."""
    current = THEMES[THEME]
    return next((key for key in _STATUS_ROLES if current[key] == value), None)


def color(key: str) -> str:
    """Any palette color of the current theme, e.g. color("border")."""
    return THEMES[THEME][key]


def logo_path() -> Path:
    return ICONS / ("logo-white.png" if IS_DARK else "logo.png")


def _chevron(color: str) -> str:
    """Write (once) a down-chevron SVG in the given color and return its path for the stylesheet."""
    path = ICONS / f"chevron-down-{color.lstrip('#').lower()}.svg"
    if not path.exists():
        path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" '
            f'stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
            '<polyline points="6 9 12 15 18 9"/></svg>')
    return path.as_posix()


def _check(color: str) -> str:
    """Write (once) a tick-mark SVG in the given color and return its path for the stylesheet."""
    path = ICONS / f"check-{color.lstrip('#').lower()}.svg"
    if not path.exists():
        path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" '
            f'stroke="{color}" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round">'
            '<polyline points="20 6 9 17 4 12"/></svg>')
    return path.as_posix()


def _dash(color: str) -> str:
    """Write (once) a dash SVG, for the "some selected" state of the select-all checkbox."""
    path = ICONS / f"dash-{color.lstrip('#').lower()}.svg"
    if not path.exists():
        path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" '
            f'stroke="{color}" stroke-width="3.2" stroke-linecap="round"><line x1="6" y1="12" x2="18" y2="12"/></svg>')
    return path.as_posix()


def build_stylesheet(c: dict) -> str:
    log_bg, log_fg = c["log"]
    return f"""
QMainWindow, QDialog {{ background: {c["bg"]}; color: {c["text"]}; }}
QWidget {{ font-size: 14px; color: {c["text"]}; }}
QToolTip {{ background: {c["surface"]}; color: {c["text"]}; border: 1px solid {c["border"]}; padding: 4px 6px; }}
QWidget#LoginWindow {{ background: {c["bg"]}; }}
QFrame#LoginCard {{ background: {c["surface"]}; border: 1px solid {c["border"]}; border-radius: 12px; }}
QFrame#LoginCard QLabel {{ background: transparent; border: none; }}
QWidget#SidebarColumn {{ background: {c["sidebar"]}; border-right: 1px solid {c["sidebar_border"]}; }}
QToolButton#SidebarToggle {{
    border: none; background: transparent; border-radius: 6px; min-width: 32px; min-height: 32px;
}}
QToolButton#SidebarToggle:hover {{ background: {c["hover"]}; }}
QPushButton#ThemeToggle {{
    border: none; background: transparent; text-align: left; padding: 0 12px; min-height: 38px;
    border-radius: 6px; color: {c["text_soft"]};
}}
QPushButton#ThemeToggle:hover {{ background: {c["hover"]}; }}
QLabel#BrandName {{ font-size: 19px; font-weight: 700; color: {c["text"]}; }}
QListWidget#Sidebar {{
    background: transparent; border: none; padding: 8px 10px 16px 10px; font-size: 15px;
}}
QListWidget#Sidebar::item {{ min-height: 42px; padding: 0 10px; border-radius: 6px; color: {c["text"]}; }}
QListWidget#Sidebar::item:hover {{ background: {c["hover"]}; }}
QListWidget#Sidebar::item:selected {{ background: {c["accent_soft"]}; color: {c["accent"]}; font-weight: 600; }}
QListWidget#PresetList {{ background: transparent; border: none; }}
QListWidget#PresetList::item {{ padding: 10px 12px; margin-bottom: 4px; border-radius: 8px; color: {c["text"]}; }}
QListWidget#PresetList::item:hover {{ background: {c["surface"]}; }}
QListWidget#PresetList::item:selected {{ background: {c["surface"]}; border: 1px solid {c["border"]}; }}
QListWidget {{ background: {c["surface"]}; border: 1px solid {c["border"]}; color: {c["text"]}; }}
QListWidget::item:hover {{ background: {c["hover"]}; }}
QLabel#PageTitle {{ font-size: 24px; font-weight: 600; }}
QLabel#Muted {{ color: {c["muted"]}; }}
QPushButton {{
    min-height: 36px; padding: 0 16px; border: 1px solid {c["border_strong"]};
    border-radius: 6px; background: {c["surface"]}; color: {c["text"]};
}}
QPushButton:hover {{ background: {c["hover"]}; }}
QPushButton:disabled {{ color: {c["muted"]}; }}
QPushButton[primary="true"] {{
    background: {c["accent"]}; color: {c["on_accent"]}; border-color: {c["accent"]}; font-weight: 500;
}}
QPushButton[primary="true"]:disabled {{
    background: {c["accent_disabled"]}; border-color: {c["accent_disabled"]}; color: {c["on_accent_disabled"]};
}}
QPushButton[link="true"] {{ border: none; background: transparent; color: {c["accent"]}; padding: 0; min-height: 24px; }}
QPushButton[link="true"]:hover {{ text-decoration: underline; }}
QPushButton[link="true"]:disabled {{ color: {c["muted"]}; text-decoration: none; }}
QToolButton#SettingsButton {{
    border: none; background: transparent; border-radius: 6px; min-width: 30px; min-height: 30px;
}}
QToolButton#SettingsButton:hover {{ background: {c["hover"]}; }}
QPushButton[segment="true"] {{ border: none; background: transparent; min-height: 32px; }}
QPushButton[segment="true"]:checked {{ background: {c["surface"]}; font-weight: 600; border: 1px solid {c["border"]}; }}
QFrame#Card, QFrame#Panel {{ background: {c["surface"]}; border: 1px solid {c["border"]}; border-radius: 8px; }}
QPushButton#AttentionCount {{
    border: none; background: transparent; padding: 0 2px; min-height: 24px;
    color: {c["problem"]}; font-size: 13px; font-weight: 600; text-align: left;
}}
QPushButton#AttentionCount:hover {{ text-decoration: underline; }}
QLineEdit, QComboBox {{
    min-height: 36px; padding: 0 10px; border: 1px solid {c["border_strong"]};
    border-radius: 6px; background: {c["surface"]}; color: {c["text"]};
}}
QLineEdit:focus, QComboBox:focus {{ border-color: {c["accent"]}; }}
QComboBox QAbstractItemView {{
    background: {c["surface"]}; color: {c["text"]}; border: 1px solid {c["border"]};
    selection-background-color: {c["accent_soft"]}; selection-color: {c["text"]}; outline: none;
}}
QPlainTextEdit {{ background: {c["surface"]}; color: {c["text"]}; border: 1px solid {c["border"]}; border-radius: 6px; }}
QTextBrowser#AIAnswer {{
    background: {c["surface"]}; color: {c["text"]}; border: 1px solid {c["border"]};
    border-radius: 8px; padding: 10px 14px; font-size: 14px;
}}
QPlainTextEdit#Log {{
    background: {log_bg}; color: {log_fg}; border-radius: 6px; font-family: monospace; font-size: 12px;
}}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QTableWidget#DeviceTable {{
    background: {c["surface"]}; border: 1px solid {c["border"]}; border-radius: 8px;
}}
QTableWidget#DeviceTable::item {{ border-bottom: 1px solid {c["row_line"]}; }}
QTableWidget#DeviceTable QHeaderView {{ background: {c["surface_alt"]}; }}
QTableWidget#DeviceTable QHeaderView::section {{
    background: {c["surface_alt"]}; color: {c["muted"]}; border: none; border-bottom: 1px solid {c["border"]};
    padding: 0 8px; height: 38px; font-size: 12px; font-weight: 600;
}}
QTableWidget#DeviceTable QTableCornerButton::section {{ background: {c["surface_alt"]}; border: none; }}
QComboBox {{ padding: 0 10px; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{ image: url("{_chevron(c["muted"])}"); width: 14px; height: 14px; }}
QFrame#AppTag {{
    background: {c["surface_alt"]}; border: 1px solid {c["border"]}; border-radius: 6px;
}}
QFrame#AppTag[pending="true"] {{ background: {c["accent_soft"]}; border-color: {c["accent_soft_border"]}; }}
QFrame#AppTag QLabel#AppTagName {{ font-size: 13px; background: transparent; border: none; }}
QFrame#AppTag[pending="true"] QLabel#AppTagName {{ color: {c["accent"]}; }}
QLabel#AppTagStatic {{
    font-size: 13px; color: {c["text_soft"]}; padding: 3px 9px;
    border: 1px solid {c["border"]}; border-radius: 6px;
}}
QToolButton#TagRemove {{
    border: none; background: transparent; border-radius: 4px; min-width: 18px; min-height: 18px; padding: 0;
}}
QToolButton#TagRemove:hover {{ background: {c["hover"]}; }}
QListWidget#SearchResults {{ border: 1px solid {c["border"]}; border-radius: 8px; padding: 0; outline: none; }}
QListWidget#SearchResults::item {{ border-bottom: 1px solid {c["row_line"]}; }}
QListWidget#SearchResults::item:hover {{ background: {c["hover"]}; }}
QListWidget#SearchResults::item:selected {{ background: {c["accent_soft"]}; }}
QPushButton#SmallButton {{ min-height: 28px; max-height: 28px; padding: 0 12px; font-size: 13px; }}
QLabel#StatusText[tone="ok"] {{ color: {c["ok"]}; font-weight: 600; }}
QLabel#Dot[tone="ok"] {{ background: {c["ok"]}; }}
QLabel#StatusText[tone="problem"] {{ color: {c["problem"]}; font-weight: 600; }}
QLabel#Dot[tone="problem"] {{ background: {c["problem"]}; }}
QLabel#StatusText[tone="warning"] {{ color: {c["warning"]}; font-weight: 600; }}
QLabel#Dot[tone="warning"] {{ background: {c["warning"]}; }}
QLabel#StatusText[tone="offline"] {{ color: {c["offline"]}; font-weight: 600; }}
QLabel#Dot[tone="offline"] {{ background: {c["offline"]}; }}
QLabel#StatusText[tone="muted"] {{ color: {c["muted"]}; font-weight: 600; }}
QLabel#Dot[tone="muted"] {{ background: {c["muted"]}; }}
QLabel#StatusText[tone="text"] {{ color: {c["text"]}; font-weight: 600; }}
QLabel#Dot[tone="text"] {{ background: {c["text"]}; }}
QLabel#StatusText[tone="accent"] {{ color: {c["accent"]}; font-weight: 600; }}
QLabel#Dot[tone="accent"] {{ background: {c["accent"]}; }}
QLabel#StatusText[tone="track"] {{ color: {c["track"]}; font-weight: 600; }}
QLabel#Dot[tone="track"] {{ background: {c["track"]}; }}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px; border-radius: 4px;
    border: 1.5px solid {c["border_strong"]}; background: {c["surface"]};
}}
QCheckBox::indicator:hover {{ border-color: {c["accent"]}; }}
QCheckBox::indicator:checked {{
    background: {c["accent"]}; border-color: {c["accent"]}; image: url("{_check(c["on_accent"])}");
}}
QCheckBox::indicator:indeterminate {{
    background: {c["accent"]}; border-color: {c["accent"]}; image: url("{_dash(c["on_accent"])}");
}}
QStatusBar {{ background: {c["statusbar"]}; border-top: 1px solid {c["border"]}; color: {c["text_soft"]}; }}
QStatusBar QLabel {{ color: {c["text_soft"]}; }}
"""


def build_palette(c: dict) -> QPalette:
    """Base colors for things the stylesheet doesn't reach: checkboxes, scrollbars, popups."""
    p = QPalette()
    role = QPalette.ColorRole
    for r, key in ((role.Window, "bg"), (role.Base, "surface"), (role.AlternateBase, "surface_alt"),
                   (role.Button, "surface"), (role.ToolTipBase, "surface"), (role.Mid, "border"),
                   (role.Dark, "border_strong"), (role.Midlight, "hover"), (role.Light, "surface_alt")):
        p.setColor(r, QColor(c[key]))
    for r in (role.WindowText, role.Text, role.ButtonText, role.ToolTipText, role.BrightText):
        p.setColor(r, QColor(c["text"]))
    p.setColor(role.PlaceholderText, QColor(c["muted"]))
    p.setColor(role.Highlight, QColor(c["accent"]))
    p.setColor(role.HighlightedText, QColor(c["on_accent"]))
    p.setColor(role.Link, QColor(c["accent"]))
    for r in (role.WindowText, role.Text, role.ButtonText):
        p.setColor(QPalette.ColorGroup.Disabled, r, QColor(c["muted"]))
    return p


def apply(app, theme: str) -> None:
    """Switch the whole app to `theme` ("light" or "dark")."""
    global THEME, IS_DARK, ACCENT, OK, PROBLEM, WARNING, OFFLINE, PENDING, MUTED, TEXT, STYLESHEET, _fusion_set
    THEME = theme if theme in THEMES else "dark"
    IS_DARK = THEME == "dark"
    c = THEMES[THEME]
    ACCENT, OK, PROBLEM, WARNING = c["accent"], c["ok"], c["problem"], c["warning"]
    OFFLINE, PENDING, MUTED, TEXT = c["offline"], c["track"], c["muted"], c["text"]
    STYLESHEET = build_stylesheet(c)
    if app is not None:
        if not _fusion_set:  # re-setting the style re-polishes every widget; once is enough
            app.setStyle("Fusion")  # follows the palette consistently on every desktop
            _fusion_set = True
        app.setPalette(build_palette(c))  # tooltips and unstyled controls follow the palette
        _notify()


apply(None, "light")
