"""Finestre di dialogo."""
import os
import re
import sys
import time

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtCore import QUrl
from PySide6.QtGui import (
    QColor, QDesktopServices, QIcon, QImage, QPainter, QPainterPath, QPen, QPixmap,
)
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPlainTextEdit, QPushButton, QRadioButton, QSpinBox, QVBoxLayout, QWidget,
)

from tkpdf import APP_TITLE, AUTHOR, AUTHOR_URL, VERSION
from tkpdf.util import FAMILY_LABELS, signatures_dir


def _buttons(dialog, ok_text="OK"):
    box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    ok = box.button(QDialogButtonBox.StandardButton.Ok)
    ok.setText(ok_text)
    ok.setObjectName("primary")
    box.button(QDialogButtonBox.StandardButton.Cancel).setText("Annulla")
    box.accepted.connect(dialog.accept)
    box.rejected.connect(dialog.reject)
    return box


class ColorButton(QPushButton):
    colorChanged = Signal(QColor)

    def __init__(self, color=QColor("black"), parent=None):
        super().__init__(parent)
        self.setFixedSize(QSize(46, 30))
        self.setToolTip("Scegli colore")
        self._color = QColor(color)
        self.clicked.connect(self._pick)
        self._refresh()

    def color(self):
        return QColor(self._color)

    def setColor(self, color):
        self._color = QColor(color)
        self._refresh()

    def _refresh(self):
        self.setStyleSheet(
            f"QPushButton {{ background: {self._color.name()}; border: 2px solid #cbd5e1; border-radius: 6px; }}"
        )

    def _pick(self):
        c = QColorDialog.getColor(self._color, self, "Scegli colore")
        if c.isValid():
            self.setColor(c)
            self.colorChanged.emit(c)


# ====================================================================== testo
class TextDialog(QDialog):
    """Usato sia per 'Aggiungi testo' sia per 'Modifica testo esistente'."""

    def __init__(self, parent=None, title="Testo", text="", family="sans", size=11.0, bold=False,
                 italic=False, color=QColor("black"), multiline=True, allow_original=False, note=""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)

        if note:
            lab = QLabel(note)
            lab.setWordWrap(True)
            lab.setStyleSheet("color:#64748b;")
            lay.addWidget(lab)

        if multiline:
            self.edit = QPlainTextEdit(text)
            self.edit.setMinimumHeight(110)
        else:
            self.edit = QLineEdit(text)
            self.edit.selectAll()
        lay.addWidget(self.edit)

        form = QFormLayout()
        self.family = QComboBox()
        if allow_original:
            self.family.addItem("Stesso font del documento (incorporato o da Google Fonts)", "original")
        for key, label in FAMILY_LABELS.items():
            self.family.addItem(label, key)
        idx = self.family.findData("original" if allow_original else family)
        self.family.setCurrentIndex(max(0, idx))
        self._fallback_family = family
        form.addRow("Carattere", self.family)

        row = QHBoxLayout()
        self.size = QDoubleSpinBox()
        self.size.setRange(4, 200)
        self.size.setDecimals(1)
        self.size.setValue(size)
        self.size.setSuffix(" pt")
        self.bold = QCheckBox("Grassetto")
        self.bold.setChecked(bold)
        self.italic = QCheckBox("Corsivo")
        self.italic.setChecked(italic)
        self.color = ColorButton(color)
        row.addWidget(self.size)
        row.addWidget(self.bold)
        row.addWidget(self.italic)
        row.addStretch(1)
        row.addWidget(QLabel("Colore"))
        row.addWidget(self.color)
        form.addRow("Dimensione", row)
        lay.addLayout(form)
        lay.addWidget(_buttons(self, "Applica"))
        self.edit.setFocus()

    def values(self):
        text = self.edit.toPlainText() if isinstance(self.edit, QPlainTextEdit) else self.edit.text()
        return dict(text=text, family=self.family.currentData(), fallback_family=self._fallback_family,
                    size=self.size.value(), bold=self.bold.isChecked(), italic=self.italic.isChecked(),
                    color=self.color.color())


