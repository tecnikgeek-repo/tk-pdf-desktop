"""Avvio dell'applicazione."""
import os
import sys
import time
import traceback

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, QUrl, Slot
from PySide6.QtWidgets import QApplication, QMessageBox

from tkpdf import APP_NAME, APP_TITLE, VERSION
from tkpdf.util import IS_LINUX, app_data_dir


class TkApplication(QApplication):
    """Su macOS i file aperti dal Finder (doppio clic, «Apri con», Dock) arrivano come QFileOpenEvent."""

    def __init__(self, argv):
        super().__init__(argv)
        self.window = None
        self.pending_files = []

    def event(self, e):
        if e.type() == QEvent.Type.FileOpen and e.file():
            if self.window is not None:
                self.window.open_path(e.file())
            else:
                self.pending_files.append(e.file())
            return True
        return super().event(e)


class _ApriConIlSistema(QObject):
    """Linux: link, e-mail e cartelle si aprono con xdg-open e l'ambiente del sistema, non con quello del pacchetto
    (con le nostre librerie il browser o il file manager potrebbero non partire)."""

    @Slot(QUrl)
    def apri(self, url):
        from tkpdf import tk_linux
        tk_linux.apri(url.toLocalFile() if url.isLocalFile() else url.toString())


def _linux_avvio(app):
    from PySide6.QtGui import QDesktopServices
    from tkpdf.util import LINUX_DESKTOP_ID
    app.setDesktopFileName(LINUX_DESKTOP_ID)  # Wayland: la barra delle applicazioni trova l'icona dal .desktop
    app._apri_sistema = _ApriConIlSistema(app)
    for scheme in ("http", "https", "mailto", "file"):
        QDesktopServices.setUrlHandler(scheme, app._apri_sistema, "apri")
    if "--selftest" not in sys.argv:
        # voce nel menu delle applicazioni e in «Apri con» (si corregge da sola se l'AppImage è stato spostato)
        import threading
        from tkpdf.util import install_linux_menu

        def menu():
            try:
                install_linux_menu()
            except Exception:
                pass
        threading.Thread(target=menu, daemon=True).start()


def runtime_check():
    """Selftest del pacchetto: PDF, licenze, stampa e OCR ci sono davvero. Ritorna «OK …» o solleva un'eccezione."""
    import pymupdf
    from PySide6.QtPrintSupport import QPrinter, QPrinterInfo
    from tkpdf import ocr, pro
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "Prova àèìòù")
    assert "àèìòù" in pymupdf.open("pdf", doc.tobytes())[0].get_text(), "PyMuPDF: testo non riletto"
    lic = pro.cartella_licenze()
    assert os.path.isfile(os.path.join(lic, "COPYING-AGPL-3.0.txt")), f"licenze mancanti ({lic})"
    QPrinter(QPrinter.PrinterMode.HighResolution)
    stampanti = len(QPrinterInfo.availablePrinterNames())
    assert ocr.available(), "riconoscimento del testo non disponibile"
    extra = ""
    if IS_LINUX:
        from tkpdf import ocr_linux
        extra = f" · {ocr_linux.versione()}"
    return (f"OK PyMuPDF {pymupdf.VersionBind} · {len(os.listdir(lic))} licenze · {stampanti} stampanti · "
            f"OCR{extra}")


def _install_excepthook():
    def hook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        try:
            with open(os.path.join(app_data_dir(), "errori.log"), "a", encoding="utf-8") as fh:
                fh.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] v{VERSION}\n{text}")
        except OSError:
            pass
        if QApplication.instance() is not None:
            QMessageBox.warning(None, APP_TITLE, f"Si è verificato un errore imprevisto:\n\n{exc}\n\n"
                                                 "Il dettaglio è stato salvato in errori.log.")
        else:
            sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = hook


