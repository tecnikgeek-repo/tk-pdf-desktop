"""Scrittura del file su disco a prova di blocchi di Windows.

Salvare sostituisce il file (scrive un temporaneo e poi lo rinomina): su Windows il rinomino fallisce
se qualcuno tiene aperto il file — il riquadro di anteprima di Esplora file, un lettore PDF, Dropbox
mentre sincronizza, l'antivirus — oppure se il file è in sola lettura. Qui si riprova e, se proprio non
si può, si dice CHI lo sta bloccando (e la finestra salva una copia numerata). Il file originale non viene
mai riscritto sul posto: o viene sostituito per intero o resta com'era. La sola lettura si toglie solo se
l'utente lo chiede (ReadOnlyError → domanda → allow_read_only=True)."""
import ctypes
import os
import re
import sys
import time

IS_WIN = sys.platform == "win32"
FILE_ATTRIBUTE_READONLY = 0x1
RETRIES = (0.15, 0.35, 0.7, 1.2)  # i blocchi di Dropbox/antivirus durano in genere meno di un secondo


class SaveError(Exception):
    """Messaggio già pronto per l'utente; `can_retry` dice se ha senso riprovare."""

    def __init__(self, message, can_retry=True):
        super().__init__(message)
        self.can_retry = can_retry


class ReadOnlyError(SaveError):
    """Il file è in sola lettura: si sovrascrive solo se l'utente lo chiede."""


def _is_read_only(path):
    if not os.path.exists(path):
        return False
    if IS_WIN:
        attrs = _attributes(path)
        return attrs is not None and bool(attrs & FILE_ATTRIBUTE_READONLY)
    return not os.access(path, os.W_OK)


def _attributes(path):
    if not IS_WIN:
        return None
    attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
    return None if attrs == -1 else attrs


def _set_attributes(path, attrs):
    if IS_WIN and attrs is not None:
        ctypes.windll.kernel32.SetFileAttributesW(str(path), attrs)


def locking_programs(path):
    """Nomi dei programmi che tengono aperto il file (Restart Manager di Windows)."""
    if not IS_WIN or not os.path.exists(path):
        return []
    try:
        rm = ctypes.WinDLL("rstrtmgr")
        session = ctypes.c_uint()
        key = ctypes.create_unicode_buffer(256)
        if rm.RmStartSession(ctypes.byref(session), 0, key) != 0:
            return []
        try:
            files = (ctypes.c_wchar_p * 1)(str(path))
            if rm.RmRegisterResources(session, 1, files, 0, None, 0, None) != 0:
                return []

            class RM_UNIQUE_PROCESS(ctypes.Structure):
                # FILETIME = due DWORD: con un solo campo da 8 byte l'allineamento sfalsa tutti i nomi
                _fields_ = [("dwProcessId", ctypes.c_uint),
                            ("ProcessStartTimeLow", ctypes.c_uint),
                            ("ProcessStartTimeHigh", ctypes.c_uint)]

            class RM_PROCESS_INFO(ctypes.Structure):
                _fields_ = [("Process", RM_UNIQUE_PROCESS),
                            ("strAppName", ctypes.c_wchar * 256),
                            ("strServiceShortName", ctypes.c_wchar * 64),
                            ("ApplicationType", ctypes.c_uint),
                            ("AppStatus", ctypes.c_uint),
                            ("TSSessionId", ctypes.c_uint),
                            ("bRestartable", ctypes.c_int)]

            needed = ctypes.c_uint(0)
            count = ctypes.c_uint(0)
            reason = ctypes.c_uint(0)
            rm.RmGetList(session, ctypes.byref(needed), ctypes.byref(count), None, ctypes.byref(reason))
            if needed.value == 0:
                return []
            count = ctypes.c_uint(needed.value)
            infos = (RM_PROCESS_INFO * needed.value)()
            if rm.RmGetList(session, ctypes.byref(needed), ctypes.byref(count), infos, ctypes.byref(reason)) != 0:
                return []
            names, me = [], os.getpid()
            for i in range(count.value):
                if infos[i].Process.dwProcessId == me:
                    continue
                name = (infos[i].strAppName or "").strip()
                if name and name not in names:
                    names.append(name)
            return names
        finally:
            rm.RmEndSession(session)
    except Exception:
        return []


