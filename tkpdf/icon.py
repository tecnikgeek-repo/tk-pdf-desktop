"""Icona dell'applicazione disegnata via codice (nessun file esterno necessario)."""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QLinearGradient, QPainter, QPainterPath, QPixmap


def render_icon(size, solo_foglio=False):
    """solo_foglio: disegna il foglio bianco senza il fondo navy (per i quadrati rossi, come sul telefono)."""
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = size / 256.0

    # fondo arrotondato navy -> accento
    p.setPen(Qt.PenStyle.NoPen)
    if not solo_foglio:
        grad = QLinearGradient(QPointF(0, 0), QPointF(size, size))
        grad.setColorAt(0, QColor("#0f172a"))
        grad.setColorAt(1, QColor("#334155"))
        p.setBrush(grad)
        p.drawRoundedRect(QRectF(8 * s, 8 * s, 240 * s, 240 * s), 52 * s, 52 * s)

    # foglio con angolo piegato
    page = QPainterPath()
    page.moveTo(64 * s, 36 * s)
    page.lineTo(158 * s, 36 * s)
    page.lineTo(196 * s, 74 * s)
    page.lineTo(196 * s, 204 * s)
    page.quadTo(196 * s, 216 * s, 184 * s, 216 * s)
    page.lineTo(76 * s, 216 * s)
    page.quadTo(64 * s, 216 * s, 64 * s, 204 * s)
    page.closeSubpath()
    p.setBrush(QColor("white"))
    p.drawPath(page)
    fold = QPainterPath()
    fold.moveTo(158 * s, 36 * s)
    fold.lineTo(158 * s, 74 * s)
    fold.lineTo(196 * s, 74 * s)
    fold.closeSubpath()
    p.setBrush(QColor("#cbd5e1"))
    p.drawPath(fold)

    # righe di testo
    p.setBrush(QColor("#ffe4e6") if solo_foglio else QColor("#e2e8f0"))
    for i, w in enumerate((80, 100, 64)):
        p.drawRoundedRect(QRectF(84 * s, (92 + i * 18) * s, w * s, 8 * s), 4 * s, 4 * s)

    # fascia PDF (dentro il quadrato rosso si tiene solo il foglio)
    if solo_foglio:
        p.end()
        return img
    p.setBrush(QColor("#e11d48"))
    p.drawRoundedRect(QRectF(40 * s, 150 * s, 176 * s, 58 * s), 14 * s, 14 * s)
    font = QFont("Segoe UI")
    font.setBold(True)
    font.setPixelSize(max(6, int(44 * s)))
    p.setFont(font)
    p.setPen(QColor("white"))
    p.drawText(QRectF(40 * s, 150 * s, 176 * s, 58 * s), Qt.AlignmentFlag.AlignCenter, "PDF")
    p.end()
    return img


def app_icon():
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(QPixmap.fromImage(render_icon(size)))
    return icon
