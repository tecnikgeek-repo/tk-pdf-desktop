"""Finestra principale di tk-pdf."""
import os
import sys

import pymupdf as fitz
from PySide6.QtCore import QPointF, QSettings, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import (
    QAction, QColor, QDesktopServices, QIcon, QImage, QKeySequence, QPainter, QPen, QPixmap, QPolygonF,
    QTransform,
)
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPushButton,
    QScrollArea, QSizePolicy, QStackedWidget, QToolButton, QVBoxLayout, QWidget, QWidgetAction,
)

from tkpdf import APP_TITLE, AUTHOR, VERSION
from tkpdf.dialogs import (
    OPEN_FILTER, STAMPS, ColorButton, CompressDialog, MergeDialog, PasswordDialog,
    SignatureDialog, SplitDialog, StampDialog, saved_signatures,
)
from tkpdf.document import PasswordRequired, PdfDocument
from tkpdf.filesave import ReadOnlyError, SaveError, free_name, protection_help
from tkpdf.icon import app_icon
from tkpdf.scan import ScanDialog
from tkpdf.thumbs import ThumbPanel
from tkpdf.tk_licenza_qt import dentro_lo_schermo, testata_compatta
from tkpdf.updater_ui import UpdateManager
from tkpdf.util import IS_MAC, human_size, pix_to_qimage, qimage_to_png_bytes
from tkpdf.viewer import TOOL_HINTS, PdfView, Tool

RECENT_THUMB_W, RECENT_THUMB_H = 34, 44
ZOOM_PRESETS = ["50%", "75%", "100%", "125%", "150%", "200%", "300%", "400%"]
FIT_WIDTH = "Adatta larghezza"
FIT_PAGE = "Pagina intera"


def shortcut_text(text):
    """Sul Mac le scorciatoie Ctrl diventano ⌘ (Qt mappa già Ctrl sul tasto Cmd)."""
    return text.replace("Ctrl+", "⌘").replace("Shift+", "⇧") if IS_MAC else text


