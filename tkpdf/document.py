"""Modello del documento PDF con annulla/ripeti."""
import os
from contextlib import contextmanager

import pymupdf as fitz
from PySide6.QtCore import QObject, Signal

from tkpdf.filesave import write_file

MAX_UNDO = 30
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp")
# limitazioni che l'autore può mettere a un PDF (password del proprietario)
PERMISSIONS = (
    (fitz.PDF_PERM_PRINT, "stampa"),
    (fitz.PDF_PERM_MODIFY, "modifica"),
    (fitz.PDF_PERM_COPY, "copia del testo"),
    (fitz.PDF_PERM_ANNOTATE, "annotazioni"),
    (fitz.PDF_PERM_FORM, "compilazione dei moduli"),
)
# permessi dei file salvati con password da tk-pdf
PERMISSIONS_ALL = int(fitz.PDF_PERM_ACCESSIBILITY | fitz.PDF_PERM_PRINT | fitz.PDF_PERM_COPY
                      | fitz.PDF_PERM_ANNOTATE | fitz.PDF_PERM_FORM | fitz.PDF_PERM_PRINT_HQ)


class PasswordRequired(Exception):
    pass


def restrictions_of(doc):
    """Limitazioni del proprietario (stampa, modifica…) di un PDF cifrato aperto: elenco dei nomi, [] se nessuna."""
    try:
        if not (doc.metadata or {}).get("encryption"):
            return []
        perms = doc.permissions
        return [name for bit, name in PERMISSIONS if not perms & bit]
    except Exception:
        return []


def has_digital_signatures(doc):
    """Vero se il PDF contiene firme digitali (SigFlags del modulo o campi firma compilati)."""
    try:
        flags = doc.get_sigflags()
        if flags > 0 and flags & 1:
            return True
        for page in doc:
            for w in page.widgets(types=[fitz.PDF_WIDGET_TYPE_SIGNATURE]):
                if doc.xref_get_key(w.xref, "V")[0] not in ("null", ""):
                    return True
    except Exception:
        pass
    return False


