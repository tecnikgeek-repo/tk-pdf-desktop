"""Pannello miniature con riordino tramite trascinamento."""
import pymupdf as fitz
from PySide6.QtCore import QPoint, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPen, QPixmap
from PySide6.QtWidgets import QAbstractItemView, QListWidget, QListWidgetItem, QStyle, QStyledItemDelegate

from tkpdf.style import ACCENT, ACCENT_D, ACCENT_L, GRAY_200, GRAY_500
from tkpdf.util import pix_to_qimage

THUMB_W = 118
ROLE_PNO = Qt.ItemDataRole.UserRole + 1
ROLE_PIX = Qt.ItemDataRole.UserRole + 2
ROLE_SIZE = Qt.ItemDataRole.UserRole + 3


class ThumbDelegate(QStyledItemDelegate):
    def paint(self, p, option, index):
        p.save()
        p.setRenderHint(p.RenderHint.Antialiasing, True)
        p.setRenderHint(p.RenderHint.SmoothPixmapTransform, True)
        r = QRectF(option.rect).adjusted(6, 3, -6, -3)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if selected or hover:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(ACCENT_L if selected else GRAY_200))
            p.drawRoundedRect(r, 8, 8)
        size = index.data(ROLE_SIZE) or QSize(THUMB_W, int(THUMB_W * 1.41))
        tw, th = size.width(), size.height()
        target = QRectF(r.center().x() - tw / 2, r.top() + 8, tw, th)
        p.fillRect(target.translated(1, 2), QColor(15, 23, 42, 40))
        p.fillRect(target, QColor("white"))
        pix = index.data(ROLE_PIX)
        if isinstance(pix, QPixmap) and not pix.isNull():
            p.drawPixmap(target, pix, QRectF(pix.rect()))
        if selected:
            p.setPen(QPen(QColor(ACCENT), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(target.adjusted(-1, -1, 1, 1))
        font = QFont(option.font)
        font.setBold(True)
        font.setPointSizeF(8.5)
        p.setFont(font)
        p.setPen(QColor(ACCENT_D if selected else GRAY_500))
        p.drawText(QRectF(r.left(), target.bottom() + 3, r.width(), 18), Qt.AlignmentFlag.AlignCenter, str(index.row() + 1))
        p.restore()

    def sizeHint(self, option, index):
        size = index.data(ROLE_SIZE) or QSize(THUMB_W, int(THUMB_W * 1.41))
        return QSize(size.width() + 28, size.height() + 36)


class ThumbPanel(QListWidget):
    pageActivated = Signal(int)
    reordered = Signal(list)

    def __init__(self, pdf, parent=None):
        super().__init__(parent)
        self.pdf = pdf
        self.setObjectName("tkThumbs")
        self.setItemDelegate(ThumbDelegate(self))
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setMouseTracking(True)
        self.setUniformItemSizes(False)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.setFixedWidth(THUMB_W + 58)

        self._syncing = False
        self._dirty = set()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._render_some)
        self.currentRowChanged.connect(self._on_row)
        self.verticalScrollBar().valueChanged.connect(lambda _: self._timer.start(30))
        pdf.changed.connect(self._on_doc_changed)

    # ------------------------------------------------------------ dati
    def _on_doc_changed(self, structure):
        n = self.pdf.page_count
        if structure or n != self.count():
            self.rebuild()
        else:
            pages = self.pdf.last_pages
            self._dirty.update(range(n) if pages is None else [p for p in pages if p < n])
            self._timer.start(60)

    def rebuild(self):
        cur = max(0, self.currentRow())
        self._syncing = True
        old_pix = {}
        # conserva le vecchie miniature per evitare lo sfarfallio (vengono comunque ridisegnate)
        for i in range(self.count()):
            old_pix[i] = self.item(i).data(ROLE_PIX)
        self.clear()
        doc = self.pdf.doc
        for i in range(self.pdf.page_count):
            r = doc[i].rect
            item = QListWidgetItem()
            item.setData(ROLE_PNO, i)
            item.setData(ROLE_SIZE, QSize(THUMB_W, max(20, int(THUMB_W * r.height / max(1.0, r.width)))))
            if old_pix.get(i) is not None:
                item.setData(ROLE_PIX, old_pix[i])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsDragEnabled)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsDropEnabled)
            self.addItem(item)
        if self.count():
            self.setCurrentRow(min(cur, self.count() - 1))
        self._syncing = False
        self._dirty = set(range(self.count()))
        self._timer.start(0)

    def _visible_rows(self):
        if not self.count():
            return range(0)
        top = self.indexAt(QPoint(10, 5)).row()
        bottom = self.indexAt(QPoint(10, self.viewport().height() - 5)).row()
        top = 0 if top < 0 else top
        bottom = self.count() - 1 if bottom < 0 else bottom
        return range(max(0, top - 1), min(self.count(), bottom + 2))

    def _render_some(self):
        if self.pdf.doc is None or not self._dirty:
            return
        visible = [i for i in self._visible_rows() if i in self._dirty]
        row = visible[0] if visible else min(self._dirty)
        self._dirty.discard(row)
        item = self.item(row)
        if item is not None and row < self.pdf.page_count:
            try:
                page = self.pdf.doc[item.data(ROLE_PNO)]
                scale = THUMB_W / max(1.0, page.rect.width) * self.devicePixelRatioF()
                pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False, annots=True)
                qpix = QPixmap.fromImage(pix_to_qimage(pix))
                item.setData(ROLE_PIX, qpix)
            except Exception:
                pass
        if self._dirty:
            self._timer.start(0 if visible else 15)

    # ------------------------------------------------------------ interazione
    def _on_row(self, row):
        if not self._syncing and row >= 0:
            self.pageActivated.emit(row)

    def set_current(self, pno):
        if 0 <= pno < self.count() and self.currentRow() != pno:
            self._syncing = True
            self.setCurrentRow(pno)
            self.scrollToItem(self.item(pno), QAbstractItemView.ScrollHint.EnsureVisible)
            self._syncing = False

    def selected_pages(self):
        rows = sorted(self.row(it) for it in self.selectedItems())
        if not rows and self.currentRow() >= 0:
            rows = [self.currentRow()]
        return rows

    def dropEvent(self, e):
        if e.source() is not self:
            e.ignore()
            return
        super().dropEvent(e)
        order = [self.item(i).data(ROLE_PNO) for i in range(self.count())]
        if order != list(range(len(order))):
            QTimer.singleShot(0, lambda: self.reordered.emit(order))
