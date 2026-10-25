"""Vista continua delle pagine PDF con strumenti di annotazione e modifica."""
import math
import time
from bisect import bisect_right
from enum import Enum

import pymupdf as fitz
from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QColor, QCursor, QDesktopServices, QFont, QPainter, QPen, QPixmap, QPolygonF,
)
from PySide6.QtWidgets import (
    QApplication, QColorDialog, QFrame, QGraphicsItem, QGraphicsScene, QGraphicsView, QInputDialog,
    QLineEdit, QMenu, QMessageBox, QPlainTextEdit,
)

from tkpdf import APP_TITLE, webfonts
from tkpdf import objects as tko
from tkpdf.dialogs import NoteDialog, TextDialog
from tkpdf.style import ACCENT
from tkpdf.util import (
    find_original_font, fix_tounicode, font_for, font_renders_text, frect_to_qrect, guess_bold_italic, guess_family,
    int_to_rgb, pix_to_qimage, qcolor_to_rgb, rgb_to_qcolor, to_unrot_point, to_unrot_rect, to_view_rect,
)

PAGE_GAP = 14
SIDE_MARGIN = 14
PT_TO_PX = 96.0 / 72.0
MAX_PIXELS = 30_000_000


class Tool(Enum):
    SELECT = "select"
    HAND = "hand"
    HIGHLIGHT = "highlight"
    UNDERLINE = "underline"
    STRIKE = "strike"
    NOTE = "note"
    TEXTBOX = "textbox"
    INK = "ink"
    RECT = "rect"
    ELLIPSE = "ellipse"
    ARROW = "arrow"
    ADD_TEXT = "add_text"
    EDIT_TEXT = "edit_text"
    WHITEOUT = "whiteout"
    IMAGE = "image"
    STAMP = "stamp"
    OBJECTS = "objects"


TOOL_HINTS = {
    Tool.SELECT: "Seleziona testo trascinando · clicca un'annotazione per spostarla (Canc per eliminarla) · clicca un campo per compilarlo",
    Tool.HAND: "Trascina per scorrere il documento",
    Tool.HIGHLIGHT: "Trascina sul testo da evidenziare",
    Tool.UNDERLINE: "Trascina sul testo da sottolineare",
    Tool.STRIKE: "Trascina sul testo da barrare",
    Tool.NOTE: "Clicca dove vuoi inserire la nota",
    Tool.TEXTBOX: "Clicca o trascina un riquadro per la casella di testo",
    Tool.INK: "Disegna a mano libera tenendo premuto il tasto sinistro",
    Tool.RECT: "Trascina per disegnare un rettangolo",
    Tool.ELLIPSE: "Trascina per disegnare un'ellisse",
    Tool.ARROW: "Trascina per disegnare una freccia",
    Tool.ADD_TEXT: "Clicca dove vuoi scrivere il testo (diventa parte della pagina)",
    Tool.EDIT_TEXT: "Clicca su una riga per modificarla · trascinala per spostarla (Maiusc = solo orizzontale/verticale)",
    Tool.WHITEOUT: "Trascina un riquadro: il contenuto sotto viene cancellato",
    Tool.IMAGE: "Clicca per posizionare (oppure trascina un riquadro per scegliere la dimensione) · Esc per annullare",
    Tool.STAMP: "Clicca dove vuoi applicare il timbro · Esc per annullare",
    Tool.OBJECTS: "Clicca su sfondi, riquadri, righe o immagini: trascina per spostare, maniglie per ridimensionare · "
                  "doppio clic = colore · tasto destro = altre opzioni · Canc = elimina",
}

MARKUP_TOOLS = {Tool.HIGHLIGHT, Tool.UNDERLINE, Tool.STRIKE}
RECT_TOOLS = {Tool.TEXTBOX, Tool.RECT, Tool.ELLIPSE, Tool.WHITEOUT, Tool.ARROW, Tool.IMAGE}
CLICK_TOOLS = {Tool.NOTE, Tool.ADD_TEXT, Tool.STAMP, Tool.EDIT_TEXT}
SKIP_ANNOTS = {fitz.PDF_ANNOT_LINK, fitz.PDF_ANNOT_WIDGET, fitz.PDF_ANNOT_POPUP}
TEXT_ANNOTS = {fitz.PDF_ANNOT_FREE_TEXT, fitz.PDF_ANNOT_TEXT}
FIELD_TYPES = {fitz.PDF_WIDGET_TYPE_TEXT, fitz.PDF_WIDGET_TYPE_CHECKBOX, fitz.PDF_WIDGET_TYPE_RADIOBUTTON,
               fitz.PDF_WIDGET_TYPE_COMBOBOX, fitz.PDF_WIDGET_TYPE_LISTBOX}
STAMP_FONT_SIZE = 20


def _rotate_for_dir(direction):
    """Angolo (0/90/180/270) per insert_text da una direzione di riga, o None se obliqua."""
    dx, dy = direction
    angle = math.degrees(math.atan2(-dy, dx)) % 360
    snapped = round(angle / 90.0) * 90 % 360
    diff = min(abs(angle - snapped), 360 - abs(angle - snapped))
    return int(snapped) if diff < 1.0 else None


def _fit_rect(target: QRectF, w, h):
    if w <= 0 or h <= 0:
        return target
    s = min(target.width() / w, target.height() / h)
    return QRectF(target.center().x() - w * s / 2, target.center().y() - h * s / 2, w * s, h * s)


class PageItem(QGraphicsItem):
    def __init__(self, view, pno, w, h):
        super().__init__()
        self.view = view
        self.pno = pno
        self.w = w
        self.h = h
        self.pixmap = None
        self.pix_scale = 0.0
        self.pix_rev = -1

    def set_size(self, w, h):
        if (w, h) != (self.w, self.h):
            self.prepareGeometryChange()
            self.w, self.h = w, h
            self.pixmap = None
            self.pix_rev = -1

    def boundingRect(self):
        return QRectF(-2, -2, self.w + 6, self.h + 7)

    def paint(self, p, option, widget=None):
        p.fillRect(QRectF(1.5, 2.5, self.w, self.h), QColor(15, 23, 42, 35))
        p.fillRect(QRectF(0, 0, self.w, self.h), QColor("white"))
        if self.pixmap is not None:
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            p.drawPixmap(QRectF(0, 0, self.w, self.h), self.pixmap, QRectF(self.pixmap.rect()))
        self.view.paint_overlays(self, p)
        self.view.need_render(self)


