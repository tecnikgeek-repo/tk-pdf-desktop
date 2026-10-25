"""Installazione da ZIP (senza exe dedicati): avviata da «Installa tk-pdf.cmd» con il Python incluso.

Evita i blocchi di antivirus (Avast CyberCapture) e Smart App Control sugli exe non firmati.
"""
import ctypes
import os
import shutil
import subprocess
import sys
import threading
import time
from ctypes import POINTER, byref, c_void_p, wintypes

from tkpdf import APP_TITLE, VERSION

UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\tk-pdf"
NO_WINDOW = 0x08000000
SHORTCUT = "tk-pdf.lnk"
LEGACY_SHORTCUTS = ("tkPDF.lnk", "TK PDF.lnk")  # nomi dei collegamenti: «tkPDF» 1.0.18-1.0.28, «TK PDF» fino alla 1.0.17
# alzare quando cambia dove puntano collegamenti e disinstallazione: al prossimo avvio l'app li rifà tutti
LAUNCH_SCHEMA = "4"  # 2: tk-pdf.exe · 3: «tkPDF.lnk» al posto di «TK PDF.lnk» · 4: «tk-pdf.lnk» al posto di «tkPDF.lnk»
TASKBAR_PINS = os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Internet Explorer\Quick Launch\User Pinned\TaskBar")


# ---------------------------------------------------------------- percorsi
def source_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def default_dest():
    return os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "Programs", "tk-pdf")


def existing_dest():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
            path = winreg.QueryValueEx(k, "InstallLocation")[0]
            return path if path and os.path.isdir(path) else None
    except OSError:
        return None


def special_folder(csidl):
    buf = ctypes.create_unicode_buffer(260)
    ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buf)
    return buf.value


# ---------------------------------------------------------------- collegamenti (IShellLinkW via ctypes)
class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8)]

    def __init__(self, text):
        super().__init__()
        ctypes.oledll.ole32.CLSIDFromString(text, byref(self))


def _vcall(ptr, index, restype, *args):
    """Chiama il metodo n. `index` della vtable di un'interfaccia COM."""
    vtable = ctypes.cast(ptr, POINTER(POINTER(c_void_p))).contents
    argtypes = [c_void_p]
    for a in args:
        if isinstance(a, str):
            argtypes.append(wintypes.LPCWSTR)
        elif isinstance(a, ctypes._SimpleCData):
            argtypes.append(type(a))
        else:  # byref(...) e puntatori
            argtypes.append(c_void_p)
    fn = ctypes.WINFUNCTYPE(restype, *argtypes)(vtable[index])
    return fn(ptr, *args)


def create_shortcut(path, target, arguments, workdir, icon, description):
    ole32 = ctypes.oledll.ole32
    ole32.CoInitialize(None)
    link = c_void_p()
    ole32.CoCreateInstance(byref(GUID("{00021401-0000-0000-C000-000000000046}")), None, 1,
                           byref(GUID("{000214F9-0000-0000-C000-000000000046}")), byref(link))
    # indici vtable IShellLinkW: SetDescription 7, SetWorkingDirectory 9, SetArguments 11, SetIconLocation 17, SetPath 20
    _vcall(link, 20, ctypes.HRESULT, target)
    _vcall(link, 11, ctypes.HRESULT, arguments)
    _vcall(link, 9, ctypes.HRESULT, workdir)
    _vcall(link, 17, ctypes.HRESULT, icon, ctypes.c_int(0))
    _vcall(link, 7, ctypes.HRESULT, description)
    persist = c_void_p()
    _vcall(link, 0, ctypes.HRESULT, byref(GUID("{0000010B-0000-0000-C000-000000000046}")), byref(persist))
    _vcall(persist, 6, ctypes.HRESULT, path, wintypes.BOOL(True))  # IPersistFile::Save
    _vcall(persist, 2, wintypes.ULONG)
    _vcall(link, 2, wintypes.ULONG)


