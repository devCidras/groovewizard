"""GrooveWizard's desktop palette, widget styles and library sleeve illustration."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

C = {
    "bg": "#11131A",
    "card": "#1B1E28",
    "muted": "#292D3A",
    "switch_off": "#64748B",
    "border": "#373C4D",
    "fg": "#F8FAFC",
    "fg_muted": "#AFB6C8",
    "accent": "#81E7AE",
    "accent_hover": "#A5F3C6",
    "on_accent": "#0F172A",
    "secondary": "#4338CA",
    "secondary_hover": "#4F46E5",
    "danger": "#EF4444",
    "warn": "#F59E0B",
}

FONT = '"Inter", "Segoe UI Variable Text", "Segoe UI", sans-serif'

QSS = f"""
* {{ font-family: {FONT}; font-size: 14px; color: {C['fg']}; }}
QMainWindow, QWidget#root {{ background: {C['bg']}; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
QFrame#library {{ background: #222638; border: 1px solid #434861; border-radius: 14px; }}
QLabel#libraryTitle {{ font-size: 25px; font-weight: 700; }}
QFrame#library QLineEdit {{ background: #151822; }}
QLabel#armed {{ color: {C['warn']}; font-size: 12px; }}
QTabWidget::pane {{ border: none; border-top: 1px solid {C['border']}; }}
QTabBar {{ background: {C['bg']}; }}
QTabBar::tab {{ background: {C['bg']}; color: {C['fg_muted']}; padding: 9px 14px;
               border-bottom: 3px solid transparent; font-weight: 600; }}
QTabBar::tab:selected {{ color: {C['fg']}; border-bottom-color: {C['accent']}; }}
QTabBar::tab:hover {{ background: {C['muted']}; }}
QTabBar::tab:focus {{ color: {C['accent']}; }}
QMenu {{ background: {C['card']}; border: 1px solid {C['border']}; padding: 4px; }}
QMenu::item {{ padding: 7px 18px; }}
QMenu::item:selected {{ background: {C['muted']}; }}

QFrame#banner {{ background: {C['secondary']}; border-radius: 12px; }}
QFrame#banner QLabel {{ font-weight: 600; }}
QFrame#banner QPushButton#ghost {{ color: #E0E7FF; }}
QLabel#shutLabel {{ font-weight: 600; font-size: 13px; }}
QFrame#card {{ background: {C['card']}; border: 1px solid {C['border']}; border-radius: 12px; }}
QLabel#title {{ font-size: 22px; font-weight: 700; }}
QLabel#subtitle {{ color: {C['fg_muted']}; font-size: 14px; }}
QLabel#cardTitle {{ font-size: 18px; font-weight: 600; }}
QLabel#overviewValue {{ color: {C['accent']}; font-weight: 600; }}
QLabel#hint, QLabel#stepDesc {{ color: {C['fg_muted']}; font-size: 13px; }}
QLabel#badge {{ background: {C['muted']}; color: {C['fg_muted']}; border-radius: 9px; padding: 2px 10px; font-size: 12px; }}
QLabel#statValue {{ font-size: 22px; font-weight: 700; }}
QLabel#statLabel {{ color: {C['fg_muted']}; font-size: 12px; }}
QLabel a {{ color: {C['accent']}; }}

QLineEdit {{
    background: {C['muted']}; border: 1px solid {C['border']}; border-radius: 8px;
    padding: 9px 12px; selection-background-color: {C['secondary']};
}}
QLineEdit:focus {{ border: 1px solid {C['secondary_hover']}; }}

QComboBox {{
    background: {C['muted']}; border: 1px solid {C['border']}; border-radius: 8px; padding: 6px 10px; min-width: 110px;
}}
QComboBox:focus {{ border: 1px solid {C['secondary_hover']}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {C['card']}; border: 1px solid {C['border']}; selection-background-color: {C['secondary']}; }}
QCheckBox {{ spacing: 10px; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px; border: 1px solid {C['fg_muted']}; background: {C['muted']}; }}
QCheckBox::indicator:checked {{ background: {C['accent']}; border: 1px solid {C['accent']}; }}
QCheckBox:focus {{ color: {C['fg']}; }}

QPushButton {{
    background: {C['muted']}; border: 1px solid {C['border']}; border-radius: 8px;
    padding: 9px 18px; min-height: 22px; font-weight: 600;
}}
QPushButton:hover {{ background: #32324A; }}
QPushButton:focus {{ border: 1px solid {C['accent']}; }}
QPushButton:disabled {{ color: #5B6478; background: #1F1F36; }}
QPushButton#primary {{ background: {C['accent']}; color: {C['on_accent']}; border: none; padding: 11px 28px; font-size: 15px; }}
QPushButton#primary:hover {{ background: {C['accent_hover']}; }}
QPushButton#primary:focus, QPushButton#ghost:focus {{ border: 2px solid #AB9BF5; }}
QPushButton#review {{ background: #35304F; color: #DED7FF; }}
QPushButton#primary:disabled {{ background: #1E4D33; color: #6B8F7A; }}
QPushButton#danger {{ color: {C['danger']}; }}
QPushButton#ghost {{ background: transparent; border: none; color: {C['fg_muted']}; padding: 6px 8px; }}
QPushButton#ghost:hover {{ color: {C['fg']}; }}

QProgressBar {{ background: {C['muted']}; border: none; border-radius: 4px; max-height: 8px; min-height: 8px; }}
QProgressBar::chunk {{ background: {C['accent']}; border-radius: 4px; }}

QPlainTextEdit {{
    background: #151820; border: 1px solid {C['border']}; border-radius: 8px; padding: 8px;
    font-family: "Cascadia Mono", Consolas, monospace; font-size: 12px; color: {C['fg_muted']};
}}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {C['muted']}; border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
QToolTip {{ background: {C['muted']}; color: {C['fg']}; border: 1px solid {C['border']}; padding: 6px; }}
QMessageBox {{ background: {C['card']}; }}
QListWidget, QTableWidget {{
    background: #12122A; border: 1px solid {C['border']}; border-radius: 8px; gridline-color: {C['border']};
    selection-background-color: {C['secondary']}; outline: none;
}}
QListWidget::item {{ padding: 4px 6px; }}
QListWidget:focus, QTableWidget:focus {{ border: 1px solid {C['secondary_hover']}; }}
QHeaderView::section {{ background: {C['muted']}; color: {C['fg_muted']}; border: none; padding: 6px 8px; font-weight: 600; }}
QListWidget::indicator, QTableWidget::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid {C['fg_muted']}; background: {C['muted']}; }}
QListWidget::indicator:checked, QTableWidget::indicator:checked {{ background: {C['accent']}; border: 1px solid {C['accent']}; }}
"""


class RecordSleeve(QWidget):
    """Scalable artwork beside the library folder picker."""

    def __init__(self):
        super().__init__()
        self.setFixedSize(190, 142)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.translate(7, 9)
        p.rotate(-4)
        disc = QRectF(57, 11, 117, 117)
        p.setPen(QPen(QColor("#656A82"), 1))
        p.setBrush(QColor("#13151F"))
        p.drawEllipse(disc)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor("#383C50"), 1))
        for inset in range(4, 37, 4):
            p.drawEllipse(disc.adjusted(inset, inset, -inset, -inset))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(C["accent"]))
        p.drawEllipse(disc.center(), 19, 19)
        p.setBrush(QColor("#191B28"))
        p.drawEllipse(disc.center(), 3, 3)
        sleeve = QRectF(4, 8, 116, 116)
        p.fillRect(sleeve, QColor("#A697EF"))
        p.setClipRect(sleeve)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor("#403962"), 2))
        for diameter in range(28, 268, 8):
            p.drawEllipse(QRectF(11 - diameter / 2, 125 - diameter / 2, diameter, diameter))
        p.fillRect(QRectF(15, 19, 23, 6), QColor("#D5F9C9"))
        p.end()