def main():
    if "--register" in sys.argv:
        from tkpdf.winreg_assoc import register
        register()
        return
    if "--unregister" in sys.argv:
        from tkpdf.winreg_assoc import unregister
        unregister()
        return
    if "--install-zip" in sys.argv:
        from tkpdf.zipsetup import run as install_from_zip
        sys.exit(install_from_zip(sys.argv))
    if "--uninstall" in sys.argv:
        from tkpdf.uninstall import run as uninstall
        sys.exit(uninstall())
    if "--ocr-test" in sys.argv:
        # verifica del pacchetto: riconosce il testo di un'immagine e lo scrive in un file
        i = sys.argv.index("--ocr-test")
        from PySide6.QtGui import QImage
        from tkpdf import ocr
        try:
            lines = ocr.recognize([QImage(sys.argv[i + 1])])[0]
            text = "\n".join(" ".join(t for t, _ in words) for words in lines)
            # poi le parole con il riquadro (pixel dell'immagine): tests/verifica_ocr.py controlla le posizioni
            text += "\n---\n" + "\n".join(f"{t}\t{r.x():.1f}\t{r.y():.1f}\t{r.width():.1f}\t{r.height():.1f}"
                                          for words in lines for t, r in words)
        except Exception as exc:
            text = f"ERRORE: {exc}"
        with open(sys.argv[i + 2], "w", encoding="utf-8") as fh:
            fh.write(text)
        sys.exit(0 if text and not text.startswith("ERRORE") else 1)
    if "--update-test" in sys.argv:
        from tkpdf.updater import cli_update_test
        sys.exit(cli_update_test(sys.argv))

    if "--selftest" in sys.argv:
        import tempfile
        os.environ.setdefault("TKPDF_DATI", tempfile.mkdtemp(prefix="tkpdf-selftest-"))
    _install_excepthook()
    if sys.platform == "win32":
        # dopo un aggiornamento la registrazione «Apri con» può essere di una versione precedente
        from tkpdf.winreg_assoc import ensure_registered
        ensure_registered()
        try:
            # collegamenti su tk-pdf.exe (installazioni <= 1.0.15) e voce di «App installate» aggiornata
            from tkpdf.zipsetup import refresh_after_update
            refresh_after_update()
        except Exception:
            pass
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("TecnikGeek.tk-pdf")
        except Exception:
            pass

    app = TkApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("TecnikGeek")
    app.setApplicationDisplayName(APP_TITLE)
    app.setStyle("Fusion")
    if IS_LINUX:
        _linux_avvio(app)
    # testi italiani nei dialoghi standard di Qt (colori, pulsanti OK/Annulla…)
    from PySide6.QtCore import QLibraryInfo, QTranslator
    translator = QTranslator(app)
    if translator.load("qtbase_it", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(translator)
    try:
        app.styleHints().setColorScheme(Qt.ColorScheme.Light)
    except Exception:
        pass

    from tkpdf.icon import app_icon
    from tkpdf.mainwindow import MainWindow
    from tkpdf.style import QSS

    from tkpdf.tk_licenza_qt import stile_caselle_globale
    app.setStyleSheet(QSS + stile_caselle_globale())
    app.setWindowIcon(app_icon())
    # donazione, benvenuto e consenso alle statistiche (software libero: nessuna funzione bloccata)
    try:
        from tkpdf.tk_licenza import Licenza
        app.licenza = Licenza("tk-pdf", VERSION, app_data_dir())
    except Exception:
        app.licenza = None
    win = MainWindow()
    files = [a for a in sys.argv[1:] if not a.startswith("--") and os.path.isfile(a)]

    if "--selftest" in sys.argv:
        # verifica del pacchetto: apre il file fuori schermo, salva uno screenshot ed esce
        out = sys.argv[sys.argv.index("--selftest") + 1]
        try:
            res = runtime_check()
        except Exception as exc:
            res = f"ERRORE {exc.__class__.__name__}: {exc}"
        with open(os.path.splitext(out)[0] + ".txt", "w", encoding="utf-8") as fh:
            fh.write(res)
        win.move(-4000, -4000)
        win.resize(1300, 850)
        win.show()

        def finish():
            win.grab().save(out)
            win.pdf.close()
            app.quit()

        if files:
            QTimer.singleShot(200, lambda: win.open_path(files[0]))
        # fuori schermo la vista non riceve paint: il primo grab avvia il rendering delle pagine
        QTimer.singleShot(2500, win.grab)
        QTimer.singleShot(4000, finish)
        sys.exit(app.exec())

    win.show()
    app.window = win

    def open_initial():
        todo = files or app.pending_files
        app.pending_files = []
        if len(todo) == 1:
            win.open_path(todo[0])
        elif todo:
            win.merge_files(todo, False)

    def after_welcome():
        # benvenuto la prima volta (finestra già visibile), poi i file; nessuna rete prima della risposta
        from tkpdf import pro
        pro.benvenuto(win)
        open_initial()
        # segnale giornaliero solo col consenso dato nel benvenuto: in sottofondo, senza rete non succede niente
        if getattr(app, "licenza", None) is not None:
            QTimer.singleShot(6000, app.licenza.avvia)
        # controllo aggiornamenti in background (al massimo ogni 12 ore)
        QTimer.singleShot(4000, win.updates.check)
        pro.invito(win)

    QTimer.singleShot(300, after_welcome)
    sys.exit(app.exec())