# ---------------------------------------------------------------- installazione
def install(dest, desktop=True, progress=None):
    report = progress or (lambda p, s: None)
    src = source_root()
    same = os.path.normcase(os.path.abspath(src)) == os.path.normcase(os.path.abspath(dest))

    report(3, "Chiusura di tk-pdf se aperto…")
    if os.path.isdir(dest) and not same:
        from tkpdf.uninstall import kill_other_instances
        kill_other_instances(dest)
        time.sleep(0.8)

    if not same:
        items = ["python", "tkpdf", "assets", "licenze", "run.py"]
        files = [os.path.join(d, f) for item in items if os.path.isdir(os.path.join(src, item))
                 for d, _, fs in os.walk(os.path.join(src, item)) for f in fs]
        total = len(files) + 1
        staging = dest + ".nuova"
        if os.path.isdir(staging):
            shutil.rmtree(staging, ignore_errors=True)
        os.makedirs(staging, exist_ok=True)
        done = 0
        for f in files + [os.path.join(src, "run.py")]:
            rel = os.path.relpath(f, src)
            target = os.path.join(staging, rel)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy2(f, target)
            done += 1
            if done % 40 == 0 or done == total:
                report(5 + done * 80 // total, f"Copia dei file… {done * 100 // total}%")

        # i file estratti da uno ZIP scaricato hanno il «marchio del web»: lo si toglie per evitare avvisi a ogni avvio
        for d, _, fs in os.walk(staging):
            for name in fs:
                try:
                    os.remove(os.path.join(d, name) + ":Zone.Identifier")
                except OSError:
                    pass

        report(86, "Sostituzione della versione precedente…")
        old = dest + ".vecchia"
        if os.path.isdir(old):
            shutil.rmtree(old, ignore_errors=True)
        if os.path.isdir(dest):
            for attempt in range(30):
                try:
                    os.rename(dest, old)
                    break
                except OSError:
                    if attempt == 29:
                        raise PermissionError("tk-pdf è ancora aperto: chiudilo e riprova.")
                    time.sleep(1)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        os.rename(staging, dest)
        shutil.rmtree(old, ignore_errors=True)
        stray = os.path.join(dest, "tk-pdf.exe")  # lanciatore delle versioni <= 1.0.5
        if os.path.exists(stray):
            os.remove(stray)

    report(90, "Creazione dei collegamenti…")
    create_shortcuts(dest, desktop)

    report(95, "Registrazione per i file PDF…")
    subprocess.run([app_exe(dest), os.path.join(dest, "run.py"), "--register"], cwd=dest, timeout=60,
                   creationflags=NO_WINDOW)
    write_uninstall_entry(dest)
    report(100, "Installazione completata")
    return dest


def app_exe(dest):
    from tkpdf.winreg_assoc import installed_exe
    return installed_exe(dest) or os.path.join(dest, "python", "pythonw.exe")


def create_shortcuts(dest, desktop):
    exe = app_exe(dest)
    args = f'"{os.path.join(dest, "run.py")}"'
    icon = os.path.join(dest, "assets", "tk-pdf.ico")
    description = "tk-pdf - visualizza, annota, firma e modifica PDF"
    for folder in (special_folder(0x0002), special_folder(0x0010)):
        for old in LEGACY_SHORTCUTS:  # «tkPDF.lnk» / «TK PDF.lnk» delle versioni <= 1.0.28 → sostituiti da «tk-pdf.lnk»
            try:
                os.remove(os.path.join(folder, old))
            except OSError:
                pass
    create_shortcut(os.path.join(special_folder(0x0002), SHORTCUT), exe, args, dest, icon, description)
    if desktop:
        create_shortcut(os.path.join(special_folder(0x0010), SHORTCUT), exe, args, dest, icon, description)
    # tk-pdf aggiunto alla barra delle applicazioni: è una copia a parte. Il file non si rinomina (si perderebbe il
    # fissaggio): se ne aggiorna solo la destinazione
    for name in (SHORTCUT,) + LEGACY_SHORTCUTS:
        pin = os.path.join(TASKBAR_PINS, name)
        if os.path.exists(pin):
            create_shortcut(pin, exe, args, dest, icon, description)


def has_shortcut(csidl):
    folder = special_folder(csidl)
    return any(os.path.exists(os.path.join(folder, n)) for n in (SHORTCUT,) + LEGACY_SHORTCUTS)


def write_uninstall_entry(dest):
    import winreg
    exe = app_exe(dest)
    args = f'"{os.path.join(dest, "run.py")}"'
    icon = os.path.join(dest, "assets", "tk-pdf.ico")
    size_kb = sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(dest) for f in fs) // 1024
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
        try:
            installed_on = winreg.QueryValueEx(k, "InstallDate")[0]
        except OSError:
            installed_on = time.strftime("%Y%m%d")
        for name, value in (("DisplayName", APP_TITLE), ("DisplayVersion", VERSION), ("Publisher", "TecnikGeek"),
                            ("DisplayIcon", icon), ("InstallLocation", dest),
                            ("UninstallString", f'"{exe}" {args} --uninstall'),
                            ("URLInfoAbout", "https://pietrodefilippis.it"),
                            ("InstallDate", installed_on), ("TkLaunchSchema", LAUNCH_SCHEMA)):
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)
        for name, value in (("EstimatedSize", size_kb), ("NoModify", 1), ("NoRepair", 1)):
            winreg.SetValueEx(k, name, 0, winreg.REG_DWORD, value)