def _friendly(name):
    low = name.lower()
    if "explorer" in low:
        return "Esplora file (chiudi il riquadro di anteprima o deseleziona il file)"
    if "dropbox" in low:
        return "Dropbox (sincronizzazione in corso)"
    if "onedrive" in low:
        return "OneDrive (sincronizzazione in corso)"
    return name


def _app_path():
    """Percorso da autorizzare nell'antivirus."""
    exe = sys.executable or ""
    if exe.lower().endswith("tk-pdf.exe"):
        return exe
    guess = os.path.join(os.path.dirname(exe), "tk-pdf.exe")
    return guess if os.path.exists(guess) else exe


def antivirus_names():
    """Antivirus installati, come li dichiara Windows."""
    if not IS_WIN:
        return []
    try:
        import subprocess
        out = subprocess.run([os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32",
                                           "WindowsPowerShell", "v1.0", "powershell.exe"),
                              "-NoProfile", "-NonInteractive", "-Command",
                              "Get-CimInstance -Namespace root/SecurityCenter2 -ClassName AntiVirusProduct "
                              "| Select-Object -ExpandProperty displayName"],
                             capture_output=True, text=True, timeout=20, creationflags=0x08000000)
        return [line.strip() for line in out.stdout.splitlines() if line.strip()]
    except Exception:
        return []


def protection_help():
    """(testo, percorso dell'app) per spiegare come autorizzare tk-pdf nell'antivirus."""
    app = _app_path()
    names = [n for n in antivirus_names()]
    low = " ".join(names).lower()
    righe = ["Il file originale non si lascia modificare: è l'antivirus che sorveglia le cartelle personali "
             "(Desktop, Documenti, Immagini) e lascia cambiare i file solo ai programmi autorizzati. "
             "tk-pdf i file nuovi può crearli, perciò salva una copia numerata e non perdi niente.", ""]
    if names:
        righe.append("Antivirus su questo computer: " + ", ".join(names))
        righe.append("")
    righe.append("Per autorizzare tk-pdf una volta per tutte:")
    voci = []
    if "avast" in low or "avg" in low:
        voci.append("• Avast / AVG: Protezione → Scudo ransomware → App bloccate / Consenti app → aggiungi tk-pdf")
    if "defender" in low or "microsoft" in low:
        voci.append("• Sicurezza di Windows: Protezione da virus e minacce → Gestisci la protezione ransomware "
                    "→ Consenti un'app tramite Accesso alle cartelle controllate")
    if not voci:
        voci.append("• Avast / AVG: Protezione → Scudo ransomware → App bloccate / Consenti app → aggiungi tk-pdf")
        voci.append("• Sicurezza di Windows: Protezione da virus e minacce → Gestisci la protezione ransomware "
                    "→ Consenti un'app tramite Accesso alle cartelle controllate")
    voci.append("• Altri antivirus (Norton, Bitdefender, Kaspersky, ESET…): nelle impostazioni cerca "
                "«ransomware», «cartelle protette» o «app consentite» e aggiungi tk-pdf. Di solito il programma "
                "appena bloccato è già nell'elenco e basta consentirlo.")
    righe += voci
    righe += ["", "Percorso di tk-pdf, già copiato negli appunti (la cartella AppData è nascosta: incollalo "
                  "invece di cercarlo sfogliando):", app]
    return "\n".join(righe), app


def _diagnose(path, exc):
    folder = os.path.dirname(os.path.abspath(path)) or "."
    programs = locking_programs(path)
    if programs:
        chi = "\n".join(f"  • {_friendly(p)}" for p in programs)
        return SaveError(f"Il file è aperto in un altro programma:\n{chi}\n\n"
                         "Chiudilo e riprova, oppure usa «Salva con nome».")
    attrs = _attributes(path)
    if attrs is not None and attrs & FILE_ATTRIBUTE_READONLY:
        return SaveError("Il file è in sola lettura e non si riesce a togliere questa protezione.\n"
                         "Usa «Salva con nome» per salvare una copia.", can_retry=False)
    if os.path.exists(path) and not os.access(path, os.W_OK):
        return SaveError("Non hai i permessi per modificare questo file.\nUsa «Salva con nome».", can_retry=False)
    if not os.access(folder, os.W_OK):
        return SaveError(f"Non hai i permessi per scrivere nella cartella:\n{folder}\n\n"
                         "Usa «Salva con nome» e scegli un'altra cartella.", can_retry=False)
    if getattr(exc, "winerror", None) == 5 or isinstance(exc, PermissionError):
        return SaveError("Windows nega la modifica di questo file: i permessi non lo consentono oppure "
                         "un antivirus lo sta proteggendo.")
    return SaveError(f"Il file non può essere sostituito adesso ({exc}).\n"
                     "Riprova tra qualche secondo oppure usa «Salva con nome».")