class NoteDialog(QDialog):
    def __init__(self, parent=None, title="Nota", text=""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(380)
        lay = QVBoxLayout(self)
        self.edit = QPlainTextEdit(text)
        self.edit.setMinimumHeight(120)
        lay.addWidget(self.edit)
        lay.addWidget(_buttons(self, "Salva"))
        self.edit.setFocus()

    def text(self):
        return self.edit.toPlainText()


# ====================================================================== firma
class SignaturePad(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(560, 220)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.strokes = []
        self.pen_color = QColor("#0f172a")
        self.pen_width = 3.0
        self.image = None  # immagine caricata al posto del disegno

    def clear(self):
        self.strokes = []
        self.image = None
        self.update()

    def is_empty(self):
        return not self.strokes and self.image is None

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.image = None
            self.strokes.append([e.position()])
            self.update()

    def mouseMoveEvent(self, e):
        if self.strokes and e.buttons() & Qt.MouseButton.LeftButton:
            self.strokes[-1].append(e.position())
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("white"))
        p.setPen(QPen(QColor("#e2e8f0"), 1, Qt.PenStyle.DashLine))
        base = self.height() * 0.72
        p.drawLine(24, int(base), self.width() - 24, int(base))
        p.setPen(QPen(QColor("#94a3b8")))
        if self.is_empty():
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Firma qui con il mouse, la penna o il dito")
        if self.image is not None:
            target = QRectF(self.rect()).adjusted(20, 20, -20, -20)
            img = self.image.scaled(target.size().toSize(), Qt.AspectRatioMode.KeepAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation)
            p.drawImage(QPointF(target.center().x() - img.width() / 2, target.center().y() - img.height() / 2), img)
        self._draw_strokes(p, 1.0, QPointF(0, 0))

    def _draw_strokes(self, p, scale, offset):
        pen = QPen(self.pen_color, self.pen_width * scale, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                   Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        for stroke in self.strokes:
            if len(stroke) == 1:
                p.drawPoint((stroke[0] - offset) * scale)
                continue
            path = QPainterPath((stroke[0] - offset) * scale)
            for i in range(1, len(stroke) - 1):
                mid = (stroke[i] + stroke[i + 1]) / 2
                path.quadTo((stroke[i] - offset) * scale, (mid - offset) * scale)
            path.lineTo((stroke[-1] - offset) * scale)
            p.drawPath(path)

    def to_image(self):
        """Immagine PNG trasparente ritagliata sul disegno."""
        if self.image is not None:
            return self.image
        if not self.strokes:
            return None
        xs = [pt.x() for s in self.strokes for pt in s]
        ys = [pt.y() for s in self.strokes for pt in s]
        margin = self.pen_width * 2
        left, top = min(xs) - margin, min(ys) - margin
        w, h = max(xs) - left + margin, max(ys) - top + margin
        scale = 4.0
        img = QImage(int(w * scale) + 1, int(h * scale) + 1, QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._draw_strokes(p, scale, QPointF(left, top))
        p.end()
        return img


SIGNATURE_NOTICE = ("Questa è una <b>firma grafica</b> (un'immagine sulla pagina): non è una firma digitale "
                    "né qualificata e non ha valore dove serve la firma digitale.")


def signature_notice():
    lab = QLabel("ℹ️ " + SIGNATURE_NOTICE)
    lab.setWordWrap(True)
    lab.setTextFormat(Qt.TextFormat.RichText)
    lab.setStyleSheet("background:#fef3c7; color:#78350f; border:1px solid #fcd34d; border-radius:6px; padding:8px 10px;")
    return lab


class SignatureDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Nuova firma")
        lay = QVBoxLayout(self)
        self.pad = SignaturePad()
        self.pad.setStyleSheet("border:1px solid #cbd5e1;")
        lay.addWidget(self.pad)

        row = QHBoxLayout()
        self.colors = QButtonGroup(self)
        for i, (name, hexc) in enumerate((("Nero", "#0f172a"), ("Blu", "#1d4ed8"), ("Rosso", "#b91c1c"))):
            rb = QRadioButton(name)
            rb.setChecked(i == 0)
            rb.toggled.connect(lambda on, c=hexc: on and self._set_color(c))
            self.colors.addButton(rb)
            row.addWidget(rb)
        row.addSpacing(12)
        row.addWidget(QLabel("Spessore"))
        self.width_spin = QSpinBox()
        self.width_spin.setRange(1, 10)
        self.width_spin.setValue(3)
        self.width_spin.valueChanged.connect(self._set_width)
        row.addWidget(self.width_spin)
        row.addStretch(1)
        load = QPushButton("🖼️ Carica immagine…")
        load.clicked.connect(self._load)
        clear = QPushButton("🧽 Cancella")
        clear.clicked.connect(self.pad.clear)
        row.addWidget(load)
        row.addWidget(clear)
        lay.addLayout(row)

        # spenta di default: la firma resta sul computer solo se lo chiedi
        self.save_it = QCheckBox("Salva questa firma su questo computer per usarla di nuovo")
        self.save_it.setChecked(False)
        lay.addWidget(self.save_it)
        lay.addWidget(signature_notice())
        lay.addWidget(_buttons(self, "Usa firma"))

    def _set_color(self, c):
        self.pad.pen_color = QColor(c)
        self.pad.update()

    def _set_width(self, v):
        self.pad.pen_width = float(v)
        self.pad.update()

    def _load(self):
        path, _ = QFileDialog.getOpenFileName(self, "Immagine della firma", "", "Immagini (*.png *.jpg *.jpeg *.bmp *.webp)")
        if path:
            img = QImage(path)
            if img.isNull():
                QMessageBox.warning(self, APP_TITLE, "Immagine non valida.")
                return
            self.pad.strokes = []
            self.pad.image = img
            self.pad.update()

    def accept(self):
        if self.pad.is_empty():
            QMessageBox.information(self, APP_TITLE, "Disegna la firma o carica un'immagine.")
            return
        super().accept()

    def result_image(self):
        img = self.pad.to_image()
        if img is not None and self.save_it.isChecked():
            path = os.path.join(signatures_dir(), f"firma-{int(time.time())}.png")
            img.save(path, "PNG")
        return img


def saved_signatures():
    d = signatures_dir()
    files = [os.path.join(d, f) for f in os.listdir(d) if f.lower().endswith(".png")]
    return sorted(files, key=os.path.getmtime, reverse=True)


# ====================================================================== timbri
STAMPS = [
    ("APPROVATO", "#15803d"), ("RICEVUTO", "#1d4ed8"), ("PAGATO", "#15803d"), ("BOZZA", "#64748b"),
    ("CONFIDENZIALE", "#b91c1c"), ("RIFIUTATO", "#b91c1c"), ("COPIA", "#64748b"), ("URGENTE", "#b91c1c"),
]


class StampDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Timbro personalizzato")
        lay = QFormLayout(self)
        self.text = QLineEdit("VISTO")
        self.color = ColorButton(QColor("#b91c1c"))
        self.date = QCheckBox("Aggiungi data di oggi")
        self.date.setChecked(True)
        lay.addRow("Testo", self.text)
        lay.addRow("Colore", self.color)
        lay.addRow("", self.date)
        lay.addRow(_buttons(self, "Usa timbro"))

    def values(self):
        text = self.text.text().strip() or "VISTO"
        if self.date.isChecked():
            text += "\n" + time.strftime("%d/%m/%Y")
        return text, self.color.color()


# ====================================================================== unisci
OPEN_FILTER = "PDF e immagini (*.pdf *.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.webp);;PDF (*.pdf);;Tutti i file (*.*)"


class MergeDialog(QDialog):
    def __init__(self, parent=None, files=None, title="Unisci PDF e immagini", intro=""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(520, 380)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(intro or "Aggiungi i file e trascinali per scegliere l'ordine."))
        body = QHBoxLayout()
        self.list = QListWidget()
        self.list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        body.addWidget(self.list, 1)
        side = QVBoxLayout()
        for text, slot in (("➕ Aggiungi…", self._add), ("⬆️ Su", lambda: self._move(-1)),
                           ("⬇️ Giù", lambda: self._move(1)), ("🗑️ Rimuovi", self._remove)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            side.addWidget(b)
        side.addStretch(1)
        body.addLayout(side)
        lay.addLayout(body)
        lay.addWidget(_buttons(self, "Unisci"))
        for f in files or []:
            self._append(f)

    def _append(self, path):
        item = QListWidgetItem(("🖼️ " if not path.lower().endswith(".pdf") else "📄 ") + os.path.basename(path))
        item.setData(Qt.ItemDataRole.UserRole, path)
        item.setToolTip(path)
        self.list.addItem(item)

    def _add(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Aggiungi file", "", OPEN_FILTER)
        for f in files:
            self._append(f)

    def _move(self, step):
        row = self.list.currentRow()
        new = row + step
        if row < 0 or not 0 <= new < self.list.count():
            return
        item = self.list.takeItem(row)
        self.list.insertItem(new, item)
        self.list.setCurrentRow(new)

    def _remove(self):
        for item in self.list.selectedItems():
            self.list.takeItem(self.list.row(item))

    def files(self):
        return [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())]

    def accept(self):
        if not self.files():
            QMessageBox.information(self, APP_TITLE, "Aggiungi almeno un file.")
            return
        super().accept()


# ====================================================================== dividi
class SplitDialog(QDialog):
    def __init__(self, parent, page_count, base_name, folder):
        super().__init__(parent)
        self.setWindowTitle("Dividi PDF")
        self.setMinimumWidth(480)
        self.page_count = page_count
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"Il documento ha <b>{page_count}</b> pagine."))

        self.rb_each = QRadioButton("Una pagina per file")
        self.rb_n = QRadioButton("Ogni")
        self.rb_ranges = QRadioButton("Intervalli (un file per intervallo)")
        self.rb_each.setChecked(True)
        self.n = QSpinBox()
        self.n.setRange(1, max(1, page_count))
        self.n.setValue(min(2, max(1, page_count)))
        self.ranges = QLineEdit()
        self.ranges.setPlaceholderText("es. 1-3, 4, 5-10")
        self.ranges.textEdited.connect(lambda: self.rb_ranges.setChecked(True))

        lay.addWidget(self.rb_each)
        row = QHBoxLayout()
        row.addWidget(self.rb_n)
        row.addWidget(self.n)
        row.addWidget(QLabel("pagine"))
        row.addStretch(1)
        lay.addLayout(row)
        lay.addWidget(self.rb_ranges)
        lay.addWidget(self.ranges)

        form = QFormLayout()
        self.name = QLineEdit(base_name)
        frow = QHBoxLayout()
        self.folder = QLineEdit(folder)
        browse = QPushButton("Sfoglia…")
        browse.clicked.connect(self._browse)
        frow.addWidget(self.folder)
        frow.addWidget(browse)
        form.addRow("Nome base", self.name)
        form.addRow("Cartella", frow)
        lay.addLayout(form)
        lay.addWidget(_buttons(self, "Dividi"))

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Cartella di destinazione", self.folder.text())
        if d:
            self.folder.setText(d)

    def groups(self):
        n = self.page_count
        if self.rb_each.isChecked():
            return [[i] for i in range(n)]
        if self.rb_n.isChecked():
            k = self.n.value()
            return [list(range(i, min(i + k, n))) for i in range(0, n, k)]
        return parse_ranges(self.ranges.text(), n, grouped=True)

    def accept(self):
        try:
            groups = self.groups()
        except ValueError as exc:
            QMessageBox.warning(self, APP_TITLE, str(exc))
            return
        if not groups:
            QMessageBox.warning(self, APP_TITLE, "Indica almeno un intervallo di pagine.")
            return
        if not os.path.isdir(self.folder.text()):
            QMessageBox.warning(self, APP_TITLE, "La cartella di destinazione non esiste.")
            return
        super().accept()


def parse_ranges(text, page_count, grouped=False):
    """'1-3, 5' -> [[0,1,2],[4]] (grouped) oppure [0,1,2,4]."""
    groups = []
    for part in re.split(r"[;,]", text):
        part = part.strip()
        if not part:
            continue
        m = re.fullmatch(r"(\d+)\s*-\s*(\d+)", part)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
        elif part.isdigit():
            a = b = int(part)
        else:
            raise ValueError(f"Intervallo non valido: «{part}»")
        if a < 1 or b > page_count or a > b:
            raise ValueError(f"Intervallo fuori dalle pagine (1-{page_count}): «{part}»")
        groups.append(list(range(a - 1, b)))
    if grouped:
        return groups
    return [p for g in groups for p in g]


# ====================================================================== comprimi
class CompressDialog(QDialog):
    LEVELS = [
        ("Leggera — qualità alta (immagini 150 dpi)", 150, 80),
        ("Media — consigliata (immagini 110 dpi)", 110, 65),
        ("Forte — file minimo (immagini 72 dpi)", 72, 45),
    ]

    def __init__(self, parent, size_now):
        super().__init__(parent)
        self.setWindowTitle("Comprimi PDF")
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"Dimensione attuale stimata: <b>{size_now}</b>"))
        self.group = QButtonGroup(self)
        for i, (label, _, _) in enumerate(self.LEVELS):
            rb = QRadioButton(label)
            rb.setChecked(i == 1)
            self.group.addButton(rb, i)
            lay.addWidget(rb)
        self.gray = QCheckBox("Converti le immagini in bianco e nero (scala di grigi)")
        lay.addWidget(self.gray)
        lay.addWidget(_buttons(self, "Comprimi"))

    def values(self):
        _, dpi, quality = self.LEVELS[self.group.checkedId()]
        return dpi, quality, self.gray.isChecked()


