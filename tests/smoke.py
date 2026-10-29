import os, sys, shutil, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if sys.platform == "win32":
    os.environ["QT_QPA_FONTDIR"] = r"C:\Windows\Fonts"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pymupdf as fitz
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication, QMessageBox
from tkpdf.style import QSS
from tkpdf import viewer as V, mainwindow as MW
from tkpdf.viewer import Tool
from tkpdf.util import qimage_to_png_bytes

HERE = os.path.dirname(os.path.abspath(__file__))
app = QApplication(sys.argv); app.setStyle("Fusion"); app.setStyleSheet(QSS)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: None)
errors = []
QMessageBox.warning = staticmethod(lambda *a, **k: errors.append(a[2] if len(a) > 2 else a))
QMessageBox.critical = staticmethod(lambda *a, **k: errors.append(a[2] if len(a) > 2 else a))


def _exec_default(self):
    """Finestre con pulsanti propri: si «preme» il pulsante predefinito senza mostrarle."""
    b = self.defaultButton()
    if b is not None:
        b.click()
    return 0


QMessageBox.exec = _exec_default
V.webfonts.ask_consent = lambda parent=None: False   # durante la prova niente Google Fonts e nessuna scelta salvata
TMP = tempfile.mkdtemp()
MW.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (os.path.join(TMP, "salvato-con-nome.pdf"), ""))

class FakeText:
    queue = []
    def __init__(self, *a, **k): self.k = k
    def exec(self): return True
    def values(self):
        v = dict(text="", family="sans", fallback_family=self.k.get("family","sans"), size=self.k.get("size",12), bold=False, italic=False, color=QColor("#dc2626"))
        v.update(FakeText.queue.pop(0)); return v
    class _D:
        def setEnabled(self, x): pass
    family = bold = italic = _D()
class FakeNote:
    def __init__(self, *a, **k): pass
    def exec(self): return True
    def text(self): return "Nota di prova"
V.TextDialog = FakeText; V.NoteDialog = FakeNote
class FakeCompress:
    def __init__(self, *a, **k): pass
    def exec(self): return True
    def values(self): return (72, 45, False)
MW.CompressDialog = FakeCompress

src = os.path.join(HERE, "prova.pdf")
work = os.path.join(HERE, "lavoro.pdf"); shutil.copy(src, work)
win = MW.MainWindow(); win.resize(1300, 850); win.show(); app.processEvents()
win.grab().save(os.path.join(HERE, "shot0_welcome.png"))
win.open_path(work)
for _ in range(40): app.processEvents()
v = win.view; pdf = win.pdf
def pump(n=60):
    for _ in range(n): app.processEvents()
    # force renders
    for _ in range(20): v._render_next(); win.thumbs._render_some()
pump()
import time as _t
_t0=_t.time()
while _t.time()-_t0<1.5: app.processEvents()
win.grab().save(os.path.join(HERE, "shot1_open.png"))
print("pages", pdf.page_count, "form", pdf.doc.is_form_pdf, "tab", win.tools_stack.currentIndex())

# 1. selezione + evidenzia
v.set_tool(Tool.HIGHLIGHT)
v._set_sel(0, fitz.Point(75, 125), fitz.Point(300, 128))
print("sel text:", repr(v.selected_text()))
v.apply_markup(Tool.HIGHLIGHT)
# 2. penna
v.set_tool(Tool.INK)
v._finish_ink(dict(pno=0, points=[QPointF(100+i*3, 400+ (i%5)*4) for i in range(40)]))
# 3. forme
for t, a, b in ((Tool.RECT, (320,380), (480,450)), (Tool.ELLIPSE, (330,470),(470,540)), (Tool.ARROW, (100,560),(300,600))):
    v.set_tool(t); v._finish_rect(dict(pno=0, start=QPointF(*a), cur=QPointF(*b)))