def refresh_after_update():
    """Dopo un aggiornamento automatico (che sostituisce solo i file): collegamenti su tk-pdf.exe al posto di
    pythonw.exe (installazioni <= 1.0.15) e voce di «App installate» aggiornata. Solo per la copia installata."""
    import winreg
    root = source_root()
    dest = existing_dest()
    if dest is None or os.path.normcase(os.path.abspath(dest)) != os.path.normcase(root) or "--selftest" in sys.argv:
        return False
    def value(name):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
                return winreg.QueryValueEx(k, name)[0]
        except OSError:
            return ""

    # la versione da sola non basta: lo script di aggiornamento delle versioni precedenti la scrive già lui
    changed = (value("TkLaunchSchema") != LAUNCH_SCHEMA or value("DisplayVersion") != VERSION
               or os.path.basename(app_exe(root)) not in value("UninstallString"))
    if changed:
        # i collegamenti si rifanno solo se esistono già (chi ha tolto quello sul desktop non se lo ritrova)
        if has_shortcut(0x0002) or has_shortcut(0x0010):
            create_shortcuts(root, has_shortcut(0x0010))
        write_uninstall_entry(root)
    if value("TkLaunchSchema") == LAUNCH_SCHEMA:
        cleanup_launchers(root)  # solo con i collegamenti già spostati su tk-pdf.exe
    return changed


def cleanup_launchers(root):
    """Toglie python.exe e pythonw.exe dalla copia installata, così nella cartella resta solo tk-pdf.exe.
    Solo quando l'app gira già come tk-pdf.exe e «Apri con» punta a tk-pdf.exe; se il file è in uso si riprova
    al prossimo avvio."""
    import winreg
    from tkpdf.winreg_assoc import EXE_NAME, PROG_ID
    exe = os.path.join(root, "python", EXE_NAME)
    if not os.path.isfile(exe) or os.path.normcase(os.path.abspath(sys.executable)) != os.path.normcase(exe):
        return
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{PROG_ID}\shell\open\command") as k:
            if EXE_NAME not in winreg.QueryValueEx(k, "")[0].lower():
                return
    except OSError:
        return
    for name in ("pythonw.exe", "python.exe"):
        try:
            os.remove(os.path.join(root, "python", name))
        except OSError:
            pass


def launch(dest):
    subprocess.Popen([app_exe(dest), os.path.join(dest, "run.py")], cwd=dest,
                     creationflags=0x00000200, close_fds=True)