def _sep():
    line = QFrame()
    line.setFrameShape(QFrame.Shape.VLine)
    line.setStyleSheet("color:#e2e8f0;")
    line.setFixedWidth(12)
    return line


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("TecnikGeek", "tk-pdf")
        self.icon = app_icon()
        self.setWindowIcon(self.icon)
        self.setAcceptDrops(True)
        self.resize(1320, 880)

        self.pdf = PdfDocument(self)
        self.view = PdfView(self.pdf)
        self.view.setAcceptDrops(False)
        self.thumbs = ThumbPanel(self.pdf)
        self._tool_buttons = {}
        self._doc_actions = []
        self._thumb_cache = {}
        self._wide_buttons = []      # (pulsante, testo intero, testo corto) per finestre strette
        self._hint = ""
        self.updates = UpdateManager(self)
        self.closing_for_update = False
        self._renamed_save = False      # un salvataggio è finito in una copia numerata

        root = QWidget()
        lay = QVBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._build_header())
        lay.addWidget(self._build_tabs())
        lay.addWidget(self._build_tools())

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_welcome())
        self.stack.addWidget(self._build_doc_area())
        lay.addWidget(self.stack, 1)
        self.setCentralWidget(root)

        self.status_msg = QLabel()
        self.status_page = QLabel()
        self.statusBar().addWidget(self.status_msg, 1)
        self.statusBar().addPermanentWidget(self.status_page)
        self._msg_timer = QTimer(self)
        self._msg_timer.setSingleShot(True)
        self._msg_timer.timeout.connect(lambda: self.status_msg.setText(self._hint))

        self._build_shortcuts()
        self._connect()
        # su finestre strette la testata mostra solo le icone; e la finestra non esce mai dallo schermo (MacBook)
        testata_compatta(self, [(b, corto) for b, _intero, corto in self._wide_buttons], 1380)
        geo = self.settings.value("geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        dentro_lo_schermo(self)
        self.thumbs.setVisible(self.settings.value("thumbs", True, type=bool))
        self.btn_thumbs.setChecked(self.thumbs.isVisible())
        self._set_tab(0)
        self.update_state()

    # ================================================================ costruzione UI
    def _hbtn(self, text, tip, slot, doc_only=True):
        b = QToolButton()
        b.setText(text)
        b.setToolTip(shortcut_text(tip))
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        if slot:
            b.clicked.connect(slot)
        if doc_only:
            self._doc_actions.append(b)
        return b

    def _build_header(self):
        w = QWidget()
        w.setObjectName("tkHeader")
        w.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        h = QHBoxLayout(w)
        h.setContentsMargins(16, 10, 12, 10)
        h.setSpacing(4)

        ic = QLabel()
        ic.setPixmap(self.icon.pixmap(34, 34))
        h.addWidget(ic)
        h.addSpacing(6)
        col = QVBoxLayout()
        col.setSpacing(0)
        title = QLabel(APP_TITLE)
        title.setObjectName("tkHeaderTitle")
        self.file_label = QLabel(f"v{VERSION}")
        self.file_label.setObjectName("tkHeaderFile")
        col.addWidget(title)
        col.addWidget(self.file_label)
        h.addLayout(col)
        h.addSpacing(18)

        b_apri = self._hbtn("📂 Apri", "Apri un PDF (Ctrl+O)", self.open_dialog, doc_only=False)
        self._wide_buttons.append((b_apri, "📂 Apri", "📂"))
        h.addWidget(b_apri)
        self.btn_save = self._hbtn("💾 Salva", "Salva (Ctrl+S)", self.save)
        self._wide_buttons.append((self.btn_save, "💾 Salva", "💾"))
        h.addWidget(self.btn_save)
        # su finestre strette restano le sole icone, altrimenti la finestra non si potrebbe rimpicciolire
        for text, short, tip, slot in (
                ("💾 Salva con nome", "💾⁺", "Salva una copia con un altro nome (Ctrl+Maiusc+S)", self.save_as),
                ("🔒 Salva con password", "🔒", "Salva una copia protetta da password", self.protect)):
            b = self._hbtn(text, tip, slot)
            self._wide_buttons.append((b, text, short))
            h.addWidget(b)
        b_stampa = self._hbtn("🖨️ Stampa", "Stampa (Ctrl+P)", self.print_doc)
        self._wide_buttons.append((b_stampa, "🖨️ Stampa", "🖨️"))
        h.addWidget(b_stampa)
        h.addSpacing(10)
        self.btn_undo = self._hbtn("↶", "Annulla (Ctrl+Z)", self.pdf.undo)
        self.btn_redo = self._hbtn("↷", "Ripeti (Ctrl+Y)", self.pdf.redo)
        for b in (self.btn_undo, self.btn_redo):
            b.setStyleSheet("font-size:20px; padding:0 10px;")
            h.addWidget(b)
        h.addStretch(1)

        # ‹ › invece di ◀ ▶: su Windows questi ultimi vengono disegnati come emoji blu
        prev_btn = self._hbtn("‹", "Pagina precedente", lambda: self.view.go_to_page(self.view.current_page() - 1))
        prev_btn.setStyleSheet("QToolButton { font-size: 22px; padding: 0 10px 3px 10px; }")
        h.addWidget(prev_btn)
        self.page_edit = QLineEdit()
        self.page_edit.setFixedWidth(46)
        self.page_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_edit.returnPressed.connect(self._goto_page_edit)
        self._doc_actions.append(self.page_edit)
        h.addWidget(self.page_edit)
        self.page_total = QLabel("/ 0")
        self.page_total.setStyleSheet("color:#cbd5e1; padding: 0 4px;")
        h.addWidget(self.page_total)
        next_btn = self._hbtn("›", "Pagina successiva", lambda: self.view.go_to_page(self.view.current_page() + 1))
        next_btn.setStyleSheet("QToolButton { font-size: 22px; padding: 0 10px 3px 10px; }")
        h.addWidget(next_btn)
        h.addSpacing(10)

        h.addWidget(self._hbtn("−", "Riduci (Ctrl+-)", lambda: self.view.set_zoom(self.view.zoom / 1.2)))
        self.zoom_combo = QComboBox()
        self.zoom_combo.setEditable(True)
        self.zoom_combo.addItems([FIT_WIDTH, FIT_PAGE] + ZOOM_PRESETS)
        self.zoom_combo.setFixedWidth(132)
        self.zoom_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.zoom_combo.textActivated.connect(self._zoom_from_combo)
        self._doc_actions.append(self.zoom_combo)
        h.addWidget(self.zoom_combo)
        h.addWidget(self._hbtn("+", "Ingrandisci (Ctrl++)", lambda: self.view.set_zoom(self.view.zoom * 1.2)))
        h.addSpacing(10)
        h.addWidget(self._hbtn("🔍", "Cerca nel documento (Ctrl+F)", self.show_search))
        self.btn_update = self._hbtn("⬆️ Aggiorna", "È disponibile una nuova versione di tk-pdf",
                                     lambda: self.updates.show_dialog(), doc_only=False)
        self.btn_update.setStyleSheet("QToolButton { background:#e11d48; color:white; border-radius:6px; padding:6px 12px; }"
                                      "QToolButton:hover { background:#be123c; }")
        self.btn_update.hide()
        h.addWidget(self.btn_update)

        menu_btn = self._hbtn("☰", "Menu", None, doc_only=False)
        menu_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu_btn.setStyleSheet("QToolButton::menu-indicator{image:none;} QToolButton{font-size:19px;}")
        self.main_menu = QMenu(menu_btn)
        self.main_menu.aboutToShow.connect(self._build_main_menu)
        menu_btn.setMenu(self.main_menu)
        h.addWidget(menu_btn)
        return w

    def _build_tabs(self):
        w = QWidget()
        w.setObjectName("tkTabs")
        w.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        h = QHBoxLayout(w)
        h.setContentsMargins(12, 0, 12, 0)
        h.setSpacing(2)
        self.tab_group = QButtonGroup(self)
        self.tab_group.setExclusive(True)
        for i, name in enumerate(("👁️ Visualizza", "🖍️ Annota", "✍️ Firma e moduli", "✏️ Modifica testo", "📄 Pagine")):
            b = QPushButton(name)
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            self.tab_group.addButton(b, i)
            h.addWidget(b)
        h.addStretch(1)
        self.tab_group.idClicked.connect(self._set_tab)
        return w

    def _tbtn(self, text, tip, tool=None, slot=None, menu=None, checkable=False):
        b = QToolButton()
        b.setText(text)
        b.setToolTip(shortcut_text(tip))
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        if tool is not None:
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, t=tool: self._usa_strumento(t))
            self._tool_buttons.setdefault(tool, []).append(b)
        elif checkable:
            b.setCheckable(True)
        if slot:
            b.clicked.connect(slot)
        if menu is not None:
            b.setMenu(menu)
            b.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._doc_actions.append(b)
        return b

    def _tool_row(self, widgets):
        page = QWidget()
        h = QHBoxLayout(page)
        h.setContentsMargins(14, 7, 14, 7)
        h.setSpacing(6)
        for wd in widgets:
            if wd is None:
                h.addWidget(_sep())
            elif wd == "stretch":
                h.addStretch(1)
            else:
                h.addWidget(wd)
        if "stretch" not in widgets:
            h.addStretch(1)
        # su schermi stretti la riga scorre invece di allargare la finestra
        area = QScrollArea()
        area.setWidget(page)
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        area.setFixedHeight(page.sizeHint().height() + 10)
        area.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: white; }"
                           "QScrollBar:horizontal { height: 6px; }")
        return area

    def _small_label(self, text):
        lab = QLabel(text)
        lab.setStyleSheet("color:#64748b;")
        return lab

    def _build_tools(self):
        w = QWidget()
        w.setObjectName("tkTools")
        w.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        self.tools_stack = QStackedWidget()
        v.addWidget(self.tools_stack)

        # --- Visualizza
        self.btn_thumbs = self._tbtn("▦ Miniature", "Mostra/nascondi le miniature", checkable=True,
                                     slot=lambda: self._toggle_thumbs())
        view_row = [
            self._tbtn("🖱️ Seleziona", "Seleziona testo, annotazioni e campi", tool=Tool.SELECT),
            self._tbtn("✋ Mano", "Trascina per scorrere", tool=Tool.HAND),
            None,
            self._tbtn("↔️ Adatta larghezza", "Adatta alla larghezza (Ctrl+0)", slot=lambda: self.view.set_fit("width")),
            self._tbtn("🗎 Pagina intera", "Mostra la pagina intera", slot=lambda: self.view.set_fit("page")),
            self._tbtn("100%", "Dimensione reale", slot=lambda: self.view.set_zoom(1.0)),
            None,
            self.btn_thumbs,
            self._tbtn("🔍 Cerca", "Cerca nel documento (Ctrl+F)", slot=self.show_search),
            self._tbtn("📋 Copia testo", "Copia il testo selezionato (Ctrl+C)", slot=self.view.copy_selection),
        ]
        self.tools_stack.addWidget(self._tool_row(view_row))

        # --- Annota
        self.hl_color = ColorButton(self.view.markup_color[Tool.HIGHLIGHT])
        self.hl_color.setToolTip("Colore evidenziatore")
        self.hl_color.colorChanged.connect(lambda c: self.view.markup_color.__setitem__(Tool.HIGHLIGHT, c))
        self.draw_color = ColorButton(self.view.draw_color)
        self.draw_color.setToolTip("Colore di penna, forme e frecce")
        self.draw_color.colorChanged.connect(lambda c: setattr(self.view, "draw_color", c))
        self.draw_width = QDoubleSpinBox()
        self.draw_width.setRange(0.5, 20)
        self.draw_width.setSingleStep(0.5)
        self.draw_width.setValue(self.view.draw_width)
        self.draw_width.setSuffix(" pt")
        self.draw_width.setToolTip("Spessore del tratto")
        self.draw_width.valueChanged.connect(lambda v_: setattr(self.view, "draw_width", v_))
        self.fill_shapes = QCheckBox("Riempi")
        self.fill_shapes.setToolTip("Riempi rettangoli ed ellissi con colore trasparente")
        self.fill_shapes.toggled.connect(lambda on: setattr(self.view, "fill_shapes", on))
        annot_row = [
            self._tbtn("🖱️", "Seleziona / sposta annotazioni", tool=Tool.SELECT),
            self._tbtn("🖍️ Evidenzia", "Evidenzia il testo", tool=Tool.HIGHLIGHT),
            self.hl_color,
            self._tbtn("U̲ Sottolinea", "Sottolinea il testo", tool=Tool.UNDERLINE),
            self._tbtn("S̶ Barra", "Barra il testo", tool=Tool.STRIKE),
            None,
            self._tbtn("💬 Nota", "Aggiungi una nota adesiva", tool=Tool.NOTE),
            self._tbtn("🔤 Casella di testo", "Aggiungi una casella di testo spostabile", tool=Tool.TEXTBOX),
            None,
            self._tbtn("✏️ Penna", "Disegno a mano libera", tool=Tool.INK),
            self._tbtn("▭ Rettangolo", "Disegna un rettangolo", tool=Tool.RECT),
            self._tbtn("◯ Ellisse", "Disegna un'ellisse", tool=Tool.ELLIPSE),
            self._tbtn("➜ Freccia", "Disegna una freccia", tool=Tool.ARROW),
            None,
            self._small_label("Colore"), self.draw_color, self.draw_width, self.fill_shapes,
        ]
        self.tools_stack.addWidget(self._tool_row(annot_row))

        # --- Firma e moduli
        self.sign_menu = QMenu(self)
        self.sign_menu.aboutToShow.connect(self._build_sign_menu)
        stamp_menu = QMenu(self)
        for text, color in STAMPS:
            act = stamp_menu.addAction(f"●  {text}")
            act.triggered.connect(lambda _=False, t=text, c=color: self.view.start_stamp(t, QColor(c)))
        stamp_menu.addSeparator()
        stamp_menu.addAction("✏️ Personalizzato…", self.custom_stamp)
        self.btn_fields = self._tbtn("🟦 Evidenzia campi", "Mostra i campi compilabili", checkable=True,
                                     slot=lambda: self._toggle_fields())
        self.btn_fields.setChecked(True)
        sign_row = [
            self._tbtn("✍️ Firma", "Inserisci la tua firma", menu=self.sign_menu),
            self._tbtn("🖼️ Immagine", "Inserisci un'immagine", slot=self.insert_image),
            self._tbtn("🔖 Timbro", "Applica un timbro", menu=stamp_menu),
            self._tbtn("📝 Aggiungi testo", "Scrivi testo sulla pagina (per moduli non compilabili)", tool=Tool.ADD_TEXT),
            self._tbtn("✔ Spunta", "Inserisci segni di spunta (Esc per finire)", slot=self._checkmark),
            None,
            self._tbtn("🖱️ Compila campi", "Clicca sui campi del modulo per compilarli", tool=Tool.SELECT),
            self.btn_fields,
            self._tbtn("🧹 Svuota modulo", "Cancella tutti i valori dei campi", slot=self.clear_form),
            self._tbtn("📌 Appiattisci", "Rende definitivi campi e annotazioni (non più modificabili)", slot=self.flatten),
        ]
        self.tools_stack.addWidget(self._tool_row(sign_row))

        # --- Modifica testo
        edit_row = [
            self._tbtn("✏️ Modifica testo", "Clicca su una riga per modificarla", tool=Tool.EDIT_TEXT),
            self._tbtn("📝 Aggiungi testo", "Scrivi nuovo testo sulla pagina", tool=Tool.ADD_TEXT),
            self._tbtn("🩹 Bianchetto", "Cancella un'area della pagina", tool=Tool.WHITEOUT),
            self._tbtn("🧩 Oggetti", "Sposta, ridimensiona, ricolora ed elimina sfondi, riquadri, righe e immagini "
                                    "(pagine create con «Da foto a PDF»)", tool=Tool.OBJECTS),
            None,
            self._small_label("Funziona al meglio su PDF creati da programmi (Word, gestionali). "
                              "Sulle scansioni usa Bianchetto + Aggiungi testo."),
        ]
        self.tools_stack.addWidget(self._tool_row(edit_row))

        # --- Pagine
        pages_row = [
            self._tbtn("↺ Ruota", "Ruota a sinistra le pagine selezionate", slot=lambda: self.rotate_pages(-90)),
            self._tbtn("↻ Ruota", "Ruota a destra le pagine selezionate", slot=lambda: self.rotate_pages(90)),
            self._tbtn("🗑️ Elimina", "Elimina le pagine selezionate", slot=self.delete_pages),
            self._tbtn("📑 Duplica", "Duplica le pagine selezionate", slot=self.duplicate_pages),
            self._tbtn("➕ Pagina vuota", "Inserisci una pagina vuota dopo quella corrente", slot=self.insert_blank),
            self._tbtn("📥 Inserisci file", "Inserisci PDF o immagini dopo la pagina corrente", slot=self.insert_files),
            self._tbtn("📷 Da foto", "Aggiungi in fondo le foto di documenti, ritagliate e raddrizzate",
                       slot=self.photo_to_pdf),
            None,
            self._tbtn("🔗 Unisci", "Aggiungi altri PDF in fondo", slot=self.merge_dialog),
            self._tbtn("✂️ Dividi", "Dividi il PDF in più file", slot=self.split),
            self._tbtn("📤 Estrai", "Salva le pagine selezionate in un nuovo PDF", slot=self.extract_pages),
            None,
            self._tbtn("🗜️ Comprimi", "Riduci la dimensione del file", slot=self.compress),
            self._tbtn("🔒 Password", "Salva una copia protetta da password", slot=self.protect),
            None,
            self._small_label("Trascina le miniature per riordinare"),
        ]
        self.tools_stack.addWidget(self._tool_row(pages_row))
        return w

    def _build_welcome(self):
        w = QWidget()
        w.setObjectName("tkWelcome")
        w.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        outer = QVBoxLayout(w)
        outer.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        card = QWidget()
        card.setObjectName("tkWelcomeCard")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        card.setMaximumWidth(620)
        card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        c = QVBoxLayout(card)
        c.setContentsMargins(40, 34, 40, 30)
        c.setSpacing(10)
        ic = QLabel()
        ic.setPixmap(self.icon.pixmap(84, 84))
        c.addWidget(ic, alignment=Qt.AlignmentFlag.AlignHCenter)
        t = QLabel(APP_TITLE)
        t.setObjectName("tkWelcomeTitle")
        c.addWidget(t, alignment=Qt.AlignmentFlag.AlignHCenter)
        sub = QLabel("Apri, annota, firma, scansiona e modifica i tuoi PDF.\nPuoi anche trascinare qui un file.")
        sub.setObjectName("tkWelcomeSub")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        c.addWidget(sub)
        c.addSpacing(8)
        btns = QHBoxLayout()
        open_b = QPushButton("📂  Apri PDF")
        open_b.setObjectName("accent")
        open_b.setMinimumHeight(42)
        open_b.clicked.connect(self.open_dialog)
        merge_b = QPushButton("🔗  Unisci PDF o immagini")
        merge_b.setMinimumHeight(42)
        merge_b.clicked.connect(self.merge_dialog)
        photo_b = QPushButton("📷  Da foto a PDF")
        photo_b.setMinimumHeight(42)
        photo_b.setToolTip("Trasforma le foto di documenti in un PDF: ritaglio, raddrizzamento e sfondo bianco")
        photo_b.clicked.connect(self.photo_to_pdf)
        for b in (open_b, photo_b, merge_b):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            btns.addWidget(b)
        c.addLayout(btns)
        c.addSpacing(10)
        self.recent_title = QLabel("FILE RECENTI")
        self.recent_title.setStyleSheet("color:#64748b; font-size:11px; font-weight:700;")
        c.addWidget(self.recent_title)
        self.recent_list = QListWidget()
        self.recent_list.setObjectName("tkRecent")
        self.recent_list.setMaximumHeight(260)
        self.recent_list.setIconSize(QSize(RECENT_THUMB_W, RECENT_THUMB_H))
        self.recent_list.setCursor(Qt.CursorShape.PointingHandCursor)
        self.recent_list.itemActivated.connect(lambda it: self.open_path(it.data(Qt.ItemDataRole.UserRole)))
        self.recent_list.itemClicked.connect(lambda it: self.open_path(it.data(Qt.ItemDataRole.UserRole)))
        c.addWidget(self.recent_list)
        foot = QLabel(f"<span style='color:#94a3b8;font-size:11px'>v{VERSION} · creato da <b>{AUTHOR}</b></span>")
        c.addWidget(foot, alignment=Qt.AlignmentFlag.AlignHCenter)
        row.addWidget(card, 3)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(2)
        return w

    def _build_doc_area(self):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        h.addWidget(self.thumbs)
        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)

        self.search_bar = QWidget()
        self.search_bar.setObjectName("tkSearch")
        self.search_bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        s = QHBoxLayout(self.search_bar)
        s.setContentsMargins(12, 6, 12, 6)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Cerca nel documento…")
        self.search_edit.setMaximumWidth(360)
        self.search_edit.returnPressed.connect(lambda: self._search_step(1))
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._run_search)
        self.search_edit.textChanged.connect(lambda: self._search_timer.start(350))
        self.search_count = QLabel("")
        self.search_count.setStyleSheet("color:#64748b; padding: 0 8px;")
        prev_b = QPushButton("▲")
        next_b = QPushButton("▼")
        close_b = QPushButton("✕")
        prev_b.clicked.connect(lambda: self._search_step(-1))
        next_b.clicked.connect(lambda: self._search_step(1))
        close_b.clicked.connect(self.hide_search)
        s.addWidget(QLabel("🔍"))
        s.addWidget(self.search_edit)
        for b in (prev_b, next_b):
            b.setFixedWidth(40)
            s.addWidget(b)
        s.addWidget(self.search_count)
        s.addStretch(1)
        s.addWidget(close_b)
        self.search_bar.hide()
        right.addWidget(self.search_bar)
        right.addWidget(self.view, 1)
        h.addLayout(right, 1)
        return w

    def _build_shortcuts(self):
        def act(keys, slot):
            a = QAction(self)
            a.setShortcuts([QKeySequence(k) for k in keys])
            a.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
            a.triggered.connect(slot)
            self.addAction(a)
            return a

        act(["Ctrl+O"], self.open_dialog)
        act(["Ctrl+S"], self.save)
        act(["Ctrl+Shift+S"], self.save_as)
        act(["Ctrl+P"], self.print_doc)
        act(["Ctrl+W"], self.close_document)
        act(["Ctrl+F"], self.show_search)
        act(["F3"], lambda: self._search_step(1))
        act(["Shift+F3"], lambda: self._search_step(-1))
        act(["Ctrl++", "Ctrl+="], lambda: self.pdf.is_open and self.view.set_zoom(self.view.zoom * 1.2))
        act(["Ctrl+-"], lambda: self.pdf.is_open and self.view.set_zoom(self.view.zoom / 1.2))
        act(["Ctrl+0"], lambda: self.pdf.is_open and self.view.set_fit("width"))
        self._undo_act = act(["Ctrl+Z"], self._undo)
        self._redo_act = act(["Ctrl+Y", "Ctrl+Shift+Z"], self._redo)

    def _undo(self):
        if isinstance(QApplication.focusWidget(), QLineEdit):
            QApplication.focusWidget().undo()
            return
        self.pdf.undo()

    def _redo(self):
        if isinstance(QApplication.focusWidget(), QLineEdit):
            QApplication.focusWidget().redo()
            return
        self.pdf.redo()

    def _connect(self):
        self.pdf.stateChanged.connect(self.update_state)
        self.pdf.changed.connect(lambda _: (self._update_page_label(), self.thumbs.set_current(self.view.current_page())))
        self.view.currentPageChanged.connect(self._on_page_changed)
        self.view.zoomChanged.connect(self._on_zoom)
        self.view.toolChanged.connect(self._on_tool)
        self.view.message.connect(self.show_message)
        self.thumbs.pageActivated.connect(lambda p: self.view.go_to_page(p))
        self.thumbs.reordered.connect(self.reorder_pages)
        self.thumbs.customContextMenuRequested.connect(self._thumb_menu)

    # ================================================================ stato
    def update_state(self):
        is_open = self.pdf.is_open
        self.stack.setCurrentIndex(1 if is_open else 0)
        for w in self._doc_actions:
            w.setEnabled(is_open)
        self.btn_undo.setEnabled(is_open and self.pdf.can_undo)
        self.btn_redo.setEnabled(is_open and self.pdf.can_redo)
        if is_open:
            name = self.pdf.title()
            self.setWindowTitle(f"{'● ' if self.pdf.dirty else ''}{name} — {APP_TITLE}")
            lock = " 🔒" if self.pdf.password else ""
            self.file_label.setText(f"{'● ' if self.pdf.dirty else ''}{name}{lock}")
        else:
            self.setWindowTitle(APP_TITLE)
            self.file_label.setText(f"v{VERSION}")
            self._fill_recent()
        self._update_page_label()

    def _update_page_label(self):
        n = self.pdf.page_count
        cur = self.view.current_page() + 1 if n else 0
        self.page_total.setText(f"/ {n}")
        if not self.page_edit.hasFocus():
            self.page_edit.setText(str(cur) if n else "")
        self.status_page.setText(f"Pagina {cur} di {n}   ·   {round(self.view.zoom * 100)}%" if n else "")

    def _on_page_changed(self, pno):
        self.thumbs.set_current(pno)
        self._update_page_label()

    def _on_zoom(self, z):
        self.zoom_combo.blockSignals(True)
        if self.view.fit_mode == "width":
            self.zoom_combo.setEditText(FIT_WIDTH)
        elif self.view.fit_mode == "page":
            self.zoom_combo.setEditText(FIT_PAGE)
        else:
            self.zoom_combo.setEditText(f"{round(z * 100)}%")
        self.zoom_combo.blockSignals(False)
        self._update_page_label()

    def _zoom_from_combo(self, text):
        if text == FIT_WIDTH:
            self.view.set_fit("width")
        elif text == FIT_PAGE:
            self.view.set_fit("page")
        else:
            try:
                value = float(text.replace("%", "").replace(",", ".").strip())
                self.view.set_zoom(value / 100.0)
            except ValueError:
                self._on_zoom(self.view.zoom)
        self.view.setFocus()

    def _goto_page_edit(self):
        try:
            self.view.go_to_page(int(self.page_edit.text()) - 1)
        except ValueError:
            pass
        self.view.setFocus()
        self._update_page_label()

    def _usa_strumento(self, tool):
        self.view.set_tool(tool)

    def _on_tool(self, tool):
        for t, buttons in self._tool_buttons.items():
            for b in buttons:
                b.setChecked(t == tool)
        self._hint = TOOL_HINTS.get(tool, "")
        if not self._msg_timer.isActive():
            self.status_msg.setText(self._hint)

    def show_message(self, text):
        if text in TOOL_HINTS.values():
            self._hint = text
            if not self._msg_timer.isActive():
                self.status_msg.setText(text)
            return
        self.status_msg.setText(text)
        self._msg_timer.start(5000)

    def _set_tab(self, index):
        self.tab_group.button(index).setChecked(True)
        self.tools_stack.setCurrentIndex(index)
        tool = self.view.tool
        if index == 3:
            if tool not in (Tool.EDIT_TEXT, Tool.ADD_TEXT, Tool.WHITEOUT, Tool.OBJECTS):
                self.view.set_tool(Tool.EDIT_TEXT)
        elif index == 1:
            if tool not in {Tool.SELECT, Tool.HIGHLIGHT, Tool.UNDERLINE, Tool.STRIKE, Tool.NOTE, Tool.TEXTBOX,
                            Tool.INK, Tool.RECT, Tool.ELLIPSE, Tool.ARROW}:
                self.view.set_tool(Tool.SELECT)
        elif index == 2:
            if tool not in (Tool.SELECT, Tool.ADD_TEXT, Tool.IMAGE, Tool.STAMP):
                self.view.set_tool(Tool.SELECT)
        elif tool not in (Tool.SELECT, Tool.HAND):
            self.view.set_tool(Tool.SELECT)
        self._on_tool(self.view.tool)

    def _toggle_thumbs(self):
        self.thumbs.setVisible(self.btn_thumbs.isChecked())
        self.settings.setValue("thumbs", self.thumbs.isVisible())

    def _toggle_fields(self):
        self.view.show_fields = self.btn_fields.isChecked()
        for it in self.view.pages:
            it.update()

    def _build_main_menu(self):
        m = self.main_menu
        m.clear()
        is_open = self.pdf.is_open
        m.addAction("📂 Apri…\tCtrl+O", self.open_dialog)
        recent = self._recent()
        if recent:
            sub = m.addMenu("🕘 Recenti")
            for path in recent:
                sub.addAction(os.path.basename(path), lambda p=path: self.open_path(p)).setToolTip(path)
        m.addAction("🔗 Unisci PDF o immagini…", self.merge_dialog)
        m.addAction("📷 Da foto a PDF…", self.photo_to_pdf)
        m.addSeparator()
        for text, slot, need in (("💾 Salva\tCtrl+S", self.save, True),
                                 ("💾 Salva con nome…\tCtrl+Shift+S", self.save_as, True),
                                 ("🔒 Salva con password…", self.protect, True)):
            m.addAction(text, slot).setEnabled(is_open)
        if is_open and self.pdf.password:
            m.addAction("🔓 Rimuovi password", self.remove_password)
        m.addAction("🖨️ Stampa…\tCtrl+P", self.print_doc).setEnabled(is_open)
        if self._renamed_save:
            m.addAction("❓ Perché il file viene salvato con un altro nome?", self.show_protection_help)
        m.addAction("📁 Mostra nella cartella", self.show_in_folder).setEnabled(bool(is_open and self.pdf.path))
        m.addAction("✖ Chiudi documento\tCtrl+W", self.close_document).setEnabled(is_open)
        m.addSeparator()
        if sys.platform == "win32":
            m.addAction("📌 Usa tk-pdf per aprire i PDF…", self.make_default)
        m.addAction("🔄 Cerca aggiornamenti…", lambda: self.updates.check(manual=True))
        m.addAction("ℹ️ Informazioni", self.show_about)
        if IS_MAC:
            for a in m.actions():
                a.setText(shortcut_text(a.text()))

    # ================================================================ file
    def show_about(self):
        """Informazioni: finestra comune a tutti i software TK (libreria), colore di tk-pdf."""
        from PySide6.QtGui import QDesktopServices, QPixmap
        from tkpdf import AUTHOR_URL, pro, webfonts
        from tkpdf.icon import render_icon
        from tkpdf.tk_licenza_qt import InformazioniDialog
        from tkpdf.util import app_data_dir
        font = QCheckBox("Scarica da Google Fonts i caratteri mancanti")
        font.setChecked(webfonts.consent() is True)
        font.toggled.connect(webfonts.set_consent)
        InformazioniDialog(
            pro.licenza(), APP_TITLE, VERSION, "Lettore ed editor PDF: leggi, annota, firma e modifica i PDF.",
            QPixmap.fromImage(render_icon(136)), "#e11d48",
            dati=[("I tuoi dati", app_data_dir(), "Firme salvate e impostazioni restano su questo computer.")],
            url_sorgente=pro.URL_SORGENTE, cartella_licenze=pro.cartella_licenze(),
            su_aggiornamenti=lambda: self.updates.check(manual=True),
            caselle=[(font, "Solo quando riscrivi un testo con un carattere che manca nel PDF. Google riceve "
                            "l'indirizzo IP e il nome del font; senza, si usa un font simile.")],
            pulsanti=[("C'è anche per Android", lambda: QDesktopServices.openUrl(QUrl(AUTHOR_URL + "/app/")))],
            parent=self).exec()

    def _recent(self):
        items = self.settings.value("recent", [], type=list) or []
        seen, out = set(), []
        for p in items:
            if not isinstance(p, str) or not os.path.exists(p):
                continue
            key = os.path.normcase(os.path.abspath(p))
            if key not in seen:
                seen.add(key)
                out.append(os.path.abspath(p))
        return out

    def _add_recent(self, path):
        path = os.path.abspath(path)
        items = [p for p in self._recent() if os.path.normcase(p) != os.path.normcase(path)]
        items.insert(0, path)
        self.settings.setValue("recent", items[:12])

    def _fill_recent(self):
        self.recent_list.clear()
        recent = self._recent()
        self.recent_title.setVisible(bool(recent))
        self.recent_list.setVisible(bool(recent))
        for path in recent[:8]:
            item = QListWidgetItem(f"  {os.path.basename(path)}")
            item.setToolTip(path)
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setIcon(self._recent_thumb(path))
            self.recent_list.addItem(item)

    def _recent_thumb(self, path):
        """Prima pagina in miniatura, come nell'app per telefono."""
        cached = self._thumb_cache.get(path)
        if cached is not None:
            return cached
        icon = QIcon()
        try:
            doc = fitz.open(path)
            try:
                if doc.page_count and not doc.needs_pass:
                    page = doc[0]
                    zoom = RECENT_THUMB_H / max(1.0, page.rect.height)
                    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
                    img = pix_to_qimage(pix)
                    canvas = QImage(RECENT_THUMB_W, RECENT_THUMB_H, QImage.Format.Format_ARGB32)
                    canvas.fill(Qt.GlobalColor.transparent)
                    p = QPainter(canvas)
                    x = (RECENT_THUMB_W - img.width()) // 2
                    p.fillRect(x - 1, -1, img.width() + 2, img.height() + 2, QColor("#cbd5e1"))
                    p.drawImage(x, 0, img)
                    p.end()
                    icon = QIcon(QPixmap.fromImage(canvas))
            finally:
                doc.close()
        except Exception:
            pass
        self._thumb_cache[path] = icon
        return icon

    def _last_dir(self):
        return self.settings.value("last_dir", os.path.join(os.path.expanduser("~"), "Documents"))

    def open_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Apri PDF", self._last_dir(), OPEN_FILTER)
        if path:
            self.open_path(path)

    def open_path(self, path):
        if not path or not os.path.exists(path):
            QMessageBox.warning(self, APP_TITLE, "Il file non esiste più.")
            return
        if not self.maybe_save():
            return
        password = None
        while True:
            try:
                QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
                self.view.reset_position()
                self.pdf.open_file(path, password)
                break
            except PasswordRequired:
                QApplication.restoreOverrideCursor()
                dlg = PasswordDialog(self, title="Documento protetto",
                                     message=f"«{os.path.basename(path)}» è protetto da password." +
                                             ("\nPassword errata, riprova." if password else ""))
                if not dlg.exec():
                    return
                password = dlg.password()
            except Exception as exc:
                QApplication.restoreOverrideCursor()
                QMessageBox.critical(self, APP_TITLE, f"Impossibile aprire il file:\n{exc}")
                return
            finally:
                if QApplication.overrideCursor():
                    QApplication.restoreOverrideCursor()
        self.settings.setValue("last_dir", os.path.dirname(path))
        if path.lower().endswith(".pdf"):
            self._add_recent(path)
        self.view.set_tool(Tool.SELECT)
        self.view.setFocus()
        self.update_state()
        if self.pdf.doc.is_form_pdf:
            self._set_tab(2)
            self.show_message("📝 Questo PDF contiene campi compilabili: clicca su un campo per scriverci")
        QTimer.singleShot(0, self._warn_on_open)

    def _warn_on_open(self):
        """Firme digitali e limitazioni dell'autore: si dice subito, non si tolgono in silenzio."""
        if not self.pdf.is_open:
            return
        notes = []
        if self.pdf.signed_path:
            notes.append("Contiene <b>firme digitali</b>: se salvi sopra l'originale non saranno più valide. "
                         "Per conservarle salva le modifiche con «Salva con nome».")
        if self.pdf.restrictions:
            notes.append("L'autore ha limitato: <b>" + ", ".join(self.pdf.restrictions) + "</b>. "
                         "tk-pdf non applica queste limitazioni e il file salvato non le avrà più: "
                         "rispetta la volontà dell'autore e i diritti sul documento.")
        if not notes:
            return
        box = QMessageBox(self)
        box.setWindowTitle(APP_TITLE)
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(f"Prima di modificare «{self.pdf.title()}»")
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setInformativeText("<br><br>".join(notes))
        box.addButton("Ho capito", QMessageBox.ButtonRole.AcceptRole)
        box.exec()

    def _file_bytes(self, path):
        password = None
        while True:
            try:
                return PdfDocument.file_to_pdf_bytes(path, password)
            except PasswordRequired:
                dlg = PasswordDialog(self, title="Documento protetto",
                                     message=f"«{os.path.basename(path)}» è protetto da password.")
                if not dlg.exec():
                    return None
                password = dlg.password()

    def maybe_save(self):
        if not self.pdf.dirty:
            return True
        box = QMessageBox(self)
        box.setWindowTitle(APP_TITLE)
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(f"Vuoi salvare le modifiche a «{self.pdf.title()}»?")
        save = box.addButton("Salva", QMessageBox.ButtonRole.AcceptRole)
        discard = box.addButton("Non salvare", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Annulla", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is save:
            return self.save()
        return box.clickedButton() is discard

    def save(self):
        if not self.pdf.is_open:
            return False
        if not self.pdf.path:
            return self.save_as()
        return self._save_to(self.pdf.path)

    def save_as(self, password=None, suggested=None):
        if not self.pdf.is_open:
            return False
        if not isinstance(password, str):
            password = None   # dai pulsanti e dal menu arriva «checked» (False): la password attuale resta
        base = suggested or self.pdf.path or os.path.join(self._last_dir(), self.pdf.title())
        path, _ = QFileDialog.getSaveFileName(self, "Salva PDF", base, "PDF (*.pdf)")
        if not path:
            return False
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        return self._save_to(path, password)

    def _ask_signed_overwrite(self, path):
        """Sopra un PDF con firme digitali: le firme non varrebbero più. Propone «Salva con nome»."""
        signed = self.pdf.signed_path
        if not signed or os.path.normcase(os.path.abspath(signed)) != os.path.normcase(os.path.abspath(path)):
            return "ok"
        box = QMessageBox(self)
        box.setWindowTitle(APP_TITLE)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText("Questo PDF contiene firme digitali.")
        box.setInformativeText("Se lo salvi sopra l'originale, le firme digitali non saranno più valide. "
                               "Con «Salva con nome» le modifiche vanno in una copia e l'originale firmato resta intatto.")
        other = box.addButton("Salva con nome…", QMessageBox.ButtonRole.AcceptRole)
        over = box.addButton("Sovrascrivi comunque", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Annulla", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(other)
        box.exec()
        if box.clickedButton() is other:
            return "save_as"
        if box.clickedButton() is over:
            self.pdf.signed_path = None
            return "ok"
        return "cancel"

    def _ask_read_only(self, path):
        """File in sola lettura: si toglie la protezione solo se l'utente lo chiede, altrimenti una copia."""
        box = QMessageBox(self)
        box.setWindowTitle(APP_TITLE)
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(f"«{os.path.basename(path)}» è in sola lettura.")
        box.setInformativeText("Vuoi salvare le modifiche in una copia accanto all'originale, oppure togliere la "
                               "sola lettura e sovrascriverlo? (dopo il salvataggio la sola lettura viene rimessa)")
        copy_b = box.addButton("Salva una copia", QMessageBox.ButtonRole.AcceptRole)
        over_b = box.addButton("Sovrascrivi", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Annulla", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(copy_b)
        box.exec()
        return {copy_b: "copy", over_b: "overwrite"}.get(box.clickedButton(), "cancel")

    def _save_to(self, path, password=None, allow_copy=True, allow_read_only=False):
        """Salva. Se Windows nega la modifica del file, salva da solo una copia numerata accanto."""
        choice = self._ask_signed_overwrite(path)
        if choice == "save_as":
            return self.save_as(password)
        if choice == "cancel":
            return False
        try:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            size = self.pdf.save(path, password, allow_read_only=allow_read_only)
        except ReadOnlyError:
            QApplication.restoreOverrideCursor()
            choice = self._ask_read_only(path)
            if choice == "overwrite":
                return self._save_to(path, password, allow_copy, allow_read_only=True)
            if choice == "copy":
                return self._save_copy(path, password)
            return False
        except (SaveError, PermissionError) as exc:
            QApplication.restoreOverrideCursor()
            err = exc if isinstance(exc, SaveError) else SaveError(f"Impossibile salvare il file:\n{exc}")
            # il file esistente è protetto, ma creare un file nuovo di solito si può
            if allow_copy:
                if not self._save_copy(path, password, err):
                    return False
                if not self._renamed_save:  # la spiegazione una volta sola, poi resta nel menu
                    self._renamed_save = True
                    QTimer.singleShot(0, self.show_protection_help)
                return True
            return self._save_failed(err, path, password)
        except Exception as exc:
            QMessageBox.critical(self, APP_TITLE, f"Errore durante il salvataggio:\n{exc}")
            return False
        finally:
            QApplication.restoreOverrideCursor()
        self._saved(path, size)
        self.show_message(f"💾 Salvato: {os.path.basename(path)} ({human_size(size)})")
        return True

    def _save_copy(self, path, password, err=None):
        """Salva una copia numerata accanto all'originale («documento (1).pdf»): l'originale non si tocca."""
        copy = free_name(path)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            size = self.pdf.save(copy, password)
        except Exception as exc:
            QApplication.restoreOverrideCursor()
            if not isinstance(err, SaveError):
                err = exc if isinstance(exc, SaveError) else SaveError(f"Impossibile salvare il file:\n{exc}")
            self._save_failed(err, path, password)
            return False
        QApplication.restoreOverrideCursor()
        self._saved(copy, size)
        self.show_message(f"💾 «{os.path.basename(path)}» non si lascia modificare: "
                          f"salvato come «{os.path.basename(copy)}»")
        return True

    def show_protection_help(self):
        """Come autorizzare tk-pdf nell'antivirus, così torna a sovrascrivere i file."""
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            text, app_path = protection_help()
        finally:
            QApplication.restoreOverrideCursor()
        if app_path:
            QApplication.clipboard().setText(app_path)
        box = QMessageBox(self)
        box.setWindowTitle(APP_TITLE)
        box.setIcon(QMessageBox.Icon.Information)
        box.setText("Il file è stato salvato con un altro nome")
        box.setInformativeText(text)
        box.addButton("Ho capito", QMessageBox.ButtonRole.AcceptRole)
        box.exec()

    def _saved(self, path, size):
        self._add_recent(path)
        self.settings.setValue("last_dir", os.path.dirname(path))
        self.update_state()

    def _save_failed(self, exc, path, password):
        """Spiega perché il salvataggio non è riuscito e offre Riprova / Salva con nome."""
        box = QMessageBox(self)
        box.setWindowTitle(APP_TITLE)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(f"Non sono riuscito a salvare «{os.path.basename(path)}».")
        box.setInformativeText(str(exc))
        retry = box.addButton("Riprova", QMessageBox.ButtonRole.AcceptRole) if exc.can_retry else None
        other = box.addButton("Salva con nome…", QMessageBox.ButtonRole.ActionRole)
        box.addButton("Annulla", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if retry is not None and box.clickedButton() is retry:
            return self._save_to(path, password, allow_copy=False)
        if box.clickedButton() is other:
            return self.save_as(password)
        return False

    def protect(self):
        if not self.pdf.is_open:
            return
        dlg = PasswordDialog(self, confirm=True, title="Proteggi con password",
                             message="Chi apre il file dovrà inserire questa password.")
        if dlg.exec():
            self.save_as(password=dlg.password())

    def remove_password(self):
        if self.pdf.path and QMessageBox.question(self, APP_TITLE, "Salvare il file senza password?") == \
                QMessageBox.StandardButton.Yes:
            self._save_to(self.pdf.path, "")

    def close_document(self):
        if self.pdf.is_open and self.maybe_save():
            self.hide_search()
            self.pdf.close()
            self.update_state()

    def show_in_folder(self):
        if self.pdf.path:
            import subprocess
            if IS_MAC:
                subprocess.Popen(["open", "-R", self.pdf.path])
            else:
                subprocess.Popen(["explorer", "/select,", os.path.normpath(self.pdf.path)])

    def make_default(self):
        try:
            from tkpdf.winreg_assoc import register
            register()
        except Exception as exc:
            QMessageBox.warning(self, APP_TITLE, f"Registrazione non riuscita:\n{exc}")
            return
        QMessageBox.information(self, APP_TITLE,
                                "tk-pdf è registrato per i file PDF.\n\nNella finestra che si apre clicca su «.pdf» "
                                "e scegli tk-pdf (Windows non permette alle app di impostarsi da sole come predefinite).")
        # pagina di tk-pdf in Impostazioni → App predefinite (Windows 11); se non supportata, elenco generale
        if not QDesktopServices.openUrl(QUrl("ms-settings:defaultapps?registeredAppUser=TK%20PDF")):
            QDesktopServices.openUrl(QUrl("ms-settings:defaultapps"))

    # ================================================================ drag & drop
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        paths = [p for p in paths if os.path.isfile(p)]
        if not paths:
            return
        if not self.pdf.is_open:
            if len(paths) == 1:
                self.open_path(paths[0])
            else:
                self.merge_files(paths, into_current=False)
            return
        box = QMessageBox(self)
        box.setWindowTitle(APP_TITLE)
        box.setText("Cosa vuoi fare con i file trascinati?")
        open_b = box.addButton("Apri", QMessageBox.ButtonRole.AcceptRole) if len(paths) == 1 else None
        add_b = box.addButton("Aggiungi in fondo", QMessageBox.ButtonRole.ActionRole)
        box.addButton("Annulla", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if open_b is not None and box.clickedButton() is open_b:
            self.open_path(paths[0])
        elif box.clickedButton() is add_b:
            self.merge_files(paths, into_current=True)

    def show_update_button(self, version):
        if version:
            self.btn_update.setText(f"⬆️ Aggiorna a {version}")
            self.btn_update.show()
        else:
            self.btn_update.hide()

    def closeEvent(self, e):
        # durante l'aggiornamento le modifiche sono già state salvate (o scartate) dall'utente
        if not self.closing_for_update and not self.maybe_save():
            e.ignore()
            return
        self.settings.setValue("geometry", self.saveGeometry())
        e.accept()

    # ================================================================ ricerca
    def show_search(self):
        if not self.pdf.is_open:
            return
        self.search_bar.show()
        self.search_edit.setFocus()
        self.search_edit.selectAll()

    def hide_search(self):
        self.search_bar.hide()
        self.search_edit.clear()
        self.view.search("")
        self.view.setFocus()

    def _run_search(self):
        text = self.search_edit.text().strip()
        if len(text) < 2 and text:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            total = self.view.search(text)
        finally:
            QApplication.restoreOverrideCursor()
        self.search_count.setText("" if not text else (f"{total} risultati" if total else "Nessun risultato"))
        if total:
            self._search_step(1)

    def _search_step(self, step):
        if self._search_timer.isActive():
            self._search_timer.stop()
            self._run_search()
            return
        res = self.view.search_step(step)
        if res:
            self.search_count.setText(f"{res[0]} di {res[1]}")

    # ================================================================ firma / immagini
    def _build_sign_menu(self):
        m = self.sign_menu
        m.clear()
        files = saved_signatures()
        for path in files[:6]:
            btn = QToolButton()
            btn.setIcon(QIcon(path))
            btn.setIconSize(QSize(170, 56))
            btn.setAutoRaise(True)
            btn.setToolTip("Usa questa firma")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet("QToolButton{background:white;border:1px solid #e2e8f0;border-radius:6px;padding:6px;margin:3px 6px;}"
                              "QToolButton:hover{border-color:#e11d48;}")
            wa = QWidgetAction(m)
            wa.setDefaultWidget(btn)
            btn.clicked.connect(lambda _=False, p=path: (m.close(), self.use_signature_file(p)))
            m.addAction(wa)
        if files:
            m.addSeparator()
        m.addAction("➕ Nuova firma…", self.new_signature)
        if files:
            sub = m.addMenu("🗑️ Elimina firma salvata")
            for i, path in enumerate(files):
                sub.addAction(QIcon(path), f"Firma {i + 1}", lambda p=path: self._delete_signature(p))

    def use_signature_file(self, path):
        img = QImage(path)
        if img.isNull():
            return
        with open(path, "rb") as fh:
            data = fh.read()
        self.view.start_image_placement(img, data, kind="signature")

    def new_signature(self):
        dlg = SignatureDialog(self)
        if dlg.exec():
            img = dlg.result_image()
            if img is not None:
                self.view.start_image_placement(img, qimage_to_png_bytes(img), kind="signature")

    def _delete_signature(self, path):
        if QMessageBox.question(self, APP_TITLE, "Eliminare questa firma salvata?") == QMessageBox.StandardButton.Yes:
            try:
                os.remove(path)
            except OSError:
                pass

    def insert_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "Inserisci immagine", self._last_dir(),
                                              "Immagini (*.png *.jpg *.jpeg *.bmp *.gif *.webp *.tif *.tiff)")
        if not path:
            return
        img = QImage(path)
        if img.isNull():
            QMessageBox.warning(self, APP_TITLE, "Immagine non valida.")
            return
        if path.lower().endswith((".png", ".jpg", ".jpeg")):
            with open(path, "rb") as fh:
                data = fh.read()
        else:
            data = qimage_to_png_bytes(img)
        self.view.start_image_placement(img, data, kind="image")

    def custom_stamp(self):
        dlg = StampDialog(self)
        if dlg.exec():
            text, color = dlg.values()
            self.view.start_stamp(text, color)

    def _checkmark(self):
        size = 96
        img = QImage(size, size, QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor("#0f172a"), 12, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawPolyline(QPolygonF([QPointF(14, 52), QPointF(38, 78), QPointF(84, 18)]))
        p.end()
        self.view.start_image_placement(img, qimage_to_png_bytes(img), kind="check")

    # ================================================================ moduli
    def clear_form(self):
        if not self.pdf.is_open or not self.pdf.doc.is_form_pdf:
            QMessageBox.information(self, APP_TITLE, "Questo PDF non contiene campi compilabili.")
            return
        if QMessageBox.question(self, APP_TITLE, "Cancellare i valori di tutti i campi del modulo?") != \
                QMessageBox.StandardButton.Yes:
            return
        with self.pdf.edit():
            for page in self.pdf.doc:
                for w in page.widgets():
                    try:
                        if w.field_type in (fitz.PDF_WIDGET_TYPE_CHECKBOX, fitz.PDF_WIDGET_TYPE_RADIOBUTTON):
                            w.field_value = False
                        elif w.field_type in (fitz.PDF_WIDGET_TYPE_TEXT, fitz.PDF_WIDGET_TYPE_COMBOBOX,
                                              fitz.PDF_WIDGET_TYPE_LISTBOX):
                            w.field_value = ""
                        else:
                            continue
                        w.update()
                    except Exception:
                        pass
        self.show_message("🧹 Modulo svuotato")

    def flatten(self):
        if not self.pdf.is_open:
            return
        if QMessageBox.question(self, APP_TITLE,
                                "Appiattire il documento?\n\nCampi compilati, annotazioni, note e timbri diventeranno "
                                "parte fissa della pagina e non saranno più modificabili.") != QMessageBox.StandardButton.Yes:
            return
        with self.pdf.edit(structure=True):
            self.pdf.doc.bake(annots=True, widgets=True)
        self.show_message("📌 Documento appiattito")

    # ================================================================ pagine
    def _selected_pages(self):
        pages = self.thumbs.selected_pages() if self.thumbs.isVisible() else []
        return pages or [self.view.current_page()]

    def _thumb_menu(self, pos):
        if not self.pdf.is_open:
            return
        item = self.thumbs.itemAt(pos)
        if item is not None and not item.isSelected():
            self.thumbs.setCurrentItem(item)
        n = len(self._selected_pages())
        m = QMenu(self)
        label = f"{n} pagine" if n > 1 else "pagina"
        m.addAction(f"↻ Ruota a destra ({label})", lambda: self.rotate_pages(90))
        m.addAction(f"↺ Ruota a sinistra ({label})", lambda: self.rotate_pages(-90))
        m.addAction(f"📑 Duplica ({label})", self.duplicate_pages)
        m.addAction(f"📤 Estrai in un nuovo PDF ({label})", self.extract_pages)
        m.addSeparator()
        m.addAction("➕ Inserisci pagina vuota dopo", self.insert_blank)
        m.addAction("📥 Inserisci file dopo…", self.insert_files)
        m.addSeparator()
        m.addAction(f"🗑️ Elimina ({label})", self.delete_pages)
        m.exec(self.thumbs.viewport().mapToGlobal(pos))

    def rotate_pages(self, delta):
        if not self.pdf.is_open:
            return
        pages = self._selected_pages()
        with self.pdf.edit(structure=True):
            for p in pages:
                page = self.pdf.doc[p]
                page.set_rotation((page.rotation + delta) % 360)
        self._reselect(pages)

    def delete_pages(self):
        if not self.pdf.is_open:
            return
        pages = self._selected_pages()
        if len(pages) >= self.pdf.page_count:
            QMessageBox.warning(self, APP_TITLE, "Non puoi eliminare tutte le pagine del documento.")
            return
        text = f"Eliminare {len(pages)} pagine?" if len(pages) > 1 else f"Eliminare la pagina {pages[0] + 1}?"
        if QMessageBox.question(self, APP_TITLE, text) != QMessageBox.StandardButton.Yes:
            return
        keep = [i for i in range(self.pdf.page_count) if i not in set(pages)]
        with self.pdf.edit(structure=True):
            self.pdf.doc.select(keep)
        self.show_message("🗑️ Pagine eliminate")

    def duplicate_pages(self):
        if not self.pdf.is_open:
            return
        pages = self._selected_pages()
        with self.pdf.edit(structure=True):
            for p in sorted(pages, reverse=True):
                self.pdf.doc.fullcopy_page(p, p + 1)
        self.show_message("📑 Pagine duplicate")

    def insert_blank(self):
        if not self.pdf.is_open:
            return
        cur = self.view.current_page()
        r = self.pdf.doc[cur].rect
        with self.pdf.edit(structure=True):
            self.pdf.doc.new_page(pno=cur + 1, width=r.width, height=r.height)
        self.view.go_to_page(cur + 1)

    def insert_files(self):
        if not self.pdf.is_open:
            return
        files, _ = QFileDialog.getOpenFileNames(self, "Inserisci file", self._last_dir(), OPEN_FILTER)
        if not files:
            return
        pos = self.view.current_page() + 1
        sources = [(f, self._file_bytes(f)) for f in files]
        with self.pdf.edit(structure=True):
            for _, data in sources:
                if data is None:
                    continue
                src = fitz.open(stream=data, filetype="pdf")
                self.pdf.doc.insert_pdf(src, start_at=pos)
                pos += src.page_count
                src.close()
        self.show_message(f"📥 Inseriti {len(files)} file")

    def merge_dialog(self):
        into = self.pdf.is_open
        intro = ("I file verranno aggiunti in fondo al documento aperto." if into
                 else "Scegli i file da unire in un nuovo PDF e trascinali per ordinarli.")
        dlg = MergeDialog(self, intro=intro)
        if not into:
            dlg._add()
        if dlg.exec():
            self.merge_files(dlg.files(), into_current=into)

    def merge_files(self, files, into_current):
        if not into_current and not self.maybe_save():
            return
        datas = [d for d in (self._file_bytes(f) for f in files) if d is not None]
        if not datas:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            if into_current:
                with self.pdf.edit(structure=True):
                    for data in datas:
                        src = fitz.open(stream=data, filetype="pdf")
                        self.pdf.doc.insert_pdf(src)
                        src.close()
            else:
                out = fitz.open()
                for data in datas:
                    src = fitz.open(stream=data, filetype="pdf")
                    out.insert_pdf(src)
                    src.close()
                merged = out.tobytes(garbage=3, deflate=True)
                out.close()
                self.view.reset_position()
                self.pdf.new_from_bytes(merged)
        except Exception as exc:
            QMessageBox.critical(self, APP_TITLE, f"Unione non riuscita:\n{exc}")
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.update_state()
        self.show_message(f"🔗 Uniti {len(datas)} file · ricordati di salvare")

    def photo_to_pdf(self, files=None):
        dlg = ScanDialog(self, start_dir=self._last_dir(), can_append=self.pdf.is_open, settings=self.settings)
        if files:
            dlg.add_files(files)
        if not dlg.exec() or not dlg.pdf_bytes:
            return
        self.settings.setValue("last_dir", dlg.start_dir or self._last_dir())
        n = len(dlg.pages)
        if dlg.append and self.pdf.is_open:
            first = self.pdf.page_count
            with self.pdf.edit(structure=True):
                src = fitz.open(stream=dlg.pdf_bytes, filetype="pdf")
                self.pdf.doc.insert_pdf(src)
                src.close()
            self.view.go_to_page(first)
        else:
            if not self.maybe_save():
                return
            self.view.reset_position()
            self.pdf.new_from_bytes(dlg.pdf_bytes)
        self.update_state()
        if dlg.made_editable:
            self._set_tab(3)
            self.show_message("🔤 Testo: clicca su una scritta per cambiarla · 🧩 Oggetti: sfondi, riquadri, righe e "
                              "immagini · ricordati di salvare")
        else:
            self.show_message(f"📷 {n} {'foto trasformate' if n > 1 else 'foto trasformata'} in PDF · ricordati di salvare")

    def reorder_pages(self, order):
        if not self.pdf.is_open or sorted(order) != list(range(self.pdf.page_count)):
            return
        with self.pdf.edit(structure=True):
            self.pdf.doc.select(order)
        self.show_message("↕️ Pagine riordinate")

    def extract_pages(self):
        if not self.pdf.is_open:
            return
        pages = self._selected_pages()
        base = os.path.splitext(self.pdf.title())[0]
        folder = os.path.dirname(self.pdf.path) if self.pdf.path else self._last_dir()
        path, _ = QFileDialog.getSaveFileName(self, "Salva pagine estratte",
                                              os.path.join(folder, f"{base}_estratte.pdf"), "PDF (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        try:
            self.pdf.save_pages_as(pages, path)
        except Exception as exc:
            QMessageBox.critical(self, APP_TITLE, f"Estrazione non riuscita:\n{exc}")
            return
        lock = " · protetto con la stessa password dell'originale" if self.pdf.password else ""
        self.show_message(f"📤 Estratte {len(pages)} pagine in {os.path.basename(path)}{lock}")

    def split(self):
        if not self.pdf.is_open:
            return
        base = os.path.splitext(self.pdf.title())[0]
        folder = os.path.dirname(self.pdf.path) if self.pdf.path else self._last_dir()
        dlg = SplitDialog(self, self.pdf.page_count, base, folder)
        if not dlg.exec():
            return
        groups = dlg.groups()
        name = dlg.name.text().strip() or base
        out_dir = dlg.folder.text()
        targets = []
        for g in groups:
            suffix = f"pag{g[0] + 1}" if len(g) == 1 else f"pag{g[0] + 1}-{g[-1] + 1}"
            targets.append((g, os.path.join(out_dir, f"{name}_{suffix}.pdf")))
        existing = [t for _, t in targets if os.path.exists(t)]
        if existing and QMessageBox.question(self, APP_TITLE, f"{len(existing)} file esistono già. Sovrascriverli?") != \
                QMessageBox.StandardButton.Yes:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for g, target in targets:
                self.pdf.save_pages_as(g, target)
        except Exception as exc:
            QMessageBox.critical(self, APP_TITLE, f"Divisione non riuscita:\n{exc}")
            return
        finally:
            QApplication.restoreOverrideCursor()
        box = QMessageBox(self)
        box.setWindowTitle(APP_TITLE)
        lock = "\n\nI file sono protetti con la stessa password dell'originale." if self.pdf.password else ""
        box.setText(f"✂️ Creati {len(targets)} file in:\n{out_dir}{lock}")
        open_b = box.addButton("Apri cartella", QMessageBox.ButtonRole.ActionRole)
        box.addButton("OK", QMessageBox.ButtonRole.AcceptRole)
        box.exec()
        if box.clickedButton() is open_b:
            QDesktopServices.openUrl(QUrl.fromLocalFile(out_dir))

    def compress(self):
        if not self.pdf.is_open:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            current = self.pdf.doc.tobytes(garbage=3, deflate=True)
        finally:
            QApplication.restoreOverrideCursor()
        dlg = CompressDialog(self, human_size(len(current)))
        if not dlg.exec():
            return
        dpi, quality, gray = dlg.values()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            tmp = fitz.open(stream=current, filetype="pdf")
            tmp.rewrite_images(dpi_threshold=dpi + 15, dpi_target=dpi, quality=quality, set_to_gray=gray)
            data = tmp.tobytes(garbage=4, deflate=True, deflate_images=True, deflate_fonts=True, clean=True,
                               use_objstms=1)
            tmp.close()
        except Exception as exc:
            QMessageBox.critical(self, APP_TITLE, f"Compressione non riuscita:\n{exc}")
            return
        finally:
            QApplication.restoreOverrideCursor()
        before, after = len(current), len(data)
        if after >= before * 0.97 and not gray:
            QMessageBox.information(self, APP_TITLE, f"Il file è già ottimizzato ({human_size(before)}): "
                                                     "non è possibile ridurlo ulteriormente con questo livello.")
            return
        saved = 100 - after * 100 // max(1, before)
        # la versione compressa va in un file nuovo («-compresso»): l'originale resta com'era
        box = QMessageBox(self)
        box.setWindowTitle(APP_TITLE)
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(f"🗜️ {human_size(before)} → {human_size(after)} (−{saved}%)")
        box.setInformativeText("Salva la versione compressa in un file nuovo: il file originale non viene toccato.")
        save_b = box.addButton("Salva con nome…", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Annulla", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(save_b)
        box.exec()
        if box.clickedButton() is not save_b:
            return
        base = os.path.splitext(self.pdf.path or os.path.join(self._last_dir(), self.pdf.title()))[0]
        self.pdf.replace_bytes(data)
        if not self.save_as(suggested=base + "-compresso.pdf"):
            self.pdf.undo()   # salvataggio annullato: il documento aperto torna com'era
            self.show_message("🗜️ Compressione annullata")

    def _reselect(self, pages):
        if pages:
            self.thumbs.set_current(pages[0])

    # ================================================================ stampa
    def print_doc(self):
        if not self.pdf.is_open:
            return
        if sys.platform == "win32":
            # la finestra di Windows 11 si chiama «Python - Stampa» e non ha anteprima: usiamo la nostra
            from tkpdf.printing import print_document
            if print_document(self, self.pdf, self.view.current_page(), self.settings):
                self.show_message("🖨️ Documento inviato alla stampante")
            return
        from PySide6.QtPrintSupport import QPrintDialog, QPrinter
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setDocName(self.pdf.title())
        dlg = QPrintDialog(printer, self)
        dlg.setMinMax(1, self.pdf.page_count)
        dlg.setFromTo(1, self.pdf.page_count)
        if dlg.exec() != QPrintDialog.DialogCode.Accepted:
            return
        first, last = printer.fromPage(), printer.toPage()
        if first == 0:
            first, last = 1, self.pdf.page_count
        painter = QPainter()
        if not painter.begin(printer):
            QMessageBox.warning(self, APP_TITLE, "Impossibile avviare la stampa.")
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            dpi = min(printer.resolution(), 300)
            for i, pno in enumerate(range(first - 1, last)):
                if i:
                    printer.newPage()
                zoom = dpi / 72.0
                pix = self.pdf.doc[pno].get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False, annots=True)
                img = pix_to_qimage(pix)
                area = painter.viewport()
                if (img.width() > img.height()) != (area.width() > area.height()):
                    img = img.transformed(QTransform().rotate(90))
                scaled = img.size().scaled(area.size(), Qt.AspectRatioMode.KeepAspectRatio)
                x = (area.width() - scaled.width()) // 2
                y = (area.height() - scaled.height()) // 2
                painter.drawImage(area.x() + x, area.y() + y, img.scaled(scaled, Qt.AspectRatioMode.IgnoreAspectRatio,
                                                                          Qt.TransformationMode.SmoothTransformation))
                self.show_message(f"🖨️ Stampa pagina {pno + 1}…")
                QApplication.processEvents()
        finally:
            painter.end()
            QApplication.restoreOverrideCursor()
        self.show_message("🖨️ Documento inviato alla stampante")
