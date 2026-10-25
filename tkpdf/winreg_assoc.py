"""Registra tk-pdf in «Apri con» e in «App predefinite» di Windows (solo utente corrente, niente permessi admin)."""
import os
import sys

PROG_ID = "TKPDF.Document"
APP_NAME = "tk-pdf"
CAPS_KEY = r"Software\TecnikGeek\tk-pdf\Capabilities"
STATE_KEY = r"Software\TecnikGeek\tk-pdf"
# alzare quando cambia cosa viene scritto nel registro: all'avvio l'app si ri-registra da sola
SCHEMA = "5"  # 3: tk-pdf.exe · 4: nome tkPDF · 5: nome tk-pdf
OLD_APP_NAMES = ("TK PDF", "tkPDF")  # nomi con cui le versioni precedenti si registravano in «App predefinite»
# copia identica di pythonw.exe con il nome dell'app (1.0.16): stesso file, Smart App Control lo accetta
EXE_NAME = "tk-pdf.exe"


def installed_exe(root):
    """python\\tk-pdf.exe della versione installata (python\\pythonw.exe per quelle precedenti), None in sviluppo."""
    for name in (EXE_NAME, "pythonw.exe"):
        p = os.path.join(root, "python", name)
        if os.path.exists(p):
            return p
    return None


def launch_command():
    """(comando, icona). Niente exe compilati (Smart App Control blocca ogni exe nuovo): si usa pythonw.exe incluso,
    copiato come tk-pdf.exe; nome e icona mostrati da Windows arrivano da FriendlyAppName/ApplicationIcon."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # versione installata: python\tk-pdf.exe incluso; sviluppo: interprete di base (quello del venv uv è console)
    pyw = installed_exe(root) or ""
    if not os.path.exists(pyw):
        pyw = os.path.join(sys.base_prefix, "pythonw.exe")
    if not os.path.exists(pyw):
        pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return f'"{pyw}" "{os.path.join(root, "run.py")}"', os.path.join(root, "assets", "tk-pdf.ico")


def _set(winreg, path, name, value):
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, path) as k:
        winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)


def _get(winreg, path, name=""):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def register():
    import winreg

    launcher, icon = launch_command()
    command = f'{launcher} "%1"'
    icon_ref = f'"{icon}",0'
    base = rf"Software\Classes\{PROG_ID}"

    _set(winreg, base, "", "Documento PDF")
    _set(winreg, base, "FriendlyTypeName", "Documento PDF")
    _set(winreg, rf"{base}\DefaultIcon", "", icon_ref)
    # nome e icona dell'app in «Apri con» (altrimenti Windows mostra «Python»)
    _set(winreg, rf"{base}\shell\open", "FriendlyAppName", APP_NAME)
    _set(winreg, rf"{base}\shell\open\command", "", command)
    _set(winreg, rf"{base}\Application", "ApplicationName", APP_NAME)
    _set(winreg, rf"{base}\Application", "ApplicationIcon", icon_ref)
    _set(winreg, rf"{base}\Application", "ApplicationCompany", "TecnikGeek")
    _set(winreg, rf"{base}\Application", "ApplicationDescription", "Visualizza, annota, firma e modifica PDF")
    _set(winreg, r"Software\Classes\.pdf\OpenWithProgids", PROG_ID, "")

    # «App predefinite» di Impostazioni
    _set(winreg, CAPS_KEY, "ApplicationName", APP_NAME)
    _set(winreg, CAPS_KEY, "ApplicationDescription", "Visualizza, annota, firma e modifica PDF")
    _set(winreg, CAPS_KEY, "ApplicationIcon", icon_ref)
    _set(winreg, rf"{CAPS_KEY}\FileAssociations", ".pdf", PROG_ID)
    _set(winreg, r"Software\RegisteredApplications", APP_NAME, CAPS_KEY)
    for old in OLD_APP_NAMES:
        _delete_value(winreg, r"Software\RegisteredApplications", old)

    # dal 1.0.16 l'eseguibile si chiama davvero tk-pdf.exe: «Apri con» legge anche Applications\tk-pdf.exe
    # (nelle versioni <= 1.0.7 la stessa chiave era scritta per errore e va comunque riscritta per intero)
    app_key = r"Software\Classes\Applications\tk-pdf.exe"
    _delete_tree(winreg, winreg.HKEY_CURRENT_USER, app_key)
    if os.path.basename(launcher.split('"')[1]).lower() == EXE_NAME:
        _set(winreg, app_key, "FriendlyAppName", APP_NAME)
        _set(winreg, rf"{app_key}\DefaultIcon", "", icon_ref)
        _set(winreg, rf"{app_key}\shell\open\command", "", command)
        _set(winreg, rf"{app_key}\SupportedTypes", ".pdf", "")
    _set(winreg, STATE_KEY, "RegistrationSchema", SCHEMA)
    _set(winreg, STATE_KEY, "RegistrationCommand", command)
    _notify()


def ensure_registered():
    """All'avvio della versione installata: rifà la registrazione se manca, è vecchia o punta altrove."""
    if sys.platform != "win32":
        return
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if installed_exe(root) is None or "--selftest" in sys.argv:
        return  # versione di sviluppo o test di build: non tocca il registro
    try:
        import winreg
        # solo la copia registrata come installata (evita che un test in una cartella temporanea
        # sposti «Apri con» su percorsi che poi spariscono)
        location = _get(winreg, r"Software\Microsoft\Windows\CurrentVersion\Uninstall\tk-pdf", "InstallLocation")
        if not location or os.path.normcase(os.path.abspath(location)) != os.path.normcase(root):
            return
        launcher, _ = launch_command()
        expected = f'{launcher} "%1"'
        if (_get(winreg, STATE_KEY, "RegistrationSchema") != SCHEMA
                or _get(winreg, rf"Software\Classes\{PROG_ID}\shell\open\command") != expected):
            register()
    except Exception:
        pass


def _notify():
    try:
        import ctypes
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)
    except Exception:
        pass


def _delete_tree(winreg, root, path):
    try:
        with winreg.OpenKey(root, path, 0, winreg.KEY_ALL_ACCESS) as k:
            while True:
                try:
                    sub = winreg.EnumKey(k, 0)
                except OSError:
                    break
                _delete_tree(winreg, root, rf"{path}\{sub}")
        winreg.DeleteKey(root, path)
    except OSError:
        pass


def unregister():
    import winreg

    hk = winreg.HKEY_CURRENT_USER
    _delete_tree(winreg, hk, rf"Software\Classes\{PROG_ID}")
    _delete_tree(winreg, hk, r"Software\Classes\Applications\tk-pdf.exe")
    _delete_tree(winreg, hk, STATE_KEY)
    _delete_value(winreg, r"Software\Classes\.pdf\OpenWithProgids", PROG_ID)
    for name in (APP_NAME,) + OLD_APP_NAMES:
        _delete_value(winreg, r"Software\RegisteredApplications", name)
    _notify()


def _delete_value(winreg, path, name):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, name)
    except OSError:
        pass