# 4. casella di testo
v.set_tool(Tool.TEXTBOX); FakeText.queue.append(dict(text="Casella con àccènti € ok"))
v._finish_rect(dict(pno=0, start=QPointF(320,600), cur=QPointF(320,600)))
# 5. nota
v.click_action(Tool.NOTE, 0, QPointF(500, 100))
# 6. modifica riga
lines = v.text_lines(0)
target = [l for l in lines if "Importo" in l["text"]][0]
FakeText.queue.append(dict(text="Importo totale: 990,00 euro - Scadenza: 15/10/2026", family="original"))
v.edit_line(0, target)
lines = [l["text"] for l in v.text_lines(0)]
print("righe dopo modifica:", [l for l in lines if "Importo" in l or "Scadenza" in l])
# 7. aggiungi testo
FakeText.queue.append(dict(text="Testo aggiunto\nsu due righe", family="serif", size=14))
v._add_text(0, QPointF(320, 200))
# 8. timbro + firma + spunta
v.start_stamp("APPROVATO", QColor("#15803d")); v._place_stamp(0, QPointF(450, 720))
img = QImage(300, 100, QImage.Format.Format_ARGB32); img.fill(Qt.GlobalColor.transparent)
p = QPainter(img); p.setPen(QColor("#1d4ed8")); p.drawLine(10,80,290,20); p.drawLine(10,20,290,80); p.end()
v.start_image_placement(img, qimage_to_png_bytes(img), kind="signature"); v._place_image(0, v._default_image_rect(QPointF(150, 700)))
win._checkmark(); v._place_image(0, v._default_image_rect(QPointF(80, 248)))
# 9. moduli
wr = v.widget_rects(0); print("campi:", [(r, t) for r, t, x in wr])
cb = [x for r,t,x in wr if t == fitz.PDF_WIDGET_TYPE_CHECKBOX][0]
v._activate_field(0, cb)
tx = [x for r,t,x in wr if t == fitz.PDF_WIDGET_TYPE_TEXT][0]
w = v._find_widget(v.page(0), tx); v._open_field_editor(0, w)
v._field_editor["widget"].setText("Mario Rossi"); v._close_field_editor(True)
pump()
import time as _t
_t0=_t.time()
while _t.time()-_t0<1.5: app.processEvents()
v.go_to_page(0); pump()
win.grab().save(os.path.join(HERE, "shot2_edited.png"))
# 10. bianchetto su pagina 2
v.set_tool(Tool.WHITEOUT); v._finish_rect(dict(pno=1, start=QPointF(70,130), cur=QPointF(300,200)))
# 11. pagina ruotata: testo, timbro, casella
v.go_to_page(3); pump()
FakeText.queue.append(dict(text="Scritto su pagina ruotata", size=16))
v._add_text(3, QPointF(60, 60))
v.start_stamp("RICEVUTO", QColor("#1d4ed8")); v._place_stamp(3, QPointF(300, 300))
v.set_tool(Tool.SELECT)
pump()
import time as _t
_t0=_t.time()
while _t.time()-_t0<1.5: app.processEvents()
win.grab().save(os.path.join(HERE, "shot3_rotated.png"))
# spostamento annotazione (timbro su pagina ruotata)
a = v.annot_list(3)[-1]; v.sel_annot = a
v._finish_move(dict(pno=3, start=QPointF(300,300), cur=QPointF(360,340)))
print("annot spostata:", a["rect"], "->", v.sel_annot and v.sel_annot["rect"])
# spostamento ink
ink = [x for x in v.annot_list(0) if x["type"] == fitz.PDF_ANNOT_INK][0]; v.sel_annot = ink
v._finish_move(dict(pno=0, start=QPointF(100,400), cur=QPointF(120,420)))
print("ink spostato:", ink["rect"], "->", v.sel_annot and v.sel_annot["rect"])
# 12. operazioni pagine
n0 = pdf.page_count
win.thumbs.set_current(1); win.duplicate_pages(); print("dopo duplica", pdf.page_count)
win.thumbs.set_current(2); win.delete_pages(); print("dopo elimina", pdf.page_count)
win.thumbs.set_current(0); win.rotate_pages(90); print("rot p0", pdf.doc[0].rotation)
win.reorder_pages([1,0,2,3,4]); print("riordino ok", pdf.doc[1].get_text()[:25].replace("\n"," "))
win.insert_blank(); print("dopo vuota", pdf.page_count)
for _ in range(3): pdf.undo()
print("dopo 3 undo", pdf.page_count, "rot p0", pdf.doc[0].rotation)
pdf.redo(); print("dopo redo", pdf.page_count)
# 13. salva e verifica
out = os.path.join(HERE, "risultato.pdf")
win._save_to(out)
chk = fitz.open(out)
print("salvato pagine", chk.page_count, "annots p?", [len(list(pg.annots())) for pg in chk])
for pg in chk:
    for wd in pg.widgets(): print("  campo", wd.field_name, repr(wd.field_value))
txt = "".join(pg.get_text() for pg in chk)
print("contiene 990,00:", "990,00" in txt, "| vecchio 1.250:", "1.250,00" in txt, "| aggiunto:", "Testo aggiunto" in txt)
chk.close()
# 14. compressione (in un file nuovo «-compresso»), divisione, estrazione, password
orig_size = os.path.getsize(out)
win.compress()
print("compresso in un file nuovo:", os.path.basename(pdf.path or ""), "| originale intatto:",
      os.path.getsize(out) == orig_size)
tmpd = tempfile.mkdtemp()
for g in ([0],[1,2]):
    pdf.save_pages_as(g, os.path.join(tmpd, f"x{g[0]}.pdf"))
print("split files", os.listdir(tmpd))
pdf.save(os.path.join(HERE, "protetto.pdf"), password="1234")
from tkpdf.document import PdfDocument, PasswordRequired
try:
    PdfDocument.file_to_pdf_bytes(os.path.join(HERE, "protetto.pdf")); print("ERRORE: password non richiesta")
except PasswordRequired: print("password richiesta ok")
print("apre con pw:", len(PdfDocument.file_to_pdf_bytes(os.path.join(HERE, "protetto.pdf"), "1234")) > 0)
# 15. ricerca
print("ricerca 'Lorem':", v.search("Lorem"), v.search_step(1))
# unione in nuovo doc
pdf._clean_len = len(pdf._undo)
win.merge_files([src, src], into_current=False); print("unione nuovo doc pagine", pdf.page_count)
win.tools_stack.setCurrentIndex(4); win.tab_group.button(4).setChecked(True); pump()
win.grab().save(os.path.join(HERE, "shot4_pages.png"))