# ====================================================================== password
class PasswordDialog(QDialog):
    def __init__(self, parent=None, confirm=False, title="Password", message=""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(360)
        lay = QFormLayout(self)
        if message:
            lab = QLabel(message)
            lab.setWordWrap(True)
            lay.addRow(lab)
        self.pw = QLineEdit()
        self.pw.setEchoMode(QLineEdit.EchoMode.Password)
        lay.addRow("Password", self.pw)
        self.pw2 = None
        if confirm:
            self.pw2 = QLineEdit()
            self.pw2.setEchoMode(QLineEdit.EchoMode.Password)
            lay.addRow("Ripeti", self.pw2)
        lay.addRow(_buttons(self, "OK"))

    def accept(self):
        if self.pw2 is not None:
            if len(self.pw.text()) < 4:
                QMessageBox.warning(self, APP_TITLE, "Usa una password di almeno 4 caratteri.")
                return
            if self.pw.text() != self.pw2.text():
                QMessageBox.warning(self, APP_TITLE, "Le due password non coincidono.")
                return
        super().accept()

    def password(self):
        return self.pw.text()


# ====================================================================== info
class AboutDialog(QDialog):
    """Informazioni: stessa impaginazione dell'app per telefono e di tk-tv (fondo navy, schede, pulsante accento)."""

    def __init__(self, parent=None, icon: QIcon = None, su_aggiornamenti=None, recenti=0):
        super().__init__(parent)
        self.setWindowTitle("Informazioni")
        self.setMinimumWidth(420)
        self.setStyleSheet(
            "QDialog { background: #0f172a; }"
            "QLabel { color: #ffffff; }"
            "#tkInfoCard { background: #1e293b; border-radius: 14px; }"
            "#tkInfoTitolo { color: #e11d48; font-size: 11px; font-weight: 800; letter-spacing: 1px; }"
            "#tkInfoEtichetta { color: #cbd5e1; font-size: 13px; }"
            "#tkInfoValore { color: #ffffff; font-size: 13px; font-weight: 700; }"
            "#tkInfoPie { color: #64748b; font-size: 11px; }"
            "QCheckBox { color: #ffffff; font-size: 13px; spacing: 8px; }"
            "QPushButton#tkChiaro { background: #334155; color: white; border: 0; border-radius: 10px;"
            " padding: 11px 16px; font-weight: 600; }"
            "QPushButton#tkChiaro:hover { background: #3f5168; }"
            "QPushButton#tkAccento { background: #e11d48; color: white; border: 0; border-radius: 12px;"
            " padding: 13px 16px; font-weight: 700; }"
            "QPushButton#tkAccento:hover { background: #be123c; }"
        )
        # contenuto in un'area che scorre: su uno schermo basso la finestra non esce dallo schermo
        from PySide6.QtWidgets import QFrame, QScrollArea
        self._corpo = QWidget()
        self._corpo.setObjectName("tkInfoCorpo")
        self._corpo.setStyleSheet("#tkInfoCorpo { background: #0f172a; }")
        lay = QVBoxLayout(self._corpo)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(16)
        self._scorri = QScrollArea()
        self._scorri.setWidget(self._corpo)
        self._scorri.setWidgetResizable(True)
        self._scorri.setFrameShape(QFrame.Shape.NoFrame)
        self._scorri.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scorri.setStyleSheet("QScrollArea { background: #0f172a; }")
        fuori = QVBoxLayout(self)
        fuori.setContentsMargins(0, 0, 0, 0)
        fuori.addWidget(self._scorri)

        # icona su quadrato accento, come sul telefono
        testa = QVBoxLayout()
        testa.setSpacing(2)
        quadro = QLabel()
        quadro.setFixedSize(72, 72)
        quadro.setAlignment(Qt.AlignmentFlag.AlignCenter)
        quadro.setStyleSheet("background: qlineargradient(x1:0, y1:0, x2:1, y2:1,"
                             " stop:0 #e11d48, stop:1 #be123c); border-radius: 20px;")
        from tkpdf.icon import render_icon
        quadro.setPixmap(QPixmap.fromImage(render_icon(44, solo_foglio=True)))
        testa.addWidget(quadro, alignment=Qt.AlignmentFlag.AlignHCenter)
        nome = QLabel(APP_TITLE)
        nome.setStyleSheet("font-size: 20px; font-weight: 800;")
        testa.addWidget(nome, alignment=Qt.AlignmentFlag.AlignHCenter)
        riga = QLabel(f"Lettore ed editor PDF — versione {VERSION}")
        riga.setStyleSheet("color: #cbd5e1; font-size: 12px;")
        testa.addWidget(riga, alignment=Qt.AlignmentFlag.AlignHCenter)
        lay.addLayout(testa)

        sistema = "Windows" if sys.platform == "win32" else ("macOS" if sys.platform == "darwin" else sys.platform)
        lay.addWidget(self._scheda("Versione", [
            ("Versione", VERSION),
            ("Sistema", sistema),
            ("Documenti recenti", str(recenti)),
        ]))

        sviluppatore = self._scheda("Sviluppatore", [("Autore", AUTHOR)])
        sito = QPushButton("Visita pietrodefilippis.it")
        sito.setObjectName("tkChiaro")
        sito.setCursor(Qt.CursorShape.PointingHandCursor)
        sito.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(AUTHOR_URL)))
        sviluppatore.layout().addSpacing(6)
        sviluppatore.layout().addWidget(sito)
        lay.addWidget(sviluppatore)

        if su_aggiornamenti is not None:
            aggiorna = QPushButton("⬇  Controlla aggiornamenti")
            aggiorna.setObjectName("tkAccento")
            aggiorna.setCursor(Qt.CursorShape.PointingHandCursor)
            aggiorna.clicked.connect(lambda: (self.accept(), su_aggiornamenti()))
            lay.addWidget(aggiorna)

        telefono = QPushButton("C'è anche per Android")
        telefono.setObjectName("tkChiaro")
        telefono.setCursor(Qt.CursorShape.PointingHandCursor)
        # pagina delle app per telefono, non la home
        telefono.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(AUTHOR_URL + "/app/")))
        lay.addWidget(telefono)

        # software libero: licenza, codice sorgente e scelte sulla privacy
        from tkpdf import pro, webfonts
        libero = self._scheda("Software libero · AGPL-3.0", [])
        testo = QLabel("tk-pdf è gratuito con tutte le funzioni: puoi usarlo, studiarlo, modificarlo e condividerlo. "
                       "È fornito senza alcuna garanzia.")
        testo.setObjectName("tkInfoEtichetta")
        testo.setWordWrap(True)
        libero.layout().addWidget(testo)
        from tkpdf.tk_licenza_qt import stile_casella

        def spiega(t):
            # spiegazione sempre visibile sotto la casella (al posto del suggerimento su una riga lunghissima)
            s = QLabel(t)
            s.setObjectName("tkInfoEtichetta")
            s.setWordWrap(True)
            s.setContentsMargins(30, 0, 0, 4)
            return s

        stat = pro.casella_statistiche()
        stat.setToolTip("")
        libero.layout().addWidget(stat)
        libero.layout().addWidget(spiega("Una volta al giorno: nome, versione e sistema, con un codice casuale. "
                                         "Niente file né contenuti."))
        font = QCheckBox("Scarica da Google Fonts i caratteri mancanti")
        font.setObjectName("tkCasella")
        font.setStyleSheet(stile_casella("QCheckBox#tkCasella"))
        font.setChecked(webfonts.consent() is True)
        font.toggled.connect(webfonts.set_consent)
        libero.layout().addWidget(font)
        libero.layout().addWidget(spiega("Solo quando riscrivi un testo con un carattere che manca nel PDF. Google "
                                         "riceve l'indirizzo IP e il nome del font; senza, si usa un font simile."))
        licenze = QPushButton("Licenze e codice sorgente")
        licenze.setObjectName("tkChiaro")
        licenze.setCursor(Qt.CursorShape.PointingHandCursor)
        licenze.clicked.connect(lambda: pro.mostra_licenze(self))
        libero.layout().addSpacing(6)
        libero.layout().addWidget(licenze)
        lay.addWidget(libero)

        caffe = pro.pulsante_caffe("tkChiaro")
        if caffe is not None:
            lay.addWidget(caffe)

        pie = QLabel(f"© 2026 Pietro De Filippis ({AUTHOR}) — pietrodefilippis.it")
        pie.setObjectName("tkInfoPie")
        lay.addWidget(pie)

        chiudi = QPushButton("Chiudi")
        chiudi.setObjectName("tkChiaro")
        chiudi.setCursor(Qt.CursorShape.PointingHandCursor)
        chiudi.clicked.connect(self.accept)
        lay.addWidget(chiudi, alignment=Qt.AlignmentFlag.AlignRight)
        self._misura()

    LARGHEZZA = 440

    def _misura(self):
        """Larghezza fissa e altezza calcolata sul testo vero (le etichette che vanno a capo non vengono
        schiacciate); oltre l'altezza dello schermo il contenuto scorre."""
        from PySide6.QtGui import QGuiApplication
        self.setFixedWidth(self.LARGHEZZA)
        utile = self.LARGHEZZA - self._scorri.verticalScrollBar().sizeHint().width()
        alto = self._corpo.layout().totalHeightForWidth(utile)
        if alto <= 0:
            alto = self._corpo.sizeHint().height()
        schermo = QGuiApplication.primaryScreen()
        massimo = (schermo.availableGeometry().height() - 60) if schermo is not None else 900
        self.resize(self.LARGHEZZA, min(alto + 2, massimo))

    def showEvent(self, ev):
        super().showEvent(ev)
        from tkpdf.tk_licenza_qt import centra
        centra(self)

    @staticmethod
    def _scheda(titolo, righe):
        card = QWidget()
        card.setObjectName("tkInfoCard")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        v = QVBoxLayout(card)
        v.setContentsMargins(16, 14, 16, 16)
        v.setSpacing(6)
        intestazione = QLabel(titolo.upper())
        intestazione.setObjectName("tkInfoTitolo")
        v.addWidget(intestazione)
        for etichetta, valore in righe:
            riga = QHBoxLayout()
            sinistra = QLabel(etichetta)
            sinistra.setObjectName("tkInfoEtichetta")
            destra = QLabel(valore)
            destra.setObjectName("tkInfoValore")
            riga.addWidget(sinistra)
            riga.addStretch(1)
            riga.addWidget(destra)
            v.addLayout(riga)
        return card
