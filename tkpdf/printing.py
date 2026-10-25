"""Finestra di stampa di tk-pdf con anteprima.

Su Windows 11 la finestra di sistema si intitola «Python - Stampa» (nome dell'eseguibile) e non ha
anteprima: qui si sceglie tutto dentro l'app e si stampa direttamente con QPrinter."""
import subprocess
import sys

import pymupdf as fitz
from PySide6.QtCore import QMarginsF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPageLayout, QPageSize, QPainter, QPen
from PySide6.QtPrintSupport import QPrinter, QPrinterInfo
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QProgressDialog, QPushButton, QRadioButton, QSizePolicy, QSpinBox, QVBoxLayout, QWidget,
)

from tkpdf import APP_TITLE
from tkpdf.dialogs import parse_ranges

ORIENT_AUTO, ORIENT_PORTRAIT, ORIENT_LANDSCAPE = 0, 1, 2
FIT_PAGE, FIT_ACTUAL = 0, 1
DUPLEX = [
    (QPrinter.DuplexMode.DuplexNone, "Solo fronte"),
    (QPrinter.DuplexMode.DuplexLongSide, "Fronte/retro (lato lungo)"),
    (QPrinter.DuplexMode.DuplexShortSide, "Fronte/retro (lato corto)"),
]
STATES = {
    QPrinter.PrinterState.Idle: ("✅ Pronta", "#15803d"),
    QPrinter.PrinterState.Active: ("🖨️ Sta stampando", "#1d4ed8"),
    QPrinter.PrinterState.Aborted: ("⚠️ Stampa interrotta", "#b45309"),
    QPrinter.PrinterState.Error: ("⚠️ Non pronta: controlla che sia accesa e collegata", "#b91c1c"),
}


def page_view_size(page):
    """Dimensioni (pt) della pagina come appare, rotazione compresa."""
    r = page.rect
    return r.width, r.height


def place(page_w, page_h, paper, paint, fit):
    """Dove disegnare la pagina sul foglio (tutto in punti).

    paper: QRectF del foglio, paint: QRectF dell'area stampabile. Ritorna (ruota90, QRectF)."""
    paper_land = paper.width() > paper.height()
    rotate = (page_w > page_h) != paper_land and abs(page_w - page_h) > 1
    if rotate:
        page_w, page_h = page_h, page_w
    if fit == FIT_PAGE:
        k = min(paint.width() / page_w, paint.height() / page_h)
    else:  # dimensione reale, ridotta solo se non entra
        k = min(1.0, paint.width() / page_w, paint.height() / page_h)
    w, h = page_w * k, page_h * k
    c = paint.center()
    return rotate, QRectF(c.x() - w / 2, c.y() - h / 2, w, h)


def render_page(page, width_px, rotate, gray):
    """Rende la pagina (con annotazioni) larga width_px pixel dopo l'eventuale rotazione."""
    pw, ph = page_view_size(page)
    base = ph if rotate else pw
    zoom = max(0.05, width_px / base)
    mat = fitz.Matrix(zoom, zoom)
    if rotate:
        # pagina già ruotata di 90° nel PDF: si ruota al contrario, così il testo resta dritto
        mat = mat.prerotate(-90 if page.rotation == 90 else 90)
    cs = fitz.csGRAY if gray else fitz.csRGB
    pix = page.get_pixmap(matrix=mat, colorspace=cs, alpha=False, annots=True)
    fmt = QImage.Format.Format_Grayscale8 if gray else QImage.Format.Format_RGB888
    return QImage(pix.samples, pix.width, pix.height, pix.stride, fmt).copy()


# ====================================================================== anteprima
class SheetPreview(QWidget):
    def __init__(self, dialog):
        super().__init__()
        self.dlg = dialog
        self.setMinimumSize(420, 460)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._cache = {}

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor("#e2e8f0"))
        info = self.dlg.sheet_info()
        if info is None:
            p.setPen(QColor("#64748b"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.dlg.pages_error or "Nessuna pagina da stampare")
            return
        pno, paper, paint = info
        area = QRectF(self.rect()).adjusted(30, 30, -30, -30)
        k = min(area.width() / paper.width(), area.height() / paper.height())
        sheet = QRectF(0, 0, paper.width() * k, paper.height() * k)
        sheet.moveCenter(area.center())
        # ombra + foglio
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(15, 23, 42, 40))
        p.drawRoundedRect(sheet.translated(3, 4), 3, 3)
        p.setBrush(QColor("white"))
        p.drawRect(sheet)
        page = self.dlg.doc[pno]
        pw, ph = page_view_size(page)
        rotate, target = place(pw, ph, paper, paint, self.dlg.fit_mode())
        t = QRectF(sheet.x() + target.x() * k, sheet.y() + target.y() * k, target.width() * k, target.height() * k)
        gray = self.dlg.is_gray()
        key = (pno, rotate, gray, round(t.width()), self.dlg.doc_revision)
        img = self._cache.get(key)
        if img is None:
            if len(self._cache) > 12:
                self._cache.clear()
            img = render_page(page, t.width() * self.devicePixelRatioF(), rotate, gray)
            self._cache[key] = img
        p.drawImage(t, img)
        # area non stampabile
        m = QRectF(sheet.x() + paint.x() * k, sheet.y() + paint.y() * k, paint.width() * k, paint.height() * k)
        p.setPen(QPen(QColor("#cbd5e1"), 1, Qt.PenStyle.DashLine))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(m)