# 16. criticità corrette nella 1.1.0
import stat
from tkpdf import document as D, filesave, pro, webfonts
from tkpdf.dialogs import SignatureDialog
from tkpdf.tk_licenza import Licenza
from tkpdf.tk_licenza_qt import BenvenutoDialog, LicenzeDialog
warned, opened = [], []
QMessageBox.warning = staticmethod(lambda *a, **k: warned.append(a[2]))
V.QDesktopServices.openUrl = staticmethod(lambda u: opened.append(u.toString()))
v._follow_link({"kind": fitz.LINK_URI, "uri": "file:///C:/Windows/System32/calc.exe"})
v._follow_link({"kind": fitz.LINK_URI, "uri": "https://example.org/"})
print("link file: bloccato:", len(warned) == 1, "| https aperto:", opened)
QMessageBox.warning = staticmethod(lambda *a, **k: errors.append(a[2] if len(a) > 2 else a))

# sola lettura: domanda → copia numerata, l'originale non si tocca
ro = os.path.join(TMP, "sola-lettura.pdf"); shutil.copy(src, ro); os.chmod(ro, stat.S_IREAD)
before = open(ro, "rb").read()
pdf._clean_len = len(pdf._undo); win.open_path(ro)
win.rotate_pages(90); win._save_to(ro)
print("sola lettura: originale intatto:", open(ro, "rb").read() == before, "| ancora sola lettura:",
      not os.access(ro, os.W_OK), "| copia:", os.path.exists(os.path.join(TMP, "sola-lettura (1).pdf")))
try:
    filesave.write_file(ro, b"x"); print("ERRORE: sola lettura tolta in silenzio")
except filesave.ReadOnlyError:
    print("write_file rifiuta la sola lettura: ok")
pdf._clean_len = len(pdf._undo); pdf.close(); os.chmod(ro, stat.S_IWRITE)

# firme digitali: avviso all'apertura e «Salva con nome» proposto prima di sovrascrivere
signed = os.path.join(TMP, "firmato.pdf")
d = fitz.open(src)
wd = fitz.Widget(); wd.field_type = fitz.PDF_WIDGET_TYPE_SIGNATURE; wd.field_name = "Firma1"; wd.rect = fitz.Rect(50, 50, 200, 90)
d[0].add_widget(wd)
d.xref_set_key(d.pdf_catalog(), "AcroForm/SigFlags", "3"); d.save(signed); d.close()
before = open(signed, "rb").read()
win.open_path(signed)
print("firme digitali rilevate:", bool(pdf.signed_path))
win.rotate_pages(90); win._save_to(signed)
print("firmato: originale intatto:", open(signed, "rb").read() == before, "| salvato in:", os.path.basename(pdf.path))
pdf._clean_len = len(pdf._undo); pdf.close()

# limitazioni del proprietario: si vedono invece di sparire in silenzio
lim = os.path.join(TMP, "limitato.pdf")
d = fitz.open(src); d.save(lim, encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="proprietario", user_pw="",
                         permissions=int(fitz.PDF_PERM_ACCESSIBILITY | fitz.PDF_PERM_COPY)); d.close()
win.open_path(lim); print("limitazioni:", pdf.restrictions); pdf.close()

# Estrai/Dividi da un PDF con password: il nuovo file resta protetto
p2 = D.PdfDocument(); p2.open_file(os.path.join(HERE, "protetto.pdf"), "1234")
estr = os.path.join(TMP, "estratte.pdf"); p2.save_pages_as([0], estr); p2.close()
print("estratte con password:", fitz.open(estr).needs_pass)

# Google Fonts: senza consenso nessun download
print("font senza rete:", webfonts.fetch("ABCDEF+FontInesistente-Bold", download=False))

# finestre: firma (avviso + «salva» spento), Informazioni, Licenze, Benvenuto
sd = SignatureDialog(win); print("firma salvata di default:", sd.save_it.isChecked())
from PySide6.QtCore import QTimer as _QT
_QT.singleShot(300, lambda: QApplication.activeModalWidget() and QApplication.activeModalWidget().reject())
win.show_about()   # Informazioni comune (libreria): si apre e si chiude da sola
print("informazioni: ok")
ld = LicenzeDialog("tk-pdf", "test", pro.URL_SORGENTE, pro.cartella_licenze(), win)
print("licenze nel pacchetto:", [ld.elenco.item(i).text() for i in range(ld.elenco.count())])
lic = Licenza("tk-pdf-prova", "0", TMP)
bd = BenvenutoDialog(lic, "tk-pdf", pro.URL_SORGENTE, win); bd.done(0)
print("benvenuto: statistiche", lic.consenso_statistiche(), "| ricordato", lic.ricordo("benvenuto_agpl"))
shutil.rmtree(TMP, ignore_errors=True)
print("ERRORI:", errors)
