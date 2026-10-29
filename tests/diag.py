import os, sys, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if sys.platform == "win32":
    os.environ["QT_QPA_FONTDIR"] = r"C:\Windows\Fonts"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtWidgets import QApplication
from tkpdf.style import QSS
from tkpdf import mainwindow as MW
HERE = os.path.dirname(os.path.abspath(__file__))
app = QApplication(sys.argv); app.setStyle("Fusion"); app.setStyleSheet(QSS)
win = MW.MainWindow(); win.resize(1150, 760); win.show()
for _ in range(20): app.processEvents()
win.open_path(os.path.join(HERE, "prova.pdf"))
t0=time.time()
while time.time()-t0 < 2.5: app.processEvents()
v = win.view
print("viewport", v.viewport().size(), "scale", v.transform().m11(), "zoom", v.zoom, "fit", v.fit_mode)
print("scene", v.sceneRect(), "visible", v.visible_range(), "current", v.current_page())
print("pix0", v.pages[0].pixmap, v.pages[0].pix_rev, win.pdf.revision, "queue", v._render_queue)
print("vscroll", v.verticalScrollBar().value(), v.verticalScrollBar().maximum(), "hscroll", v.horizontalScrollBar().maximum())
print("topleft scene", v.mapToScene(0,0))
win._set_tab(1)
for _ in range(30): app.processEvents()
win.grab().save(os.path.join(HERE, "diag.png"))