class PdfView(QGraphicsView):
    currentPageChanged = Signal(int)
    zoomChanged = Signal(float)
    toolChanged = Signal(object)
    message = Signal(str)
    selectionChanged = Signal(bool)

    def __init__(self, pdf, parent=None):
        super().__init__(parent)
        self.pdf = pdf
        self.setScene(QGraphicsScene(self))
        self.setBackgroundBrush(QColor("#e2e8f0"))
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
                            | QPainter.RenderHint.TextAntialiasing)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.SmartViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.pages = []
        self._ys = []
        self._maxw = 1.0
        self.zoom = 1.0
        self.fit_mode = "width"
        self.tool = Tool.SELECT

        # impostazioni strumenti
        self.markup_color = {Tool.HIGHLIGHT: QColor("#fde047"), Tool.UNDERLINE: QColor("#2563eb"),
                             Tool.STRIKE: QColor("#dc2626")}
        self.draw_color = QColor("#dc2626")
        self.draw_width = 2.0
        self.fill_shapes = False
        self.text_color = QColor("#0f172a")
        self.text_size = 12.0
        self.text_family = "sans"
        self.show_fields = True

        # cache (per revisione del documento)
        self._page_cache = {}
        self._words = {}
        self._lines = {}
        self._widgets = {}
        self._annots = {}
        self._links = {}
        self._objects = {}

        # stato interazione
        self.sel = None
        self.search_hits = {}
        self.search_current = None
        self.hover_line = None
        self.sel_annot = None
        self.sel_obj = None         # (pno, props) oggetto grafico selezionato
        self.hover_obj = None
        self.drag = None
        self.pending_image = None   # (QImage, bytes, is_signature)
        self.pending_stamp = None   # (testo, QColor)
        self.ghost = None           # (pno, QPointF)
        self._pan = None
        self._field_editor = None
        self._current = 0
        self._reset_pending = False
        self._last_zoom = 0.0

        self._render_queue = set()
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.timeout.connect(self._render_next)

        self.verticalScrollBar().valueChanged.connect(self._on_scrolled)
        self.horizontalScrollBar().valueChanged.connect(lambda _: self._close_field_editor(True))
        pdf.changed.connect(self._on_doc_changed)

    # ================================================================ dati pagina
    def page(self, pno):
        pg = self._page_cache.get(pno)
        if pg is None:
            pg = self.pdf.doc[pno]
            self._page_cache[pno] = pg
        return pg

    def words(self, pno):
        if pno not in self._words:
            self._words[pno] = self.page(pno).get_text("words")
        return self._words[pno]

    def text_lines(self, pno):
        if pno not in self._lines:
            lines = []
            flags = fitz.TEXT_PRESERVE_WHITESPACE | fitz.TEXT_PRESERVE_LIGATURES | fitz.TEXT_MEDIABOX_CLIP
            for block in self.page(pno).get_text("dict", flags=flags)["blocks"]:
                if block.get("type", 0) != 0:
                    continue
                for line in block["lines"]:
                    text = "".join(s["text"] for s in line["spans"])
                    if text.strip():
                        lines.append(dict(bbox=fitz.Rect(line["bbox"]), dir=line["dir"], spans=line["spans"], text=text))
            self._lines[pno] = lines
        return self._lines[pno]

    def widget_rects(self, pno):
        if pno not in self._widgets:
            try:
                self._widgets[pno] = [(fitz.Rect(w.rect), w.field_type, w.xref) for w in self.page(pno).widgets()]
            except Exception:
                self._widgets[pno] = []
        return self._widgets[pno]

    def annot_list(self, pno):
        if pno not in self._annots:
            items = []
            try:
                for a in self.page(pno).annots():
                    t = a.type[0]
                    if t in SKIP_ANNOTS:
                        continue
                    items.append(dict(pno=pno, xref=a.xref, rect=fitz.Rect(a.rect), type=t, name=a.type[1]))
            except Exception:
                pass
            self._annots[pno] = items
        return self._annots[pno]

    def page_objects(self, pno):
        if pno not in self._objects:
            self._objects[pno] = tko.list_objects(self.page(pno))
        return self._objects[pno]

    def links(self, pno):
        if pno not in self._links:
            try:
                self._links[pno] = self.page(pno).get_links()
            except Exception:
                self._links[pno] = []
        return self._links[pno]

    # ================================================================ documento
    def _on_doc_changed(self, structure):
        self._close_field_editor(False)
        self._page_cache.clear()
        self._words.clear()
        self._lines.clear()
        self._widgets.clear()
        self._annots.clear()
        self._links.clear()
        self._objects.clear()
        self.sel_obj = None
        self.hover_obj = None
        self.sel = None
        self.hover_line = None
        self.sel_annot = None
        self.drag = None
        if structure or len(self.pages) != self.pdf.page_count:
            self.search_hits = {}
            self.search_current = None
            self.rebuild()
        else:
            for it in self.pages:
                it.update()
        self.selectionChanged.emit(False)

    def rebuild(self):
        scene = self.scene()
        n = self.pdf.page_count
        cur, off = self._current, self._offset_in_current()
        if self._reset_pending:
            cur, off = 0, 0.0
            self._reset_pending = False
        while len(self.pages) > n:
            scene.removeItem(self.pages.pop())
        y = 0.0
        maxw = 1.0
        for i in range(n):
            r = self.page(i).rect
            if i < len(self.pages):
                it = self.pages[i]
                it.set_size(r.width, r.height)
            else:
                it = PageItem(self, i, r.width, r.height)
                scene.addItem(it)
                self.pages.append(it)
            it.setPos(-r.width / 2, y)
            it.update()
            y += r.height + PAGE_GAP
            maxw = max(maxw, r.width)
        self._maxw = maxw
        self._ys = [it.y() for it in self.pages]
        if n:
            scene.setSceneRect(QRectF(-maxw / 2 - SIDE_MARGIN, -PAGE_GAP * 2, maxw + 2 * SIDE_MARGIN, y + PAGE_GAP * 3))
            if self.fit_mode:
                self.apply_fit()
            self.go_to_page(min(cur, n - 1), off)
        else:
            scene.setSceneRect(QRectF(0, 0, 1, 1))
            self._current = 0

    # ================================================================ zoom e navigazione
    def set_zoom(self, z, keep_fit=False, anchor_mouse=False):
        z = max(0.1, min(8.0, z))
        if not keep_fit:
            self.fit_mode = None
        old = self.transform().m11() or 1.0
        target = z * PT_TO_PX
        if abs(target - old) > 1e-6:
            self._close_field_editor(True)
            self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse if anchor_mouse
                                         else QGraphicsView.ViewportAnchor.AnchorViewCenter)
            self.scale(target / old, target / old)
            self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
            self._last_zoom = time.monotonic()
        self.zoom = z
        self.zoomChanged.emit(z)

    def set_fit(self, mode):
        self.fit_mode = mode
        self.apply_fit()
        if self.pages:
            self.go_to_page(self._current)

    def apply_fit(self):
        if not self.pages or not self.fit_mode:
            return
        vw = max(50, self.viewport().width() - 4)
        vh = max(50, self.viewport().height() - 24)
        cur = self.pages[min(self._current, len(self.pages) - 1)]
        if self.fit_mode == "width":
            z = vw / ((self._maxw + 2 * SIDE_MARGIN) * PT_TO_PX)
        else:
            z = min(vw / ((cur.w + 2 * SIDE_MARGIN) * PT_TO_PX), vh / ((cur.h + PAGE_GAP * 2) * PT_TO_PX))
        if abs(z - self.zoom) < 1e-4 and abs(self.transform().m11() - z * PT_TO_PX) < 1e-4:
            return
        page, off = self._current, self._offset_in_current()
        self.set_zoom(z, keep_fit=True)
        self.go_to_page(page, off)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.fit_mode:
            QTimer.singleShot(0, self.apply_fit)

    def viewportEvent(self, e):
        # pinch sul trackpad (macOS e alcuni touchpad Windows)
        if e.type() == QEvent.Type.NativeGesture and e.gestureType() == Qt.NativeGestureType.ZoomNativeGesture:
            self.set_zoom(self.zoom * (1.0 + e.value()), anchor_mouse=True)
            return True
        return super().viewportEvent(e)

    def wheelEvent(self, e):
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
            self.set_zoom(self.zoom * factor, anchor_mouse=True)
            e.accept()
            return
        super().wheelEvent(e)

    def visible_range(self):
        if not self.pages:
            return 0, -1
        r = self.mapToScene(self.viewport().rect()).boundingRect()
        a = max(0, bisect_right(self._ys, r.top()) - 1)
        b = max(0, bisect_right(self._ys, r.bottom()) - 1)
        return a, min(b, len(self.pages) - 1)

    def current_page(self):
        return self._current

    def _offset_in_current(self):
        if not self.pages or self._current >= len(self.pages):
            return 0.0
        top = self.mapToScene(QPoint(0, 0)).y()
        return top - self.pages[self._current].y()

    def go_to_page(self, pno, offset=0.0):
        if not self.pages:
            return
        pno = max(0, min(pno, len(self.pages) - 1))
        it = self.pages[pno]
        s = self.transform().m11() or 1.0
        vh = self.viewport().height() / s
        cx = self.mapToScene(self.viewport().rect().center()).x()
        self.centerOn(QPointF(cx, it.y() + offset + vh / 2 - (PAGE_GAP / 2 if offset == 0 else 0)))
        if pno != self._current:
            self._current = pno
            self.currentPageChanged.emit(pno)

    def _on_scrolled(self, _=None):
        self._close_field_editor(True)
        if not self.pages:
            return
        pt = self.mapToScene(QPoint(self.viewport().width() // 2, self.viewport().height() // 3))
        idx = max(0, min(bisect_right(self._ys, pt.y()) - 1, len(self.pages) - 1))
        if idx != self._current:
            self._current = idx
            self.currentPageChanged.emit(idx)
        a, b = self.visible_range()
        for it in self.pages:
            if it.pixmap is not None and (it.pno < a - 3 or it.pno > b + 3):
                it.pixmap = None
                it.pix_rev = -1

    # ================================================================ rendering
    def wanted_scale(self, item):
        s = self.transform().m11() * self.devicePixelRatioF()
        return min(s, math.sqrt(MAX_PIXELS / max(1.0, item.w * item.h)))

    def need_render(self, item):
        if self.pdf.doc is None:
            return
        ws = self.wanted_scale(item)
        if item.pix_rev != self.pdf.revision or abs(item.pix_scale - ws) > ws * 0.02:
            self._render_queue.add(item.pno)
            if not self._render_timer.isActive():
                zooming = time.monotonic() - self._last_zoom < 0.18
                self._render_timer.start(180 if zooming else 0)

    def _render_next(self):
        if not self.pages or self.pdf.doc is None:
            self._render_queue.clear()
            return
        if time.monotonic() - self._last_zoom < 0.15:
            self._render_timer.start(150)
            return
        a, b = self.visible_range()
        todo = [p for p in self._render_queue if a - 1 <= p <= b + 1 and p < len(self.pages)]
        self._render_queue = set(todo)
        if not todo:
            return
        pno = min(todo, key=lambda p: abs(p - self._current))
        self._render_queue.discard(pno)
        it = self.pages[pno]
        ws = self.wanted_scale(it)
        try:
            pix = self.page(pno).get_pixmap(matrix=fitz.Matrix(ws, ws), alpha=False, annots=True)
            it.pixmap = QPixmap.fromImage(pix_to_qimage(pix))
        except Exception:
            pass
        it.pix_scale = ws
        it.pix_rev = self.pdf.revision
        it.update()
        if self._render_queue:
            self._render_timer.start(0)

    # ================================================================ overlay
    def paint_overlays(self, item, p):
        if self.pdf.doc is None or item.pno >= self.pdf.page_count:
            return
        pno = item.pno
        page = self.page(pno)

        def vr(r):
            return frect_to_qrect(to_view_rect(page, r))

        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self.show_fields:
            p.setPen(QPen(QColor(59, 130, 246, 130), 0.6))
            p.setBrush(QColor(59, 130, 246, 28))
            for rect, ftype, _ in self.widget_rects(pno):
                if ftype in FIELD_TYPES:
                    p.drawRect(vr(rect))

        hits = self.search_hits.get(pno)
        if hits:
            p.setPen(Qt.PenStyle.NoPen)
            for i, r in enumerate(hits):
                cur = self.search_current == (pno, i)
                p.setBrush(QColor(249, 115, 22, 130) if cur else QColor(250, 204, 21, 95))
                p.drawRect(vr(r))

        if self.sel and self.sel["pno"] == pno:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(37, 99, 235, 70))
            for r in self.sel["lines"]:
                p.drawRect(vr(r))

        if self.tool == Tool.EDIT_TEXT:
            p.setPen(QPen(QColor(225, 29, 72, 80), 0.5, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            for line in self.text_lines(pno):
                p.drawRect(vr(line["bbox"]))
            if self.hover_line and self.hover_line[0] == pno:
                p.setPen(QPen(QColor(ACCENT), 1.0))
                p.setBrush(QColor(225, 29, 72, 35))
                p.drawRect(vr(self.hover_line[1]["bbox"]))

        d = self.drag if self.drag and self.drag["pno"] == pno else None
        if self.tool == Tool.OBJECTS:
            self._paint_objects(pno, page, p, d)
            if d and d["kind"] in ("objmove", "objresize"):
                d = None
        if self.sel_annot and self.sel_annot["pno"] == pno:
            r = vr(self.sel_annot["rect"]).adjusted(-3, -3, 3, 3)
            if d and d["kind"] == "move":
                r.translate(d["cur"] - d["start"])
            p.setPen(QPen(QColor(ACCENT), 1.2, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(r)

        if d and d["kind"] == "textmove":
            r = vr(d["line"]["bbox"])
            p.setPen(QPen(QColor(ACCENT), 0.6, Qt.PenStyle.DashLine))
            p.setBrush(QColor(225, 29, 72, 25))
            p.drawRect(r)
            moved = r.translated(self._text_move_delta(d))
            p.setPen(QPen(QColor(ACCENT), 1.2))
            p.setBrush(QColor(225, 29, 72, 55))
            p.drawRect(moved)
            d = None
        if d:
            color = QColor(self.draw_color)
            pen = QPen(color, self.draw_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            if d["kind"] == "ink":
                p.setPen(pen)
                p.drawPolyline(QPolygonF(d["points"]))
            elif d["kind"] == "rect":
                r = QRectF(d["start"], d["cur"]).normalized()
                dashed = QPen(QColor(ACCENT), 1.0, Qt.PenStyle.DashLine)
                if self.tool == Tool.ARROW:
                    p.setPen(pen)
                    p.drawLine(d["start"], d["cur"])
                elif self.tool in (Tool.RECT, Tool.ELLIPSE):
                    p.setPen(pen)
                    fill = QColor(color)
                    fill.setAlpha(60)
                    p.setBrush(fill if self.fill_shapes else Qt.BrushStyle.NoBrush)
                    (p.drawEllipse if self.tool == Tool.ELLIPSE else p.drawRect)(r)
                elif self.tool == Tool.WHITEOUT:
                    p.setPen(dashed)
                    p.setBrush(QColor(255, 255, 255, 235))
                    p.drawRect(r)
                elif self.tool == Tool.IMAGE and self.pending_image:
                    img = self.pending_image[0]
                    p.setOpacity(0.75)
                    p.drawImage(_fit_rect(r, img.width(), img.height()), img)
                    p.setOpacity(1.0)
                    p.setPen(dashed)
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawRect(r)
                else:
                    p.setPen(dashed)
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawRect(r)

        if self.ghost and self.ghost[0] == pno and not d:
            pos = self.ghost[1]
            if self.tool == Tool.IMAGE and self.pending_image:
                img = self.pending_image[0]
                r = self._default_image_rect(pos)
                p.setOpacity(0.6)
                p.drawImage(r, img)
                p.setOpacity(1.0)
                p.setPen(QPen(QColor(ACCENT), 0.8, Qt.PenStyle.DashLine))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(r)
            elif self.tool == Tool.STAMP and self.pending_stamp:
                text, color = self.pending_stamp
                r = self._stamp_rect(pos, text)
                p.setOpacity(0.7)
                p.setPen(QPen(color, 2.5))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(r)
                font = QFont("Arial")
                font.setPixelSize(STAMP_FONT_SIZE)
                p.setFont(font)
                p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)
                p.setOpacity(1.0)

    # ================================================================ oggetti grafici
    def _obj_view_rect(self, page, o):
        return frect_to_qrect(to_view_rect(page, tko.bbox(o)))

    def _handle_size(self):
        return 5.0 / max(0.2, self.transform().m11())

    def _obj_handles(self, page, o):
        """Maniglie in coordinate vista: angoli per riquadri/immagini, estremi per le righe."""
        if o["K"] == "line":
            pts = [fitz.Point(o["X1"], o["Y1"]) * page.rotation_matrix, fitz.Point(o["X2"], o["Y2"]) * page.rotation_matrix]
            return [QPointF(pt.x, pt.y) for pt in pts]
        r = self._obj_view_rect(page, o)
        return [r.topLeft(), r.topRight(), r.bottomRight(), r.bottomLeft()]

    def _paint_objects(self, pno, page, p, d):
        hs = self._handle_size()
        pen_w = 1.6 / max(0.2, self.transform().m11())
        if self.hover_obj and self.hover_obj[0] == pno and not (self.sel_obj and self.sel_obj[1] is self.hover_obj[1]):
            p.setPen(QPen(QColor(37, 99, 235, 200), pen_w, Qt.PenStyle.DashLine))
            p.setBrush(QColor(37, 99, 235, 18))
            p.drawRect(self._obj_view_rect(page, self.hover_obj[1]))
        if not (self.sel_obj and self.sel_obj[0] == pno):
            return
        o = self.sel_obj[1]
        preview = self._obj_preview(pno, o, d) if d and d["kind"] in ("objmove", "objresize") else o
        if preview is not o:
            p.setPen(QPen(QColor(ACCENT), pen_w, Qt.PenStyle.DashLine))
            p.setBrush(QColor(225, 29, 72, 30))
            if o["K"] == "line":
                a, b = self._obj_handles(page, preview)
                p.drawLine(a, b)
            else:
                p.drawRect(self._obj_view_rect(page, preview))
        p.setPen(QPen(QColor(ACCENT), pen_w))
        p.setBrush(Qt.BrushStyle.NoBrush)
        if o["K"] != "line":
            p.drawRect(self._obj_view_rect(page, o))
        p.setBrush(QColor("white"))
        for pt in self._obj_handles(page, preview):
            p.drawRect(QRectF(pt.x() - hs, pt.y() - hs, hs * 2, hs * 2))

    def _obj_at(self, pno, pu):
        """Oggetto più in alto sotto il punto (righe e immagini hanno la precedenza sugli sfondi)."""
        hits = [o for o in self.page_objects(pno) if tko.bbox(o).contains(pu)]
        if not hits:
            return None
        small = [o for o in hits if o["K"] in ("line", "img")]
        return small[-1] if small else hits[-1]

    def _obj_handle_at(self, pno, lp):
        if not (self.sel_obj and self.sel_obj[0] == pno):
            return None
        hs = self._handle_size() * 1.8
        for i, pt in enumerate(self._obj_handles(self.page(pno), self.sel_obj[1])):
            if abs(pt.x() - lp.x()) <= hs and abs(pt.y() - lp.y()) <= hs:
                return i
        return None

    def _obj_preview(self, pno, o, d):
        """Proprietà dell'oggetto durante il trascinamento (senza toccare il documento)."""
        p0, p1 = self._unrot(pno, d["start"]), self._unrot(pno, d["cur"])
        shift = bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier)
        if d["kind"] == "objmove":
            dx, dy = p1.x - p0.x, p1.y - p0.y
            if shift:
                if abs(dx) > abs(dy):
                    dy = 0
                else:
                    dx = 0
            return dict(o, **tko.moved(o, dx, dy))
        if o["K"] == "line":
            keys = ("X1", "Y1") if d["handle"] == 0 else ("X2", "Y2")
            return dict(o, **{keys[0]: p1.x, keys[1]: p1.y})
        r = tko.bbox(o)
        corners = [fitz.Point(r.x0, r.y0), fitz.Point(r.x1, r.y0), fitz.Point(r.x1, r.y1), fitz.Point(r.x0, r.y1)]
        grabbed = min(range(4), key=lambda i: abs(corners[i].x - p0.x) + abs(corners[i].y - p0.y))
        fixed = corners[(grabbed + 2) % 4]
        x0, x1 = sorted((fixed.x, p1.x))
        y0, y1 = sorted((fixed.y, p1.y))
        w, hh = max(2.0, x1 - x0), max(2.0, y1 - y0)
        if o["K"] == "img" and not shift:  # le immagini mantengono le proporzioni (Maiusc = libere)
            ratio = o["W"] / max(0.01, o["H"])
            if w / hh > ratio:
                w = hh * ratio
            else:
                hh = w / ratio
            x0 = fixed.x - w if p1.x < fixed.x else fixed.x
            y0 = fixed.y - hh if p1.y < fixed.y else fixed.y
        return dict(o, X=x0, Y=y0, W=w, H=hh)

    def _obj_edit(self, pno, obj_id, fn, message=""):
        with self.pdf.edit(pages=[pno]):
            page = self.pdf.doc[pno]
            result = fn(page)
        new_id = result if isinstance(result, int) else obj_id
        for o in self.page_objects(pno):
            if o["Id"] == new_id:
                self.sel_obj = (pno, o)
                break
        if message:
            self.message.emit(message)
        if pno < len(self.pages):
            self.pages[pno].update()

    def _finish_obj_drag(self, d):
        if not self.sel_obj or (d["cur"] - d["start"]).manhattanLength() < 2:
            return
        pno, o = self.sel_obj
        new = self._obj_preview(pno, o, d)
        keys = ("X1", "Y1", "X2", "Y2") if o["K"] == "line" else ("X", "Y", "W", "H")
        changes = {k: new[k] for k in keys}
        self._obj_edit(pno, o["Id"], lambda page: tko.update(page, o["Id"], changes),
                       "↔️ Oggetto spostato" if d["kind"] == "objmove" else "⤡ Oggetto ridimensionato")

    def object_color(self, which):
        """which: 'fill' o 'stroke'. Il riempimento di una zona di sfondo divisa in più pezzi cambia tutta la zona."""
        if not self.sel_obj:
            return
        pno, o = self.sel_obj
        key = "F" if which == "fill" else "S"
        current = o.get(key) or ([1, 1, 1] if key == "F" else [0, 0, 0])
        start = QColor.fromRgbF(*[min(1.0, max(0.0, v)) for v in current[:3]])
        c = QColorDialog.getColor(start, self, "Colore di riempimento" if key == "F" else "Colore del bordo")
        if not c.isValid():
            return
        rgb = [round(c.redF(), 3), round(c.greenF(), 3), round(c.blueF(), 3)]
        group = o.get("G")
        ids = [x["Id"] for x in self.page_objects(pno) if group and x.get("G") == group] if key == "F" else []
        ids = ids or [o["Id"]]
        changes = {key: rgb}
        if key == "S" and o["K"] == "rect" and not o.get("SW"):
            changes["SW"] = 2.0

        def fn(page):
            for i in ids:
                tko.update(page, i, changes)
        self._obj_edit(pno, o["Id"], fn, "🎨 Colore cambiato")

    def object_stroke_width(self):
        if not self.sel_obj:
            return
        pno, o = self.sel_obj
        value, ok = QInputDialog.getDouble(self, APP_TITLE, "Spessore in punti (0 = nessun bordo):",
                                           float(o.get("SW") or (1.0 if o["K"] == "line" else 0.0)), 0.0, 100.0, 1)
        if not ok:
            return
        if o["K"] == "line":
            changes = dict(SW=max(0.1, value))
        else:
            changes = dict(SW=value if value > 0 else None, S=(o.get("S") or [0, 0, 0]) if value > 0 else None)
        self._obj_edit(pno, o["Id"], lambda page: tko.update(page, o["Id"], changes), "📏 Spessore aggiornato")

    def object_no_fill(self):
        if self.sel_obj:
            pno, o = self.sel_obj
            changes = dict(F=None)
            if not o.get("S"):
                changes.update(S=[0, 0, 0], SW=1.0)
            self._obj_edit(pno, o["Id"], lambda page: tko.update(page, o["Id"], changes), "Riempimento tolto")

    def object_restack(self, where):
        if self.sel_obj:
            pno, o = self.sel_obj
            self._obj_edit(pno, o["Id"], lambda page: tko.restack(page, o["Id"], where),
                           "⬆️ Portato in primo piano" if where == "top" else "⬇️ Portato sullo sfondo")

    def object_duplicate(self):
        if self.sel_obj:
            pno, o = self.sel_obj
            self._obj_edit(pno, o["Id"], lambda page: tko.duplicate(page, o["Id"]), "📑 Oggetto duplicato")

    def object_delete(self):
        if not self.sel_obj:
            return
        pno, o = self.sel_obj
        with self.pdf.edit(pages=[pno]):
            tko.delete(self.pdf.doc[pno], o["Id"])
        self.sel_obj = None
        self.message.emit("🗑️ Oggetto eliminato · Ctrl+Z per annullare")

    def object_menu(self, menu):
        pno, o = self.sel_obj
        kind = {"rect": "Riquadro / sfondo", "line": "Riga", "img": "Immagine"}[o["K"]]
        title = menu.addAction(f"🧩 {kind}")
        title.setEnabled(False)
        if o["K"] == "rect":
            menu.addAction("🎨 Colore di riempimento…", lambda: self.object_color("fill"))
            if o.get("F"):
                menu.addAction("Nessun riempimento", self.object_no_fill)
        if o["K"] in ("rect", "line"):
            menu.addAction("🖌️ Colore del bordo…" if o["K"] == "rect" else "🎨 Colore della riga…",
                           lambda: self.object_color("stroke"))
            menu.addAction("📏 Spessore…", self.object_stroke_width)
        menu.addAction("⬆️ Porta in primo piano", lambda: self.object_restack("top"))
        menu.addAction("⬇️ Porta sullo sfondo", lambda: self.object_restack("bottom"))
        menu.addAction("📑 Duplica", self.object_duplicate)
        menu.addAction("🗑️ Elimina", self.object_delete)
        menu.addSeparator()

    # ================================================================ strumenti
    def set_tool(self, tool):
        self._close_field_editor(True)
        if tool != Tool.IMAGE:
            self.pending_image = None
        if tool != Tool.STAMP:
            self.pending_stamp = None
        self.tool = tool
        self.drag = None
        self.hover_line = None
        if tool != Tool.OBJECTS:
            self.sel_obj = None
            self.hover_obj = None
        self.ghost = None
        cursors = {Tool.HAND: Qt.CursorShape.OpenHandCursor, Tool.SELECT: Qt.CursorShape.ArrowCursor,
                   Tool.EDIT_TEXT: Qt.CursorShape.IBeamCursor, Tool.OBJECTS: Qt.CursorShape.ArrowCursor}
        if tool in MARKUP_TOOLS:
            self.viewport().setCursor(Qt.CursorShape.IBeamCursor)
        else:
            self.viewport().setCursor(cursors.get(tool, Qt.CursorShape.CrossCursor))
        for it in self.pages:
            it.update()
        self.toolChanged.emit(tool)
        self.message.emit(TOOL_HINTS.get(tool, ""))

    def start_image_placement(self, qimage, data, kind="image"):
        """kind: 'image', 'signature' oppure 'check' (la spunta resta attiva per più clic)."""
        self.set_tool(Tool.IMAGE)
        self.pending_image = (qimage, data, kind)

    def start_stamp(self, text, color):
        self.set_tool(Tool.STAMP)
        self.pending_stamp = (text, QColor(color))

    def reset_position(self):
        self._current = 0
        self._reset_pending = True
        self.fit_mode = "width"

    def _default_image_rect(self, center):
        img, _, kind = self.pending_image
        w = {"signature": 150.0, "check": 16.0}.get(kind, 220.0)
        h = w * img.height() / max(1, img.width())
        return QRectF(center.x() - w / 2, center.y() - h / 2, w, h)

    def _stamp_rect(self, center, text):
        lines = text.split("\n")
        w = max(fitz.get_text_length(l, fontname="helv", fontsize=STAMP_FONT_SIZE) for l in lines) + 26
        h = len(lines) * STAMP_FONT_SIZE * 1.2 + 5
        return QRectF(center.x() - w / 2, center.y() - h / 2, w, h)

    # ================================================================ hit test
    def _hit(self, pos, clamp_pno=None):
        sp = self.mapToScene(pos)
        if clamp_pno is not None and clamp_pno < len(self.pages):
            it = self.pages[clamp_pno]
            return it, QPointF(min(max(sp.x() - it.x(), 0.0), it.w), min(max(sp.y() - it.y(), 0.0), it.h))
        idx = bisect_right(self._ys, sp.y()) - 1
        if 0 <= idx < len(self.pages):
            it = self.pages[idx]
            lx, ly = sp.x() - it.x(), sp.y() - it.y()
            if 0 <= lx <= it.w and 0 <= ly <= it.h:
                return it, QPointF(lx, ly)
        return None, None

    def _unrot(self, pno, lp):
        return to_unrot_point(self.page(pno), lp.x(), lp.y())

    def _annot_at(self, pno, pu):
        for a in reversed(self.annot_list(pno)):
            r = a["rect"]
            if fitz.Rect(r.x0 - 3, r.y0 - 3, r.x1 + 3, r.y1 + 3).contains(pu):
                return a
        return None

    def _link_at(self, pno, pu):
        for link in self.links(pno):
            if fitz.Rect(link["from"]).contains(pu):
                return link
        return None

    def _widget_at(self, pno, pu):
        for rect, ftype, xref in self.widget_rects(pno):
            if ftype in FIELD_TYPES or ftype == fitz.PDF_WIDGET_TYPE_SIGNATURE:
                if rect.contains(pu):
                    return xref
        return None

    def _word_index_at(self, pno, pu):
        for i, w in enumerate(self.words(pno)):
            if fitz.Rect(w[:4]).contains(pu):
                return i
        return None

    def _line_at(self, pno, pu):
        for line in self.text_lines(pno):
            if line["bbox"].contains(pu):
                return line
        return None

    # ================================================================ selezione testo
    def _nearest_word(self, words, pt):
        best, best_d = None, float("inf")
        for i, w in enumerate(words):
            r = fitz.Rect(w[:4])
            if r.contains(pt):
                return i
            dx = max(r.x0 - pt.x, 0, pt.x - r.x1)
            dy = max(r.y0 - pt.y, 0, pt.y - r.y1)
            dist = dx * dx + dy * dy * 4
            if dist < best_d:
                best, best_d = i, dist
        return best

    def _select_range(self, pno, i, j):
        words = self.words(pno)
        lo, hi = sorted((i, j))
        chosen = words[lo:hi + 1]
        lines = {}
        for w in chosen:
            key = (w[5], w[6])
            r = fitz.Rect(w[:4])
            lines[key] = lines[key] | r if key in lines else r
        self.sel = dict(pno=pno, words=chosen, lines=list(lines.values()))
        self.selectionChanged.emit(True)

    def _set_sel(self, pno, a, b):
        words = self.words(pno)
        if not words:
            return
        i, j = self._nearest_word(words, a), self._nearest_word(words, b)
        if i is not None and j is not None:
            self._select_range(pno, i, j)

    def clear_selection(self):
        had = self.sel is not None or self.sel_annot is not None
        self.sel = None
        self.sel_annot = None
        if had:
            for it in self.pages:
                it.update()
        self.selectionChanged.emit(False)

    def has_selection(self):
        return bool(self.sel)

    def selected_text(self):
        if not self.sel:
            return ""
        out, last = [], None
        for w in self.sel["words"]:
            key = (w[5], w[6])
            if last is None:
                out.append(w[4])
            elif key != last:
                out.append("\n" + w[4])
            else:
                out.append(" " + w[4])
            last = key
        return "".join(out)

    def copy_selection(self):
        text = self.selected_text()
        if text:
            QApplication.clipboard().setText(text)
            self.message.emit("📋 Testo copiato negli appunti")

    def select_all_page(self, pno=None):
        if not self.pages:
            return
        pno = self._current if pno is None else pno
        words = self.words(pno)
        if words:
            self._select_range(pno, 0, len(words) - 1)
            self.pages[pno].update()

    # ================================================================ mouse
    def mousePressEvent(self, e):
        self.setFocus()
        if self.pdf.doc is None or not self.pages:
            return super().mousePressEvent(e)
        pos = e.position().toPoint()
        if e.button() == Qt.MouseButton.MiddleButton or (e.button() == Qt.MouseButton.LeftButton and self.tool == Tool.HAND):
            self._pan = pos
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if e.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(e)
        self._close_field_editor(True)
        it, lp = self._hit(pos)
        if it is None:
            self.clear_selection()
            return
        pno = it.pno
        pu = self._unrot(pno, lp)
        t = self.tool
        if t == Tool.SELECT:
            xref = self._widget_at(pno, pu)
            if xref is not None:
                self.clear_selection()
                self._activate_field(pno, xref)
                return
            a = self._annot_at(pno, pu)
            if a is not None:
                self.sel = None
                self.sel_annot = a
                self.drag = dict(kind="move", pno=pno, start=lp, cur=lp)
                for item in self.pages:
                    item.update()
                return
            self.clear_selection()
            self.drag = dict(kind="select", pno=pno, start=pu, startv=lp, link=self._link_at(pno, pu), moved=False)
        elif t in MARKUP_TOOLS:
            self.clear_selection()
            self.drag = dict(kind="select", pno=pno, start=pu, startv=lp, link=None, moved=False)
        elif t == Tool.INK:
            self.drag = dict(kind="ink", pno=pno, points=[lp])
        elif t in RECT_TOOLS:
            self.drag = dict(kind="rect", pno=pno, start=lp, cur=lp)
        elif t == Tool.OBJECTS:
            handle = self._obj_handle_at(pno, lp)
            if handle is not None:
                self.drag = dict(kind="objresize", pno=pno, start=lp, cur=lp, handle=handle)
                return
            o = self._obj_at(pno, pu)
            prev = self.sel_obj
            self.sel_obj = (pno, o) if o else None
            if o:
                self.drag = dict(kind="objmove", pno=pno, start=lp, cur=lp)
                self.viewport().setCursor(Qt.CursorShape.SizeAllCursor)
            elif not self.page_objects(pno):
                self.message.emit("Questa pagina non ha oggetti grafici modificabili (si creano con «Da foto a PDF»)")
            it.update()
            if prev and prev[0] != pno and prev[0] < len(self.pages):
                self.pages[prev[0]].update()
        elif t == Tool.EDIT_TEXT and self._line_at(pno, pu) is not None:
            self.drag = dict(kind="textmove", pno=pno, start=lp, cur=lp, line=self._line_at(pno, pu))
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
        elif t in CLICK_TOOLS:
            self.drag = dict(kind="click", pno=pno, start=lp, cur=lp)

    def mouseMoveEvent(self, e):
        pos = e.position().toPoint()
        if self._pan is not None:
            delta = pos - self._pan
            self._pan = pos
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            return
        if self.pdf.doc is None or not self.pages:
            return super().mouseMoveEvent(e)
        d = self.drag
        if d:
            vh = self.viewport().height()
            if pos.y() < 24:
                self.verticalScrollBar().setValue(self.verticalScrollBar().value() - 18)
            elif pos.y() > vh - 24:
                self.verticalScrollBar().setValue(self.verticalScrollBar().value() + 18)
            it, lp = self._hit(pos, clamp_pno=d["pno"])
            if d["kind"] == "select":
                if (lp - d["startv"]).manhattanLength() > 3:
                    d["moved"] = True
                if d["moved"]:
                    self._set_sel(d["pno"], d["start"], self._unrot(d["pno"], lp))
            elif d["kind"] == "ink":
                if (lp - d["points"][-1]).manhattanLength() >= 0.7:
                    d["points"].append(lp)
            else:
                d["cur"] = lp
            it.update()
            return
        it, lp = self._hit(pos)
        self._hover(it, lp)

    def _hover(self, it, lp):
        vp = self.viewport()
        t = self.tool
        prev_ghost = self.ghost
        if t in (Tool.IMAGE, Tool.STAMP):
            self.ghost = (it.pno, lp) if it else None
            for g in (prev_ghost, self.ghost):
                if g and g[0] < len(self.pages):
                    self.pages[g[0]].update()
            vp.setCursor(Qt.CursorShape.CrossCursor)
            return
        if it is None:
            if t == Tool.SELECT:
                vp.setCursor(Qt.CursorShape.ArrowCursor)
            if self.hover_line:
                old = self.hover_line[0]
                self.hover_line = None
                self.pages[old].update()
            return
        pno = it.pno
        pu = self._unrot(pno, lp)
        if t == Tool.SELECT:
            if self._widget_at(pno, pu) is not None or self._link_at(pno, pu) is not None:
                vp.setCursor(Qt.CursorShape.PointingHandCursor)
            elif self._annot_at(pno, pu) is not None:
                vp.setCursor(Qt.CursorShape.SizeAllCursor)
            elif self._word_index_at(pno, pu) is not None:
                vp.setCursor(Qt.CursorShape.IBeamCursor)
            else:
                vp.setCursor(Qt.CursorShape.ArrowCursor)
        elif t == Tool.OBJECTS:
            if self._obj_handle_at(pno, lp) is not None:
                vp.setCursor(Qt.CursorShape.SizeFDiagCursor)
                return
            o = self._obj_at(pno, pu)
            new = (pno, o) if o else None
            old = self.hover_obj
            if (old and old[1]) is not (new and new[1]):
                self.hover_obj = new
                for h in (old, new):
                    if h and h[0] < len(self.pages):
                        self.pages[h[0]].update()
            vp.setCursor(Qt.CursorShape.SizeAllCursor if o else Qt.CursorShape.ArrowCursor)
        elif t == Tool.EDIT_TEXT:
            line = self._line_at(pno, pu)
            new = (pno, line) if line else None
            old = self.hover_line
            if (old and old[1]) is not (new and new[1]):
                self.hover_line = new
                for h in (old, new):
                    if h:
                        self.pages[h[0]].update()
            vp.setCursor(Qt.CursorShape.OpenHandCursor if line else Qt.CursorShape.ArrowCursor)

    def leaveEvent(self, e):
        if self.ghost:
            pno = self.ghost[0]
            self.ghost = None
            if pno < len(self.pages):
                self.pages[pno].update()
        super().leaveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._pan is not None:
            self._pan = None
            self.set_tool_cursor()
            return
        d = self.drag
        self.drag = None
        if not d or self.pdf.doc is None:
            return super().mouseReleaseEvent(e)
        pno = d["pno"]
        try:
            if d["kind"] == "select":
                if not d["moved"]:
                    self.clear_selection()
                    if d.get("link"):
                        self._follow_link(d["link"])
                elif self.tool in MARKUP_TOOLS and self.sel:
                    self.apply_markup(self.tool)
            elif d["kind"] == "move":
                self._finish_move(d)
            elif d["kind"] in ("objmove", "objresize"):
                self.set_tool_cursor()
                self._finish_obj_drag(d)
            elif d["kind"] == "ink":
                self._finish_ink(d)
            elif d["kind"] == "rect":
                self._finish_rect(d)
            elif d["kind"] == "click":
                self.click_action(self.tool, pno, d["start"])
            elif d["kind"] == "textmove":
                self.set_tool_cursor()
                delta = self._text_move_delta(d)
                if delta.manhattanLength() < 3:
                    self.edit_line(pno, d["line"])  # semplice clic: modifica
                else:
                    self.move_line(pno, d["line"], delta)
        except Exception as exc:
            QMessageBox.warning(self, APP_TITLE, f"Operazione non riuscita:\n{exc}")
        if pno < len(self.pages):
            self.pages[pno].update()

    def set_tool_cursor(self):
        if self.tool == Tool.HAND:
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
        elif self.tool in (Tool.SELECT, Tool.OBJECTS):
            self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        else:
            self.viewport().setCursor(Qt.CursorShape.CrossCursor)

    def mouseDoubleClickEvent(self, e):
        if self.pdf.doc is not None and self.tool == Tool.OBJECTS and self.sel_obj:
            self.drag = None
            o = self.sel_obj[1]
            if o["K"] == "img":
                self.message.emit("Immagine: trascinala per spostarla, usa le maniglie per ridimensionarla")
            elif o["K"] == "rect" and (o.get("F") or not o.get("S")):
                self.object_color("fill")
            else:
                self.object_color("stroke")
            return
        if self.pdf.doc is None or self.tool != Tool.SELECT:
            return super().mouseDoubleClickEvent(e)
        it, lp = self._hit(e.position().toPoint())
        if it is None:
            return
        pu = self._unrot(it.pno, lp)
        a = self._annot_at(it.pno, pu)
        if a is not None and a["type"] in TEXT_ANNOTS:
            self.drag = None
            self.edit_annot_text(a)
            return
        idx = self._word_index_at(it.pno, pu)
        if idx is not None:
            self._select_range(it.pno, idx, idx)
            it.update()

    def keyPressEvent(self, e):
        key = e.key()
        if key == Qt.Key.Key_Escape:
            if self.drag:
                pno = self.drag["pno"]
                self.drag = None
                self.pages[pno].update()
            elif self.tool != Tool.SELECT:
                self.set_tool(Tool.SELECT)
            else:
                self.clear_selection()
            return
        if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self.tool == Tool.OBJECTS and self.sel_obj:
            self.object_delete()
            return
        if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self.sel_annot:
            self.delete_selected_annot()
            return
        ctrl = e.modifiers() & Qt.KeyboardModifier.ControlModifier
        if key == Qt.Key.Key_C and ctrl:
            self.copy_selection()
            return
        if key == Qt.Key.Key_A and ctrl:
            self.select_all_page()
            return
        if key == Qt.Key.Key_Home and self.pages:
            self.go_to_page(0)
            return
        if key == Qt.Key.Key_End and self.pages:
            self.go_to_page(len(self.pages) - 1)
            return
        super().keyPressEvent(e)

    # ================================================================ azioni
    def apply_markup(self, tool):
        s = self.sel
        if not s:
            return
        pno = s["pno"]
        with self.pdf.edit(pages=[pno]):
            page = self.pdf.doc[pno]
            fn = {Tool.HIGHLIGHT: page.add_highlight_annot, Tool.UNDERLINE: page.add_underline_annot,
                  Tool.STRIKE: page.add_strikeout_annot}[tool]
            annot = fn(s["lines"])
            annot.set_colors(stroke=qcolor_to_rgb(self.markup_color[tool]))
            annot.update()
        self.message.emit({Tool.HIGHLIGHT: "🖍️ Testo evidenziato", Tool.UNDERLINE: "Testo sottolineato",
                           Tool.STRIKE: "Testo barrato"}[tool])

    def _finish_move(self, d):
        a = self.sel_annot
        if not a:
            return
        if (d["cur"] - d["start"]).manhattanLength() < 2:
            return
        pno = d["pno"]
        p0 = self._unrot(pno, d["start"])
        p1 = self._unrot(pno, d["cur"])
        dx, dy = p1.x - p0.x, p1.y - p0.y
        new_xref = a["xref"]
        with self.pdf.edit(pages=[pno]):
            page = self.pdf.doc[pno]
            annot = page.load_annot(a["xref"])
            t = annot.type[0]
            if t in (fitz.PDF_ANNOT_INK, fitz.PDF_ANNOT_LINE):
                verts = annot.vertices
                stroke = annot.colors.get("stroke")
                fill = annot.colors.get("fill")
                width = annot.border.get("width") or 1
                opacity = annot.opacity
                ends = annot.line_ends if t == fitz.PDF_ANNOT_LINE else None
                page.delete_annot(annot)
                if t == fitz.PDF_ANNOT_INK:
                    new = page.add_ink_annot([[(x + dx, y + dy) for (x, y) in s] for s in verts])
                else:
                    new = page.add_line_annot((verts[0][0] + dx, verts[0][1] + dy), (verts[1][0] + dx, verts[1][1] + dy))
                    if ends:
                        new.set_line_ends(*ends)
                new.set_colors(stroke=stroke, fill=fill)
                new.set_border(width=width)
                if opacity is not None and 0 <= opacity < 1:
                    new.set_opacity(opacity)
                new.update()
                new_xref = new.xref
            elif t in (fitz.PDF_ANNOT_HIGHLIGHT, fitz.PDF_ANNOT_UNDERLINE, fitz.PDF_ANNOT_STRIKE_OUT,
                       fitz.PDF_ANNOT_SQUIGGLY):
                raise RuntimeError("Le evidenziazioni sono legate al testo e non si possono spostare.\n"
                                   "Puoi eliminarla (Canc) e crearla di nuovo.")
            else:
                r = annot.rect
                annot.set_rect(fitz.Rect(r.x0 + dx, r.y0 + dy, r.x1 + dx, r.y1 + dy))
        self._reselect_annot(pno, new_xref)

    def _reselect_annot(self, pno, xref):
        for a in self.annot_list(pno):
            if a["xref"] == xref:
                self.sel_annot = a
                break
        if pno < len(self.pages):
            self.pages[pno].update()

    def _finish_ink(self, d):
        pts = d["points"]
        if len(pts) < 2:
            return
        pno = d["pno"]
        page = self.page(pno)
        stroke = [tuple(to_unrot_point(page, p.x(), p.y())) for p in pts]
        with self.pdf.edit(pages=[pno]):
            pg = self.pdf.doc[pno]
            annot = pg.add_ink_annot([stroke])
            annot.set_colors(stroke=qcolor_to_rgb(self.draw_color))
            annot.set_border(width=self.draw_width)
            annot.update()

    def _finish_rect(self, d):
        pno = d["pno"]
        page = self.page(pno)
        rv = QRectF(d["start"], d["cur"]).normalized()
        small = rv.width() < 5 and rv.height() < 5
        t = self.tool
        if t == Tool.IMAGE:
            if self.pending_image:
                self._place_image(pno, self._default_image_rect(d["start"]) if small else rv)
            return
        if t == Tool.TEXTBOX:
            self._add_textbox(pno, d["start"], None if small else rv)
            return
        if small:
            return
        ru = to_unrot_rect(page, fitz.Rect(rv.left(), rv.top(), rv.right(), rv.bottom()))
        rgb = qcolor_to_rgb(self.draw_color)
        if t == Tool.WHITEOUT:
            with self.pdf.edit(pages=[pno]):
                pg = self.pdf.doc[pno]
                pg.add_redact_annot(ru, fill=(1, 1, 1), cross_out=False)
                pg.apply_redactions(images=fitz.PDF_REDACT_IMAGE_PIXELS,
                                    graphics=fitz.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED,
                                    text=fitz.PDF_REDACT_TEXT_REMOVE)
            self.message.emit("🩹 Area cancellata (Ctrl+Z per annullare)")
            return
        with self.pdf.edit(pages=[pno]):
            pg = self.pdf.doc[pno]
            if t == Tool.ARROW:
                annot = pg.add_line_annot(self._unrot(pno, d["start"]), self._unrot(pno, d["cur"]))
                annot.set_line_ends(fitz.PDF_ANNOT_LE_NONE, fitz.PDF_ANNOT_LE_CLOSED_ARROW)
                annot.set_colors(stroke=rgb, fill=rgb)
            else:
                annot = pg.add_circle_annot(ru) if t == Tool.ELLIPSE else pg.add_rect_annot(ru)
                annot.set_colors(stroke=rgb, fill=rgb if self.fill_shapes else None)
                if self.fill_shapes:
                    annot.set_opacity(0.35)
            annot.set_border(width=self.draw_width)
            annot.update()

    def click_action(self, tool, pno, lp):
        pu = self._unrot(pno, lp)
        if tool == Tool.NOTE:
            dlg = NoteDialog(self, "Nuova nota")
            if dlg.exec() and dlg.text().strip():
                with self.pdf.edit(pages=[pno]):
                    pg = self.pdf.doc[pno]
                    annot = pg.add_text_annot(pu, dlg.text(), icon="Comment")
                    annot.set_colors(stroke=(0.98, 0.8, 0.08))
                    annot.update()
        elif tool == Tool.ADD_TEXT:
            self._add_text(pno, lp)
        elif tool == Tool.STAMP:
            self._place_stamp(pno, lp)
        elif tool == Tool.EDIT_TEXT:
            line = self._line_at(pno, pu)
            if line:
                self.edit_line(pno, line)
            else:
                self.message.emit("Nessuna riga di testo qui: clicca su un testo evidenziato dal tratteggio")

    def _add_textbox(self, pno, lp, rv):
        dlg = TextDialog(self, "Casella di testo", family="sans", size=self.text_size, color=self.text_color,
                         note="La casella è un'annotazione: potrai spostarla, modificarla o eliminarla.")
        dlg.family.setEnabled(False)
        dlg.bold.setEnabled(False)
        dlg.italic.setEnabled(False)
        if not dlg.exec():
            return
        v = dlg.values()
        text = v["text"].strip("\n")
        if not text.strip():
            return
        self.text_size, self.text_color = v["size"], v["color"]
        size = v["size"]
        lines = text.split("\n")
        needed_w = max(fitz.get_text_length(l, fontname="helv", fontsize=size) for l in lines) + 12
        if rv is None:
            w = min(max(needed_w, 60), 420)
            rv = QRectF(lp.x(), lp.y(), w, 10)
        # altezza stimata con a capo automatico
        n_lines = 0
        for l in lines:
            n_lines += max(1, math.ceil(fitz.get_text_length(l, fontname="helv", fontsize=size) / max(10, rv.width() - 8)))
        need_h = n_lines * size * 1.3 + 8
        if rv.height() < need_h:
            rv.setHeight(need_h)
        page = self.page(pno)
        ru = to_unrot_rect(page, fitz.Rect(rv.left(), rv.top(), rv.right(), rv.bottom()))
        with self.pdf.edit(pages=[pno]):
            pg = self.pdf.doc[pno]
            pg.add_freetext_annot(ru, text, fontsize=size, fontname="Helv", text_color=qcolor_to_rgb(v["color"]),
                                  rotate=pg.rotation)

    def _add_text(self, pno, lp):
        dlg = TextDialog(self, "Aggiungi testo", family=self.text_family, size=self.text_size, color=self.text_color,
                         note="Il testo viene scritto direttamente sulla pagina.")
        if not dlg.exec():
            return
        v = dlg.values()
        text = v["text"].rstrip()
        if not text.strip():
            return
        self.text_family, self.text_size, self.text_color = v["family"], v["size"], v["color"]
        fontname, fontfile = font_for(v["family"], v["bold"], v["italic"])
        origin = self._unrot(pno, QPointF(lp.x(), lp.y() + v["size"] * 0.9))
        with self.pdf.edit(pages=[pno]):
            pg = self.pdf.doc[pno]
            pg.insert_text(origin, text, fontsize=v["size"], fontname=fontname, fontfile=fontfile,
                           color=qcolor_to_rgb(v["color"]), rotate=pg.rotation)
            if fontfile:
                fix_tounicode(self.pdf.doc, pg, fontname)
                self.pdf.fonts_inserted = True

    def edit_line(self, pno, line):
        span0 = line["spans"][0]
        rotate = _rotate_for_dir(line["dir"])
        if rotate is None:
            QMessageBox.information(self, APP_TITLE, "Questa riga è inclinata e non può essere modificata.")
            return
        fam = guess_family(span0["font"], span0["flags"])
        bold, italic = guess_bold_italic(span0["font"], span0["flags"])
        color = rgb_to_qcolor(int_to_rgb(span0["color"]))
        dlg = TextDialog(self, "Modifica testo", text=line["text"], family=fam, size=round(span0["size"], 1),
                         bold=bold, italic=italic, color=color, multiline=False, allow_original=True,
                         note="La riga verrà sostituita con il nuovo testo. Lascia vuoto per cancellarla. "
                              "Puoi sempre annullare con Ctrl+Z.")
        if not dlg.exec():
            return
        v = dlg.values()
        new_text = v["text"]
        if new_text == line["text"] and v["size"] == round(span0["size"], 1) and v["family"] == "original":
            return
        page = self.page(pno)
        source, font_buffer = ("simile", None)
        if v["family"] == "original" and new_text.strip():
            source, font_buffer = self._pick_font(page, span0, new_text)
        used = source if v["family"] == "original" else ""
        with self.pdf.edit(pages=[pno]):
            pg = self.pdf.doc[pno]
            self._remove_line_text(pg, line, rotate)
            if new_text.strip():
                fontname, fontfile = None, None
                if font_buffer:
                    fontname = f"tkf{abs(hash((span0['font'], source))) % 100000}"
                    pg.insert_font(fontname=fontname, fontbuffer=font_buffer)
                else:
                    family = v["fallback_family"] if v["family"] == "original" else v["family"]
                    fontname, fontfile = font_for(family, v["bold"], v["italic"])
                pg.insert_text(fitz.Point(span0["origin"]), new_text, fontsize=v["size"], fontname=fontname,
                               fontfile=fontfile, color=qcolor_to_rgb(v["color"]), rotate=rotate)
                fix_tounicode(self.pdf.doc, pg, fontname)
                self.pdf.fonts_inserted = True
        detail = {"google": " con lo stesso font scaricato da Google Fonts",
                  "simile": " (font originale non disponibile: usato un font simile)"}.get(used, "")
        self.message.emit("✏️ Testo modificato" + detail)

    def _pick_font(self, page, span, text):
        """Font per riscrivere il testo di uno span: ('originale'|'google'|'simile', buffer o None).

        1) font incorporato, se disegna tutte le lettere; 2) stesso font completo da Google Fonts;
        3) None → il chiamante usa un font di sistema simile."""
        original = find_original_font(self.pdf.doc, page, span["font"])
        if original and font_renders_text(original[1], text):
            return "originale", original[1]
        try:
            # prima i font già scaricati; Google Fonts solo col consenso (chiesto la prima volta, poi ricordato)
            path = webfonts.fetch(span["font"], span.get("flags", 0), download=False)
            if not path and webfonts.ask_consent(self):
                QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
                try:
                    path = webfonts.fetch(span["font"], span.get("flags", 0))
                finally:
                    QApplication.restoreOverrideCursor()
            if path:
                with open(path, "rb") as fh:
                    data = fh.read()
                if font_renders_text(data, text):
                    return "google", data
        except Exception:
            pass
        return "simile", None

    @staticmethod
    def _remove_line_text(pg, line, rotate):
        """Toglie dalla pagina solo il testo della riga (lascia immagini e grafica)."""
        bbox = line["bbox"]
        if rotate in (0, 180):
            pad = bbox.height * 0.22
            r = fitz.Rect(bbox.x0 + 0.3, bbox.y0 + pad, bbox.x1 - 0.3, bbox.y1 - pad)
        else:
            pad = bbox.width * 0.22
            r = fitz.Rect(bbox.x0 + pad, bbox.y0 + 0.3, bbox.x1 - pad, bbox.y1 - 0.3)
        pg.add_redact_annot(r, fill=False, cross_out=False)
        pg.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=fitz.PDF_REDACT_LINE_ART_NONE,
                            text=fitz.PDF_REDACT_TEXT_REMOVE)

    def _text_move_delta(self, d):
        """Spostamento in coordinate vista; con Maiusc resta solo l'asse prevalente."""
        delta = d["cur"] - d["start"]
        if QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier:
            if abs(delta.x()) >= abs(delta.y()):
                delta.setY(0)
            else:
                delta.setX(0)
        return delta

    def move_line(self, pno, line, delta):
        """Sposta una riga di testo mantenendo per ogni pezzo carattere, dimensione e colore."""
        rotate = _rotate_for_dir(line["dir"])
        if rotate is None:
            QMessageBox.information(self, APP_TITLE, "Questa riga è inclinata e non può essere spostata.")
            return
        page = self.page(pno)
        start = self._unrot(pno, QPointF(0, 0))
        end = self._unrot(pno, delta)
        dx, dy = end.x - start.x, end.y - start.y
        plans, sources = [], set()
        for span in line["spans"]:
            if not span["text"].strip():
                continue
            source, font_buffer = self._pick_font(page, span, span["text"])
            sources.add(source)
            plans.append((span, source, font_buffer))
        if not plans:
            return
        with self.pdf.edit(pages=[pno]):
            pg = self.pdf.doc[pno]
            self._remove_line_text(pg, line, rotate)
            for span, source, font_buffer in plans:
                if font_buffer:
                    fontname, fontfile = f"tkf{abs(hash((span['font'], source))) % 100000}", None
                    pg.insert_font(fontname=fontname, fontbuffer=font_buffer)
                else:
                    bold, italic = guess_bold_italic(span["font"], span["flags"])
                    fontname, fontfile = font_for(guess_family(span["font"], span["flags"]), bold, italic)
                origin = fitz.Point(span["origin"][0] + dx, span["origin"][1] + dy)
                pg.insert_text(origin, span["text"], fontsize=span["size"], fontname=fontname, fontfile=fontfile,
                               color=int_to_rgb(span["color"]), rotate=rotate)
                fix_tounicode(self.pdf.doc, pg, fontname)
            self.pdf.fonts_inserted = True
        self.message.emit("↔️ Riga spostata · Ctrl+Z per annullare"
                          + (" (alcune parti con un font simile)" if "simile" in sources else "")
                          + (" · font da Google Fonts" if "google" in sources else ""))

    def _place_image(self, pno, rv):
        img, data, kind = self.pending_image
        page = self.page(pno)
        ru = to_unrot_rect(page, fitz.Rect(rv.left(), rv.top(), rv.right(), rv.bottom()))
        with self.pdf.edit(pages=[pno]):
            pg = self.pdf.doc[pno]
            pg.insert_image(ru, stream=data, keep_proportion=True, overlay=True, rotate=pg.rotation)
        if kind == "check":
            self.message.emit("✔ Spunta inserita · clicca per aggiungerne altre · Esc per finire")
            return
        self.message.emit("✍️ Firma grafica inserita (non è una firma digitale)" if kind == "signature" else "🖼️ Immagine inserita")
        self.set_tool(Tool.SELECT)

    def _place_stamp(self, pno, lp):
        if not self.pending_stamp:
            return
        text, color = self.pending_stamp
        rv = self._stamp_rect(lp, text)
        page = self.page(pno)
        ru = to_unrot_rect(page, fitz.Rect(rv.left(), rv.top(), rv.right(), rv.bottom()))
        rgb = qcolor_to_rgb(color)
        with self.pdf.edit(pages=[pno]):
            pg = self.pdf.doc[pno]
            # senza border_color il bordo usa il colore del testo
            pg.add_freetext_annot(ru, text, fontsize=STAMP_FONT_SIZE, fontname="Helv", text_color=rgb,
                                  border_width=2.5, align=fitz.TEXT_ALIGN_CENTER, rotate=pg.rotation)
        self.message.emit("🔖 Timbro applicato")
        self.set_tool(Tool.SELECT)

    # ------------------------------------------------------------ annotazioni
    def delete_selected_annot(self):
        a = self.sel_annot
        if not a:
            return
        with self.pdf.edit(pages=[a["pno"]]):
            page = self.pdf.doc[a["pno"]]
            page.delete_annot(page.load_annot(a["xref"]))
        self.message.emit("🗑️ Annotazione eliminata")

    def edit_annot_text(self, a):
        page = self.page(a["pno"])
        annot = page.load_annot(a["xref"])
        dlg = NoteDialog(self, "Modifica testo annotazione", annot.info.get("content", ""))
        if not dlg.exec():
            return
        with self.pdf.edit(pages=[a["pno"]]):
            pg = self.pdf.doc[a["pno"]]
            an = pg.load_annot(a["xref"])
            an.set_info(content=dlg.text())
            an.update()
        self._reselect_annot(a["pno"], a["xref"])

    def recolor_annot(self, a):
        c = QColorDialog.getColor(QColor("#dc2626"), self, "Colore annotazione")
        if not c.isValid():
            return
        rgb = qcolor_to_rgb(c)
        with self.pdf.edit(pages=[a["pno"]]):
            pg = self.pdf.doc[a["pno"]]
            an = pg.load_annot(a["xref"])
            if an.type[0] == fitz.PDF_ANNOT_FREE_TEXT:
                an.update(text_color=rgb, border_color=rgb if an.border.get("width") else None)
            else:
                fill = an.colors.get("fill")
                an.set_colors(stroke=rgb, fill=rgb if fill else None)
                an.update()
        self._reselect_annot(a["pno"], a["xref"])

    def contextMenuEvent(self, e):
        if self.pdf.doc is None or not self.pages:
            return
        it, lp = self._hit(e.pos())
        if it is None:
            return
        pno = it.pno
        pu = self._unrot(pno, lp)
        menu = QMenu(self)
        if self.tool == Tool.OBJECTS:
            o = self._obj_at(pno, pu)
            if o:
                self.sel_obj = (pno, o)
                it.update()
                self.object_menu(menu)
        a = self._annot_at(pno, pu)
        if a is not None:
            self.sel_annot = a
            it.update()
            if a["type"] in TEXT_ANNOTS:
                menu.addAction("✏️ Modifica testo annotazione", lambda: self.edit_annot_text(a))
            menu.addAction("🎨 Cambia colore…", lambda: self.recolor_annot(a))
            menu.addAction("🗑️ Elimina annotazione", self.delete_selected_annot)
            menu.addSeparator()
        if self.sel and self.sel["pno"] == pno:
            menu.addAction("📋 Copia", self.copy_selection)
            menu.addAction("🖍️ Evidenzia", lambda: self.apply_markup(Tool.HIGHLIGHT))
            menu.addAction("Sottolinea", lambda: self.apply_markup(Tool.UNDERLINE))
            menu.addAction("Barra", lambda: self.apply_markup(Tool.STRIKE))
            menu.addSeparator()
        line = self._line_at(pno, pu)
        if line:
            menu.addAction("✏️ Modifica questa riga", lambda: self.edit_line(pno, line))
        menu.addAction("📝 Aggiungi testo qui", lambda: self.click_action(Tool.ADD_TEXT, pno, lp))
        menu.addAction("💬 Aggiungi nota qui", lambda: self.click_action(Tool.NOTE, pno, lp))
        menu.addSeparator()
        menu.addAction("Seleziona tutto il testo della pagina", lambda: self.select_all_page(pno))
        try:
            menu.exec(e.globalPos())
        except Exception as exc:
            QMessageBox.warning(self, APP_TITLE, f"Operazione non riuscita:\n{exc}")

    def _follow_link(self, link):
        kind = link.get("kind")
        if kind == fitz.LINK_URI and link.get("uri"):
            uri = link["uri"]
            # solo pagine web e indirizzi email: niente file locali, programmi o altri protocolli
            if QUrl(uri).scheme().lower() not in ("http", "https", "mailto"):
                QMessageBox.warning(self, APP_TITLE, "Questo collegamento non viene aperto: tk-pdf apre solo pagine "
                                                     f"web (http, https) e indirizzi email.\n\n{uri}")
                return
            if QMessageBox.question(self, APP_TITLE, f"Aprire questo collegamento nel browser?\n\n{uri}") == \
                    QMessageBox.StandardButton.Yes:
                QDesktopServices.openUrl(QUrl(uri))
        elif link.get("page", -1) is not None and link.get("page", -1) >= 0:
            self.go_to_page(link["page"])

    # ================================================================ moduli
    def _find_widget(self, page, xref):
        for w in page.widgets():
            if w.xref == xref:
                return w
        return None

    def _activate_field(self, pno, xref):
        w = self._find_widget(self.page(pno), xref)
        if w is None:
            return
        ft = w.field_type
        if ft == fitz.PDF_WIDGET_TYPE_TEXT:
            if w.field_flags & fitz.PDF_FIELD_IS_READ_ONLY:
                self.message.emit("Questo campo è di sola lettura")
                return
            self._open_field_editor(pno, w)
        elif ft in (fitz.PDF_WIDGET_TYPE_CHECKBOX, fitz.PDF_WIDGET_TYPE_RADIOBUTTON):
            is_on = w.field_value not in (False, "Off", "", None)
            if ft == fitz.PDF_WIDGET_TYPE_RADIOBUTTON and is_on:
                return
            with self.pdf.edit(pages=[pno]):
                pg = self.pdf.doc[pno]
                ww = self._find_widget(pg, xref)
                ww.field_value = False if is_on else ww.on_state()
                ww.update()
        elif ft in (fitz.PDF_WIDGET_TYPE_COMBOBOX, fitz.PDF_WIDGET_TYPE_LISTBOX):
            menu = QMenu(self)
            for choice in w.choice_values or []:
                if isinstance(choice, (list, tuple)):
                    value, label = choice[0], choice[1] if len(choice) > 1 else choice[0]
                else:
                    value = label = choice
                act = menu.addAction(str(label))
                act.setData(value)
                act.setCheckable(True)
                act.setChecked(str(value) == str(w.field_value))
            editable = w.field_flags & fitz.PDF_CH_FIELD_IS_EDIT
            if editable:
                menu.addSeparator()
                custom = menu.addAction("✏️ Scrivi un valore…")
                custom.setData("__custom__")
            chosen = menu.exec(QCursor.pos())
            if chosen is None:
                return
            value = chosen.data()
            if value == "__custom__":
                value, ok = QInputDialog.getText(self, APP_TITLE, "Valore:", text=str(w.field_value or ""))
                if not ok:
                    return
            with self.pdf.edit(pages=[pno]):
                pg = self.pdf.doc[pno]
                ww = self._find_widget(pg, xref)
                ww.field_value = value
                ww.update()
        elif ft == fitz.PDF_WIDGET_TYPE_SIGNATURE:
            # tk-pdf non crea firme digitali: sopra il campo si può mettere solo una firma grafica
            QMessageBox.information(
                self, APP_TITLE,
                "Questo è un campo per la firma digitale.\n\n"
                "tk-pdf non crea firme digitali: con «✍️ Firma» puoi mettere sopra il campo una firma grafica "
                "(un'immagine), che non è una firma digitale né qualificata e non ha valore dove serve la firma "
                "digitale. Per quella usa il programma del tuo dispositivo di firma (smart card, firma remota).")

    def _open_field_editor(self, pno, w):
        page = self.page(pno)
        it = self.pages[pno]
        vr = to_view_rect(page, w.rect)
        scene_r = QRectF(it.x() + vr.x0, it.y() + vr.y0, vr.width, vr.height)
        rect = self.mapFromScene(scene_r).boundingRect()
        multiline = bool(w.field_flags & fitz.PDF_TX_FIELD_IS_MULTILINE)
        value = w.field_value or ""
        if multiline:
            ed = QPlainTextEdit(self.viewport())
            ed.setPlainText(str(value))
        else:
            ed = QLineEdit(self.viewport())
            ed.setText(str(value))
            if w.text_maxlen:
                ed.setMaxLength(w.text_maxlen)
            if w.field_flags & fitz.PDF_TX_FIELD_IS_PASSWORD:
                ed.setEchoMode(QLineEdit.EchoMode.Password)
        if multiline:
            fs = w.text_fontsize or 11
        else:
            fs = w.text_fontsize or min(vr.height * 0.62, 12)
        px = max(8, int(fs * self.transform().m11()))
        ed.setStyleSheet(f"background:#fffbeb; border:2px solid {ACCENT}; border-radius:2px; padding:0 3px;"
                         f"font-size:{px}px; color:#0f172a;")
        ed.setGeometry(rect.adjusted(-2, -2, 2, 2))
        if not multiline and rect.height() < px + 8:
            ed.setGeometry(rect.x() - 2, rect.center().y() - (px + 10) // 2, rect.width() + 4, px + 10)
        ed.show()
        ed.setFocus()
        if isinstance(ed, QLineEdit):
            ed.selectAll()
        ed.installEventFilter(self)
        self._field_editor = dict(widget=ed, pno=pno, xref=w.xref, original=str(value), multiline=multiline)
        self.message.emit("Scrivi nel campo · Invio per confermare · Tab per il campo successivo · Esc per annullare")

    def eventFilter(self, obj, ev):
        fe = self._field_editor
        if fe and obj is fe["widget"]:
            if ev.type() == QEvent.Type.KeyPress:
                key = ev.key()
                if key == Qt.Key.Key_Escape:
                    self._close_field_editor(False)
                    return True
                if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not fe["multiline"]:
                    self._close_field_editor(True)
                    return True
                if key in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
                    pno, xref = fe["pno"], fe["xref"]
                    step = -1 if key == Qt.Key.Key_Backtab or ev.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
                    self._close_field_editor(True)
                    QTimer.singleShot(0, lambda: self._next_field(pno, xref, step))
                    return True
            elif ev.type() == QEvent.Type.FocusOut:
                QTimer.singleShot(0, lambda: self._field_editor is fe and self._close_field_editor(True))
        return super().eventFilter(obj, ev)

    def _close_field_editor(self, commit):
        fe = self._field_editor
        if not fe:
            return
        self._field_editor = None
        ed = fe["widget"]
        text = ed.toPlainText() if fe["multiline"] else ed.text()
        ed.removeEventFilter(self)
        ed.hide()
        ed.deleteLater()
        self.setFocus()
        self.message.emit(TOOL_HINTS.get(self.tool, ""))
        if commit and text != fe["original"] and self.pdf.doc is not None:
            try:
                with self.pdf.edit(pages=[fe["pno"]]):
                    pg = self.pdf.doc[fe["pno"]]
                    ww = self._find_widget(pg, fe["xref"])
                    if ww is not None:
                        ww.field_value = text
                        ww.update()
            except Exception as exc:
                QMessageBox.warning(self, APP_TITLE, f"Impossibile compilare il campo:\n{exc}")

    def _next_field(self, pno, xref, step):
        fields = []
        for p in range(self.pdf.page_count):
            for rect, ft, x in sorted(self.widget_rects(p), key=lambda t: (round(t[0].y0), t[0].x0)):
                if ft == fitz.PDF_WIDGET_TYPE_TEXT:
                    fields.append((p, x))
        if not fields:
            return
        try:
            i = fields.index((pno, xref))
        except ValueError:
            i = -1
        p, x = fields[(i + step) % len(fields)]
        a, b = self.visible_range()
        w = self._find_widget(self.page(p), x)
        if w is None:
            return
        r = to_view_rect(self.page(p), w.rect)
        it = self.pages[p]
        scene_r = QRectF(it.x() + r.x0, it.y() + r.y0, r.width, r.height)
        if not self.mapToScene(self.viewport().rect()).boundingRect().contains(scene_r):
            self.centerOn(scene_r.center())
        self._open_field_editor(p, w)

    # ================================================================ ricerca
    def search(self, text):
        self.search_hits = {}
        self.search_current = None
        total = 0
        if text and self.pdf.doc is not None:
            for p in range(self.pdf.page_count):
                hits = self.page(p).search_for(text)
                if hits:
                    self.search_hits[p] = hits
                    total += len(hits)
        for it in self.pages:
            it.update()
        return total

    def search_step(self, step):
        order = [(p, i) for p in sorted(self.search_hits) for i in range(len(self.search_hits[p]))]
        if not order:
            return None
        if self.search_current in order:
            idx = (order.index(self.search_current) + step) % len(order)
        elif step > 0:
            idx = next((k for k, (p, _) in enumerate(order) if p >= self._current), 0)
        else:
            idx = next((k for k in range(len(order) - 1, -1, -1) if order[k][0] <= self._current), len(order) - 1)
        self.search_current = order[idx]
        p, i = order[idx]
        r = to_view_rect(self.page(p), self.search_hits[p][i])
        it = self.pages[p]
        self.centerOn(QPointF(it.x() + (r.x0 + r.x1) / 2, it.y() + (r.y0 + r.y1) / 2))
        for item in self.pages:
            item.update()
        return idx + 1, len(order)