# ---------------------------------------------------------------- interfaccia
def run(argv):
    dest = existing_dest() or default_dest()
    if "--silent" in argv:
        desktop = existing_dest() is None or has_shortcut(0x0010)
        install(dest, desktop)
        return 0

    from PySide6.QtCore import QObject, Qt, Signal
    from PySide6.QtWidgets import (
        QApplication, QCheckBox, QDialog, QHBoxLayout, QLabel, QMessageBox, QProgressBar, QPushButton, QVBoxLayout,
        QWidget,
    )
    from tkpdf.icon import app_icon
    from tkpdf.style import QSS

    app = QApplication(argv)
    app.setStyle("Fusion")
    from tkpdf.tk_licenza_qt import stile_caselle_globale
    app.setStyleSheet(QSS + stile_caselle_globale())
    icon = app_icon()
    app.setWindowIcon(icon)

    class Bridge(QObject):
        progress = Signal(int, str)
        finished = Signal(str)
        failed = Signal(str)

    dlg = QDialog()
    dlg.setWindowTitle(f"Installazione {APP_TITLE} {VERSION}")
    dlg.setMinimumWidth(520)
    lay = QVBoxLayout(dlg)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)

    header = QWidget()
    header.setObjectName("tkHeader")
    header.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    h = QHBoxLayout(header)
    h.setContentsMargins(22, 18, 22, 18)
    ic = QLabel()
    ic.setPixmap(icon.pixmap(52, 52))
    h.addWidget(ic)
    titles = QLabel(f"<div style='font-size:20px;font-weight:800;color:white'>{APP_TITLE}</div>"
                    f"<div style='color:#cbd5e1'>Installazione versione {VERSION} · visualizza, annota, firma e modifica PDF</div>")
    h.addWidget(titles, 1)
    lay.addWidget(header)

    body = QVBoxLayout()
    body.setContentsMargins(26, 20, 26, 12)
    body.setSpacing(10)
    where = QLabel(f"tk-pdf verrà installato in:<br><b>{dest}</b>")
    where.setWordWrap(True)
    body.addWidget(where)
    desktop_cb = QCheckBox("Crea un collegamento sul desktop")
    desktop_cb.setChecked(existing_dest() is None or has_shortcut(0x0010))
    launch_cb = QCheckBox("Apri tk-pdf al termine")
    launch_cb.setChecked(True)
    body.addWidget(desktop_cb)
    body.addWidget(launch_cb)
    info = QLabel("Non servono permessi di amministratore · nessun programma sconosciuto da approvare")
    info.setStyleSheet("color:#64748b;")
    info.setWordWrap(True)
    body.addWidget(info)
    bar = QProgressBar()
    bar.setTextVisible(False)
    bar.setFixedHeight(8)
    bar.setStyleSheet("QProgressBar { background:#e2e8f0; border:0; border-radius:4px; }"
                      "QProgressBar::chunk { background:#e11d48; border-radius:4px; }")
    bar.hide()
    body.addWidget(bar)
    status = QLabel("")
    status.setStyleSheet("color:#64748b;")
    body.addWidget(status)
    lay.addLayout(body)

    footer = QWidget()
    footer.setObjectName("tkZipFooter")
    footer.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    # selettore per id: altrimenti lo sfondo verrebbe ereditato anche dai pulsanti
    footer.setStyleSheet("#tkZipFooter { background:#f8fafc; border-top:1px solid #e2e8f0; }")
    f = QHBoxLayout(footer)
    f.setContentsMargins(26, 12, 26, 12)
    f.addWidget(QLabel("<span style='color:#64748b'>Creato da TecnikGeek</span>"))
    f.addStretch(1)
    cancel = QPushButton("Annulla")
    ok = QPushButton("Installa")
    ok.setObjectName("accent")
    ok.setDefault(True)
    f.addWidget(cancel)
    f.addWidget(ok)
    lay.addWidget(footer)

    bridge = Bridge()
    state = {"done": False}

    def on_progress(p, s):
        bar.setValue(p)
        status.setText(s)

    def on_finished(path):
        state["done"] = True
        status.setText("✔ tk-pdf è installato. Lo trovi nel menu Start" + (" e sul desktop." if desktop_cb.isChecked() else "."))
        status.setStyleSheet("color:#15803d; font-weight:600;")
        ok.setText("Fine")
        ok.setEnabled(True)

    def on_failed(msg):
        QMessageBox.critical(dlg, APP_TITLE, f"Installazione non riuscita:\n{msg}")
        for w in (ok, cancel, desktop_cb, launch_cb):
            w.setEnabled(True)
        bar.hide()
        status.setText("")

    bridge.progress.connect(on_progress)
    bridge.finished.connect(on_finished)
    bridge.failed.connect(on_failed)

    def start():
        if state["done"]:
            if launch_cb.isChecked():
                launch(dest)
            dlg.accept()
            return
        for w in (ok, cancel, desktop_cb, launch_cb):
            w.setEnabled(False)
        bar.show()
        desktop = desktop_cb.isChecked()

        def work():
            try:
                install(dest, desktop, lambda p, s: bridge.progress.emit(p, s))
                bridge.finished.emit(dest)
            except Exception as exc:
                bridge.failed.emit(str(exc))

        threading.Thread(target=work, daemon=True).start()

    ok.clicked.connect(start)
    cancel.clicked.connect(dlg.reject)
    dlg.exec()
    return 0