# ====================================================================== finestra
class PrintDialog(QDialog):
    def __init__(self, parent, pdf, current_page, settings):
        super().__init__(parent)
        self.setWindowTitle(f"Stampa — {pdf.title()}")
        self.resize(1080, 760)
        self.pdf = pdf
        self.doc = pdf.doc
        self.doc_revision = pdf.revision
        self.current_page = current_page
        self.settings = settings
        self.pages_error = ""
        self._pages = []
        self._numbers = []
        self._sheet = 0
        self._layout_cache = {}

        root = QHBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(16)

        side_w = QWidget()
        side_w.setFixedWidth(330)
        side = QVBoxLayout(side_w)
        side.setContentsMargins(0, 0, 0, 0)
        side.setSpacing(6)

        side.addWidget(self._title("STAMPANTE"))
        self.printer = QComboBox()
        names = QPrinterInfo.availablePrinterNames()
        self.printer.addItems(names)
        default = QPrinterInfo.defaultPrinterName()
        wanted = settings.value("print/printer", default) if settings is not None else default
        idx = self.printer.findText(wanted if wanted in names else default)
        self.printer.setCurrentIndex(max(0, idx))
        side.addWidget(self.printer)
        self.state = QLabel()
        self.state.setWordWrap(True)
        side.addWidget(self.state)
        if sys.platform == "win32":
            prefs = QPushButton("⚙️ Preferenze della stampante…")
            prefs.setToolTip("Qualità, tipo di carta e altre opzioni del driver")
            prefs.clicked.connect(self._printer_prefs)
            side.addWidget(prefs)

        side.addSpacing(8)
        side.addWidget(self._title("PAGINE"))
        self.rb_all = QRadioButton(f"Tutte ({self.doc.page_count})")
        self.rb_cur = QRadioButton(f"Pagina corrente ({current_page + 1})")
        self.rb_range = QRadioButton("Intervallo")
        self.rb_all.setChecked(True)
        self.range_edit = QLineEdit()
        self.range_edit.setPlaceholderText("es. 1-3, 5")
        self.range_edit.textEdited.connect(lambda: (self.rb_range.setChecked(True), self._changed()))
        self.pages_group = QButtonGroup(self)
        for b in (self.rb_all, self.rb_cur, self.rb_range):
            self.pages_group.addButton(b)
            side.addWidget(b)
        side.addWidget(self.range_edit)
        self.pages_group.buttonClicked.connect(lambda _: self._changed())

        side.addSpacing(8)
        side.addWidget(self._title("COPIE"))
        self.copies = QSpinBox()
        self.copies.setRange(1, 999)
        side.addWidget(self.copies)

        side.addSpacing(8)
        side.addWidget(self._title("FOGLIO"))
        self.paper = QComboBox()
        self.orient = QComboBox()
        self.orient.addItems(["Orientamento automatico", "Verticale", "Orizzontale"])
        self.fit = QComboBox()
        self.fit.addItems(["Adatta al foglio", "Dimensione reale (riduce solo se non entra)"])
        self.color = QComboBox()
        self.color.addItems(["A colori", "Bianco e nero"])
        self.duplex = QComboBox()
        for w in (self.paper, self.orient, self.fit, self.color, self.duplex):
            side.addWidget(w)
        side.addStretch(1)

        btns = QHBoxLayout()
        cancel = QPushButton("Annulla")
        cancel.clicked.connect(self.reject)
        self.print_b = QPushButton("🖨️ Stampa")
        self.print_b.setObjectName("accent")
        self.print_b.setMinimumHeight(38)
        self.print_b.setDefault(True)
        self.print_b.clicked.connect(self.accept)
        btns.addWidget(cancel)
        btns.addWidget(self.print_b, 1)
        side.addLayout(btns)
        root.addWidget(side_w)

        right = QVBoxLayout()
        self.preview = SheetPreview(self)
        right.addWidget(self.preview, 1)
        nav = QHBoxLayout()
        nav.addStretch(1)
        self.prev_b = QPushButton("‹")
        self.next_b = QPushButton("›")
        for b in (self.prev_b, self.next_b):
            b.setFixedWidth(46)
            b.setStyleSheet("font-size:16pt; padding:0 0 3px 0;")
        self.prev_b.clicked.connect(lambda: self._go(-1))
        self.next_b.clicked.connect(lambda: self._go(1))
        self.sheet_label = QLabel()
        self.sheet_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sheet_label.setMinimumWidth(170)
        nav.addWidget(self.prev_b)
        nav.addWidget(self.sheet_label)
        nav.addWidget(self.next_b)
        nav.addStretch(1)
        right.addLayout(nav)
        root.addLayout(right, 1)

        if settings is not None:
            self.color.setCurrentIndex(1 if settings.value("print/gray", False, type=bool) else 0)
            self.fit.setCurrentIndex(int(settings.value("print/fit", FIT_PAGE) or 0))
        self.printer.currentIndexChanged.connect(self._printer_changed)
        for w in (self.paper, self.orient, self.fit, self.color):
            w.currentIndexChanged.connect(lambda _: self._changed())
        self._printer_changed()

    @staticmethod
    def _title(text):
        lab = QLabel(text)
        lab.setStyleSheet("color:#64748b; font-size:8.5pt; font-weight:700;")
        return lab

    # ------------------------------------------------------------ stampante
    def _info(self):
        return QPrinterInfo.printerInfo(self.printer.currentText())

    def _printer_changed(self):
        info = self._info()
        text, color = STATES.get(info.state(), ("", "#64748b"))
        if not self.printer.count():
            text, color = "⚠️ Nessuna stampante installata", "#b91c1c"
        self.state.setText(text)
        self.state.setStyleSheet(f"color:{color};")
        self._layout_cache.clear()

        prev = self.paper.currentData()
        self.paper.blockSignals(True)
        self.paper.clear()
        sizes = info.supportedPageSizes() or [QPageSize(QPageSize.PageSizeId.A4)]
        for s in sizes:
            self.paper.addItem(f"Carta {s.name()}", s.id())
        target = prev if prev is not None else (info.defaultPageSize().id() if info.defaultPageSize().isValid()
                                               else QPageSize.PageSizeId.A4)
        idx = self.paper.findData(target)
        if idx < 0:
            idx = self.paper.findData(QPageSize.PageSizeId.A4)
        self.paper.setCurrentIndex(max(0, idx))
        self.paper.blockSignals(False)

        supported = set(info.supportedDuplexModes())
        self.duplex.clear()
        for mode, label in DUPLEX:
            if mode == QPrinter.DuplexMode.DuplexNone or mode in supported:
                self.duplex.addItem(label, mode)
        self.duplex.setVisible(self.duplex.count() > 1)
        self._changed()

    def _printer_prefs(self):
        name = self.printer.currentText()
        if name:
            # finestra del driver: le scelte diventano le preferenze predefinite della stampante
            subprocess.Popen(["rundll32", "printui.dll,PrintUIEntry", "/e", "/n", name])

    def _make_printer(self):
        info = self._info()
        pr = QPrinter(info, QPrinter.PrinterMode.HighResolution)
        pr.setFullPage(True)
        size_id = self.paper.currentData()
        if size_id is not None:
            pr.setPageSize(QPageSize(size_id))
        pr.setPageOrientation(self._orientation())
        return pr

    def _orientation(self):
        mode = self.orient.currentIndex()
        if mode == ORIENT_LANDSCAPE:
            return QPageLayout.Orientation.Landscape
        if mode == ORIENT_PORTRAIT or not self._pages:
            return QPageLayout.Orientation.Portrait
        land = sum(1 for p in self._pages if p.rect.width > p.rect.height)
        return QPageLayout.Orientation.Landscape if land > len(self._pages) / 2 else QPageLayout.Orientation.Portrait

    def paper_rects(self):
        """(foglio, area stampabile) in punti, con margini reali della stampante."""
        key = (self.printer.currentText(), self.paper.currentData(), self._orientation())
        if key not in self._layout_cache:
            size_id = self.paper.currentData()
            page_size = QPageSize(size_id if size_id is not None else QPageSize.PageSizeId.A4)
            margins = QMarginsF(0, 0, 0, 0)
            try:
                if self.printer.count():
                    pr = self._make_printer()
                    lay = pr.pageLayout()
                    full, paint = QRectF(lay.fullRectPoints()), QRectF(lay.paintRectPoints())
                    margins = QMarginsF(paint.left() - full.left(), paint.top() - full.top(),
                                        full.right() - paint.right(), full.bottom() - paint.bottom())
            except Exception:
                pass
            lay = QPageLayout(page_size, self._orientation(), margins)
            self._layout_cache[key] = (QRectF(lay.fullRectPoints()), QRectF(lay.paintRectPoints()))
        return self._layout_cache[key]

    # ------------------------------------------------------------ opzioni
    def fit_mode(self):
        return self.fit.currentIndex()

    def is_gray(self):
        return self.color.currentIndex() == 1

    def page_numbers(self):
        n = self.doc.page_count
        if self.rb_cur.isChecked():
            return [min(self.current_page, n - 1)]
        if self.rb_range.isChecked():
            return parse_ranges(self.range_edit.text(), n)
        return list(range(n))

    def _changed(self):
        try:
            nums = self.page_numbers()
            self.pages_error = "" if nums else "Indica le pagine da stampare"
        except ValueError as exc:
            nums, self.pages_error = [], str(exc)
        self._numbers = nums
        self._pages = [self.doc[i] for i in nums]
        self._sheet = min(self._sheet, max(0, len(nums) - 1))
        self._refresh_nav()

    def _go(self, step):
        self._sheet = max(0, min(len(self._numbers) - 1, self._sheet + step))
        self._refresh_nav()

    def _refresh_nav(self):
        n = len(self._numbers)
        self.sheet_label.setText(f"Foglio {self._sheet + 1} di {n}  ·  pag. {self._numbers[self._sheet] + 1}" if n else "")
        self.prev_b.setEnabled(self._sheet > 0)
        self.next_b.setEnabled(self._sheet < n - 1)
        self.print_b.setEnabled(bool(n) and self.printer.count() > 0)
        self.preview.update()

    def sheet_info(self):
        if not self._numbers:
            return None
        paper, paint = self.paper_rects()
        return self._numbers[self._sheet], paper, paint

    # ------------------------------------------------------------ stampa
    def accept(self):
        try:
            nums = self.page_numbers()
        except ValueError as exc:
            QMessageBox.warning(self, APP_TITLE, str(exc))
            return
        if not nums:
            QMessageBox.warning(self, APP_TITLE, "Indica le pagine da stampare.")
            return
        if self.settings is not None:
            self.settings.setValue("print/printer", self.printer.currentText())
            self.settings.setValue("print/gray", self.is_gray())
            self.settings.setValue("print/fit", self.fit_mode())
        if self.print_now(nums):
            super().accept()

    def print_now(self, nums, output_file=None):
        pr = self._make_printer()
        pr.setDocName(self.pdf.title())
        if output_file:
            pr.setOutputFileName(output_file)
        pr.setColorMode(QPrinter.ColorMode.GrayScale if self.is_gray() else QPrinter.ColorMode.Color)
        if self.duplex.currentData() is not None:
            pr.setDuplex(self.duplex.currentData())
        copies = self.copies.value()
        manual_copies = 1
        if copies > 1:
            pr.setCollateCopies(True)
            pr.setCopyCount(copies)
            if pr.copyCount() != copies or not pr.supportsMultipleCopies():
                pr.setCopyCount(1)
                manual_copies = copies
        sequence = [n for _ in range(manual_copies) for n in nums]

        painter = QPainter()
        if not painter.begin(pr):
            QMessageBox.warning(self, APP_TITLE, "Impossibile avviare la stampa: controlla che la stampante sia "
                                                 "accesa e collegata.")
            return False
        progress = QProgressDialog("Invio alla stampante…", "Annulla", 0, len(sequence), self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(300)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        ok = True
        try:
            lay = pr.pageLayout()
            paper, paint = QRectF(lay.fullRectPoints()), QRectF(lay.paintRectPoints())
            scale = pr.resolution() / 72.0
            dpi = min(pr.resolution(), 300)
            for i, pno in enumerate(sequence):
                progress.setValue(i)
                progress.setLabelText(f"Stampa pagina {pno + 1} ({i + 1} di {len(sequence)})…")
                QApplication.processEvents()
                if progress.wasCanceled():
                    pr.abort()
                    ok = False
                    break
                if i:
                    pr.newPage()
                page = self.doc[pno]
                pw, ph = page_view_size(page)
                rotate, target = place(pw, ph, paper, paint, self.fit_mode())
                img = render_page(page, target.width() * dpi / 72.0, rotate, self.is_gray())
                dest = QRectF(target.x() * scale, target.y() * scale, target.width() * scale, target.height() * scale)
                painter.drawImage(dest, img)
        finally:
            painter.end()
            progress.close()
            QApplication.restoreOverrideCursor()
        return ok


def print_document(parent, pdf, current_page, settings):
    """True se la stampa è stata inviata."""
    if not QPrinterInfo.availablePrinterNames():
        QMessageBox.warning(parent, APP_TITLE, "Nessuna stampante installata.")
        return False
    return PrintDialog(parent, pdf, current_page, settings).exec() == QDialog.DialogCode.Accepted
