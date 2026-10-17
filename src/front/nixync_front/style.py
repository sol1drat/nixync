ACCENT = "#1D5FD1"
OK = "#1A7F37"
PROBLEM = "#CF222E"
OFFLINE = "#8C959F"
PENDING = "#D4D7DD"
MUTED = "#57606A"

STYLESHEET = f"""
QMainWindow, QDialog {{ background: #F3F4F6; color: #1F2328; }}
QWidget {{ font-size: 14px; }}
QListWidget#Sidebar {{
    background: #E9EBEE; border: none; border-right: 1px solid #D4D7DD;
    padding: 16px 10px; font-size: 15px;
}}
QListWidget#Sidebar::item {{ min-height: 42px; padding: 0 10px; border-radius: 6px; }}
QListWidget#Sidebar::item:hover {{ background: #E4E7EB; }}
QListWidget#Sidebar::item:selected {{
    background: #FFFFFF; color: #1F2328; font-weight: 600; border: 1px solid #D4D7DD;
}}
QListWidget#RoleList {{ background: transparent; border: none; }}
QListWidget#RoleList::item {{ padding: 10px 12px; margin-bottom: 4px; border-radius: 8px; color: #1F2328; }}
QListWidget#RoleList::item:hover {{ background: #FFFFFF; }}
QListWidget#RoleList::item:selected {{ background: #FFFFFF; border: 1px solid #D4D7DD; }}
QLabel#PageTitle {{ font-size: 24px; font-weight: 600; }}
QLabel#Muted {{ color: {MUTED}; }}
QPushButton {{
    min-height: 36px; padding: 0 16px; border: 1px solid #C3C8D0;
    border-radius: 6px; background: #FFFFFF;
}}
QPushButton:hover {{ background: #F6F7F9; }}
QPushButton[primary="true"] {{
    background: {ACCENT}; color: #FFFFFF; border-color: {ACCENT}; font-weight: 500;
}}
QPushButton[primary="true"]:disabled {{ background: #9DB7E6; border-color: #9DB7E6; }}
QPushButton[segment="true"] {{ border: none; background: transparent; min-height: 32px; }}
QPushButton[segment="true"]:checked {{ background: #FFFFFF; font-weight: 600; border: 1px solid #D4D7DD; }}
QFrame#Card, QFrame#Panel {{ background: #FFFFFF; border: 1px solid #D4D7DD; border-radius: 8px; }}
QFrame#Attention {{ background: #FFF8E6; border: 1px solid #EBD08A; border-radius: 8px; }}
QLineEdit, QComboBox {{
    min-height: 36px; padding: 0 10px; border: 1px solid #C3C8D0;
    border-radius: 6px; background: #FFFFFF;
}}
QPlainTextEdit#Log {{
    background: #16191D; color: #D7DCE2; border-radius: 6px;
    font-family: monospace; font-size: 12px;
}}
QStatusBar {{ background: #E9EBEE; border-top: 1px solid #D4D7DD; color: #3D444D; }}
"""