class PdfDocument(QObject):
    # True = struttura cambiata (numero/ordine/dimensioni/rotazione pagine)
    changed = Signal(bool)
    stateChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.doc = None
        self.path = None
        self.password = None
        self.restrictions = []      # limitazioni dell'autore (stampa, modifica…) del file aperto
        self.signed_path = None     # file aperto con firme digitali: salvarci sopra le rende non valide
        self.revision = 0
        self.fonts_inserted = False
        self._undo = []
        self._redo = []
        self._clean_len = 0
        # pagine toccate dall'ultima modifica (None = tutte)
        self.last_pages = None

    # ------------------------------------------------------------ proprietà
    @property
    def is_open(self):
        return self.doc is not None

    @property
    def page_count(self):
        return self.doc.page_count if self.doc is not None else 0

    @property
    def dirty(self):
        return self.doc is not None and len(self._undo) != self._clean_len

    @property
    def can_undo(self):
        return bool(self._undo)

    @property
    def can_redo(self):
        return bool(self._redo)

    def title(self):
        return os.path.basename(self.path) if self.path else "Senza titolo.pdf"

    # ------------------------------------------------------------ apertura
    @staticmethod
    def file_to_pdf_bytes(path, password=None):
        """Legge un PDF o un'immagine e ritorna i byte PDF (non cifrati)."""
        return PdfDocument._read(path, password)[0]

    @staticmethod
    def _read(path, password=None):
        """(byte PDF, limitazioni del proprietario) di un PDF o di un'immagine."""
        ext = os.path.splitext(path)[1].lower()
        with open(path, "rb") as fh:
            data = fh.read()
        if ext in IMAGE_EXT:
            img = fitz.open(stream=data, filetype=ext.lstrip("."))
            try:
                return img.convert_to_pdf(), []
            finally:
                img.close()
        src = fitz.open(stream=data, filetype="pdf")
        try:
            if src.needs_pass:
                if not password or not src.authenticate(password):
                    raise PasswordRequired()
                return src.tobytes(encryption=fitz.PDF_ENCRYPT_NONE), restrictions_of(src)
            return data, restrictions_of(src)
        finally:
            src.close()

    def open_file(self, path, password=None):
        data, restrictions = self._read(path, password)
        is_pdf = os.path.splitext(path)[1].lower() not in IMAGE_EXT
        self._set_doc(fitz.open(stream=data, filetype="pdf"))
        self.path = path if is_pdf else None
        self.password = password or None
        self.restrictions = restrictions
        self.signed_path = path if is_pdf and has_digital_signatures(self.doc) else None
        self._reset_history(clean=is_pdf)

    def new_from_bytes(self, data):
        self._set_doc(fitz.open(stream=data, filetype="pdf"))
        self.path = None
        self.password = None
        self.restrictions = []
        self.signed_path = None
        self._reset_history(clean=False)

    def close(self):
        if self.doc is not None:
            self.doc.close()
        self.doc = None
        self.path = None
        self.password = None
        self.restrictions = []
        self.signed_path = None
        self._undo.clear()
        self._redo.clear()
        self._clean_len = 0
        self._emit(True, None)

    def _set_doc(self, doc):
        if self.doc is not None:
            self.doc.close()
        self.doc = doc
        self.fonts_inserted = False

    def _reset_history(self, clean):
        self._undo.clear()
        self._redo.clear()
        # documento nuovo/da immagini: risulta "da salvare"
        self._clean_len = 0 if clean else -1
        self._emit(True, None)

    # ------------------------------------------------------------ modifiche
    def _bytes(self):
        return self.doc.tobytes(encryption=fitz.PDF_ENCRYPT_NONE)

    def _reload(self, data):
        self.doc.close()
        self.doc = fitz.open(stream=data, filetype="pdf")

    def _push_undo(self, data):
        self._undo.append(data)
        if len(self._undo) > MAX_UNDO:
            self._undo.pop(0)
            self._clean_len -= 1
        self._redo.clear()
        if self._clean_len > len(self._undo):
            self._clean_len = -1

    @contextmanager
    def edit(self, structure=False, pages=None):
        """Esegue una modifica annullabile: `with pdf.edit(pages=[n]): ...`"""
        before = self._bytes()
        try:
            yield self.doc
        except Exception:
            self._reload(before)
            self._emit(True, None)
            raise
        self._push_undo(before)
        self._emit(structure, None if structure else pages)

    def _emit(self, structure, pages):
        self.revision += 1
        self.last_pages = pages
        self.changed.emit(structure)
        self.stateChanged.emit()

    def replace_bytes(self, data):
        before = self._bytes()
        self._reload(data)
        self._push_undo(before)
        self._emit(True, None)

    def undo(self):
        if not self._undo:
            return
        self._redo.append(self._bytes())
        self._reload(self._undo.pop())
        self._emit(True, None)

    def redo(self):
        if not self._redo:
            return
        self._undo.append(self._bytes())
        self._reload(self._redo.pop())
        self._emit(True, None)

    # ------------------------------------------------------------ salvataggio
    def build_bytes(self, password=None, compact=True):
        if self.fonts_inserted:
            try:
                self.doc.subset_fonts()
            except Exception:
                pass
        kw = dict(garbage=3 if compact else 1, deflate=True, use_objstms=1)
        if password:
            kw.update(encryption=fitz.PDF_ENCRYPT_AES_256, user_pw=password, owner_pw=password,
                      permissions=PERMISSIONS_ALL)
        return self.doc.tobytes(**kw)

    def save(self, path=None, password=None, allow_read_only=False):
        """password=None mantiene quella attuale; '' la rimuove.
        allow_read_only=True: l'utente ha chiesto di sovrascrivere un file in sola lettura."""
        path = path or self.path
        pw = self.password if password is None else (password or None)
        data = self.build_bytes(pw)
        write_file(path, data, allow_read_only=allow_read_only)
        self.path = path
        self.password = pw
        self._clean_len = len(self._undo)
        self.stateChanged.emit()
        return len(data)

    def save_pages_as(self, pages, path):
        """Pagine in un nuovo PDF; se l'originale ha la password, il nuovo file la mantiene (AES-256)."""
        out = fitz.open()
        try:
            for p in pages:
                out.insert_pdf(self.doc, from_page=p, to_page=p)
            kw = dict(garbage=3, deflate=True)
            if self.password:
                kw.update(encryption=fitz.PDF_ENCRYPT_AES_256, user_pw=self.password, owner_pw=self.password,
                          permissions=PERMISSIONS_ALL)
            write_file(path, out.tobytes(**kw))
        finally:
            out.close()