def write_file(path, data, allow_read_only=False):
    """Scrive data in path sostituendo il file esistente. Alza SaveError con un messaggio chiaro
    (ReadOnlyError se il file è in sola lettura e allow_read_only è falso)."""
    folder = os.path.dirname(os.path.abspath(path)) or "."
    if not os.path.isdir(folder):
        raise SaveError(f"La cartella non esiste più:\n{folder}", can_retry=False)
    read_only = _is_read_only(path)
    if read_only and not allow_read_only:
        raise ReadOnlyError("Il file è in sola lettura.\nUsa «Salva con nome» per salvare una copia.",
                            can_retry=False)
    tmp = path + ".tkpdf-tmp"
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())  # i dati sono sul disco prima di sostituire l'originale
    except OSError as exc:
        _quiet_remove(tmp)
        if not os.access(folder, os.W_OK):
            raise SaveError(f"Non hai i permessi per scrivere nella cartella:\n{folder}\n\n"
                            "Usa «Salva con nome» e scegli un'altra cartella.", can_retry=False) from exc
        raise SaveError(f"Impossibile scrivere il file:\n{exc}") from exc

    _hydrate(path)
    last = None
    restore_attrs = restore_mode = None
    if read_only:
        # l'utente ha chiesto di sovrascrivere: si toglie la sola lettura e dopo si rimette com'era
        if IS_WIN:
            restore_attrs = _attributes(path)
            _set_attributes(path, restore_attrs & ~FILE_ATTRIBUTE_READONLY)
        else:
            try:
                restore_mode = os.stat(path).st_mode & 0o7777
            except OSError:
                pass
    try:
        for attempt, pause in enumerate((0.0,) + RETRIES):
            if pause:
                time.sleep(pause)
            try:
                os.replace(tmp, path)
                _sync_folder(folder)
                return
            except OSError as exc:
                last = exc
        # il rinomino non passa (file tenuto aperto, antivirus…): niente riscrittura sul posto, che a metà
        # lascerebbe un file rovinato; la finestra spiega e salva una copia numerata
        raise _diagnose(path, last)
    finally:
        _quiet_remove(tmp)
        if restore_attrs is not None and os.path.exists(path):
            _set_attributes(path, restore_attrs)
        if restore_mode is not None and os.path.exists(path):
            try:
                os.chmod(path, restore_mode)
            except OSError:
                pass


def _sync_folder(folder):
    """macOS: anche il nuovo nome va sul disco (su Windows non si può aprire una cartella così)."""
    if IS_WIN:
        return
    try:
        fd = os.open(folder, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def _hydrate(path):
    """File «solo online» di OneDrive/Dropbox: si scarica prima, altrimenti la sostituzione può fallire."""
    attrs = _attributes(path)
    if attrs is None or not attrs & (0x400000 | 0x40000):  # RECALL_ON_DATA_ACCESS | RECALL_ON_OPEN
        return
    try:
        with open(path, "rb") as fh:
            fh.read(1)
    except OSError:
        pass


def free_name(path):
    """Nome libero accanto all'originale, come fa Windows: «documento (1).pdf», poi (2), (3)…"""
    base, ext = os.path.splitext(path)
    base = re.sub(r" \(\d+\)$", "", base)  # non accumula «(1) (2)» sullo stesso file
    n = 1
    while True:
        candidate = f"{base} ({n}){ext}"
        if not os.path.exists(candidate):
            return candidate
        n += 1


def _quiet_remove(path):
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass
