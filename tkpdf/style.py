"""Stile grafico TK (navy + accento rosso PDF)."""
import os

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPolygonF

NAVY = "#0f172a"
NAVY_2 = "#1e293b"
NAVY_3 = "#334155"
ACCENT = "#e11d48"
ACCENT_D = "#be123c"
ACCENT_L = "#ffe4e6"
GRAY_50 = "#f8fafc"
GRAY_100 = "#f1f5f9"
GRAY_200 = "#e2e8f0"
GRAY_300 = "#cbd5e1"
GRAY_500 = "#64748b"


def _arrow(name, color, up=False):
    """Freccia PNG per combo/spinbox (Qt non disegna i triangoli fatti con i bordi CSS)."""
    from tkpdf.util import app_data_dir
    folder = os.path.join(app_data_dir(), "ui")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{name}.png")
    img = QImage(20, 12, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    pts = [QPointF(2, 10), QPointF(18, 10), QPointF(10, 2)] if up else [QPointF(2, 2), QPointF(18, 2), QPointF(10, 10)]
    p.drawPolygon(QPolygonF(pts))
    p.end()
    img.save(path, "PNG")
    return path.replace(os.sep, "/")


ARROW_LIGHT = _arrow("freccia-giu-chiara", GRAY_300)
ARROW_WHITE = _arrow("freccia-giu-bianca", "#ffffff")
ARROW_DARK = _arrow("freccia-giu-scura", GRAY_500)
ARROW_UP_DARK = _arrow("freccia-su-scura", GRAY_500, up=True)

QSS = f"""
QMainWindow, QDialog {{ background: {GRAY_50}; }}
QWidget {{ font-family: 'Segoe UI', '.AppleSystemUIFont', 'Helvetica Neue', 'Segoe UI Emoji'; font-size: 10pt; color: {NAVY}; }}

/* Barra superiore */
#tkHeader {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {NAVY}, stop:0.6 {NAVY_2}, stop:1 {NAVY_3});
}}
#tkHeader QLabel {{ color: white; }}
#tkHeaderTitle {{ font-size: 13pt; font-weight: 700; }}
#tkHeaderFile {{ color: {GRAY_300}; font-size: 9.5pt; }}
#tkHeader QToolButton {{
    color: white; background: transparent; border: 0; border-radius: 6px; padding: 6px 10px; font-weight: 600;
}}
#tkHeader QToolButton:hover {{ background: rgba(255,255,255,0.12); }}
#tkHeader QToolButton:pressed {{ background: rgba(255,255,255,0.2); }}
#tkHeader QToolButton:disabled {{ color: {GRAY_500}; }}
#tkHeader QLineEdit, #tkHeader QComboBox {{
    background: {NAVY_2}; color: white; border: 1px solid {NAVY_3}; border-radius: 6px; padding: 4px 8px;
    selection-background-color: {ACCENT}; selection-color: white;
}}
#tkHeader QComboBox {{ padding-right: 22px; }}
#tkHeader QLineEdit:hover, #tkHeader QComboBox:hover {{ border: 1px solid {GRAY_500}; }}
#tkHeader QLineEdit:focus, #tkHeader QComboBox:focus {{ border: 1px solid {ACCENT}; }}
#tkHeader QComboBox QLineEdit {{ background: transparent; border: 0; padding: 0; color: white; }}
#tkHeader QComboBox::drop-down {{
    subcontrol-origin: padding; subcontrol-position: center right; width: 24px; border: 0; background: transparent;
}}
#tkHeader QComboBox::down-arrow {{ image: url("{ARROW_LIGHT}"); width: 10px; height: 6px; }}
#tkHeader QComboBox::down-arrow:hover, #tkHeader QComboBox::down-arrow:on {{ image: url("{ARROW_WHITE}"); }}
#tkHeader QComboBox QAbstractItemView {{
    background: white; color: {NAVY}; border: 1px solid {GRAY_200}; border-radius: 6px; padding: 4px; outline: 0;
    selection-background-color: {ACCENT_L}; selection-color: {ACCENT_D};
}}

/* Tab funzioni */
#tkTabs {{ background: white; border-bottom: 1px solid {GRAY_200}; }}
#tkTabs QPushButton {{
    background: transparent; border: 0; border-radius: 8px;
    padding: 7px 16px; margin: 6px 0; font-weight: 600; color: {GRAY_500};
}}
#tkTabs QPushButton:hover {{ background: {GRAY_100}; color: {NAVY}; }}
#tkTabs QPushButton:checked {{ background: {NAVY}; color: white; }}

/* Strumenti del tab */
#tkTools {{ background: white; border-bottom: 1px solid {GRAY_200}; }}
#tkTools QToolButton {{
    background: {GRAY_100}; border: 1px solid transparent; border-radius: 6px; padding: 5px 10px; font-weight: 600;
}}
#tkTools QToolButton:hover {{ background: {GRAY_200}; }}
#tkTools QToolButton:checked {{ background: {ACCENT_L}; border: 1px solid {ACCENT}; color: {ACCENT_D}; }}
#tkTools QToolButton::menu-indicator {{ subcontrol-position: right center; right: 4px; }}
#tkTools QLabel {{ color: {GRAY_500}; }}

/* Pannello miniature */
#tkThumbs {{ background: {GRAY_100}; border: 0; border-right: 1px solid {GRAY_200}; padding: 4px 0; }}

/* Ricerca */
#tkSearch {{ background: white; border-bottom: 1px solid {GRAY_200}; }}

/* Bottoni generici */
QPushButton {{
    background: {GRAY_100}; border: 0; border-radius: 6px; padding: 7px 16px; font-weight: 700; color: {NAVY};
}}
QPushButton:hover {{ background: {GRAY_200}; }}
QPushButton:disabled {{ color: {GRAY_300}; }}
QPushButton#primary, QPushButton[default="true"] {{ background: {NAVY}; color: white; }}
QPushButton#primary:hover, QPushButton[default="true"]:hover {{ background: {NAVY_2}; }}
QPushButton#accent {{ background: {ACCENT}; color: white; }}
QPushButton#accent:hover {{ background: {ACCENT_D}; }}

QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: white; border: 1px solid {GRAY_300}; border-radius: 6px; padding: 5px 8px;
    selection-background-color: {ACCENT}; selection-color: white;
}}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border: 1px solid {ACCENT}; }}
QComboBox {{ padding-right: 22px; }}
QComboBox::drop-down {{
    subcontrol-origin: padding; subcontrol-position: center right; width: 24px; border: 0; background: transparent;
}}
QComboBox::down-arrow {{ image: url("{ARROW_DARK}"); width: 10px; height: 6px; }}
QComboBox QAbstractItemView {{
    background: white; color: {NAVY}; border: 1px solid {GRAY_200}; padding: 4px; outline: 0;
    selection-background-color: {ACCENT_L}; selection-color: {ACCENT_D};
}}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border; width: 18px; border: 0; background: transparent;
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url("{ARROW_UP_DARK}"); width: 8px; height: 5px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url("{ARROW_DARK}"); width: 8px; height: 5px; }}
QGroupBox {{ border: 1px solid {GRAY_200}; border-radius: 10px; margin-top: 14px; padding: 12px; background: white; font-weight: 700; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px; }}

QMenu {{ background: white; border: 1px solid {GRAY_200}; padding: 4px; }}
QMenu::item {{ padding: 6px 22px 6px 12px; border-radius: 4px; }}
QMenu::item:selected {{ background: {ACCENT_L}; color: {ACCENT_D}; }}
QMenu::separator {{ height: 1px; background: {GRAY_200}; margin: 4px 6px; }}

QStatusBar {{ background: white; border-top: 1px solid {GRAY_200}; color: {GRAY_500}; }}
QToolTip {{ background: {NAVY}; color: white; border: 0; padding: 5px 8px; }}

QScrollBar:vertical {{ background: transparent; width: 12px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {GRAY_300}; border-radius: 5px; min-height: 30px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: {GRAY_300}; border-radius: 5px; min-width: 30px; margin: 2px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* Schermata iniziale */
#tkWelcome {{ background: {GRAY_50}; }}
#tkWelcomeCard {{ background: white; border: 1px solid {GRAY_200}; border-radius: 14px; }}
#tkWelcomeTitle {{ font-size: 20pt; font-weight: 800; }}
#tkWelcomeSub {{ color: {GRAY_500}; font-size: 10.5pt; }}
#tkRecent {{ border: 0; background: transparent; }}
#tkRecent::item {{ padding: 8px; border-radius: 6px; }}
#tkRecent::item:hover {{ background: {GRAY_100}; }}
#tkRecent::item:selected {{ background: {ACCENT_L}; color: {ACCENT_D}; }}
"""

# macOS usa 72 dpi logici: 10pt = 10px (su Windows 13px). Si scala per avere la stessa resa.
if __import__("sys").platform == "darwin":
    import re as _re
    QSS = _re.sub(r"(\d+(?:\.\d+)?)pt", lambda m: f"{float(m.group(1)) * 1.3:.1f}pt", QSS)
