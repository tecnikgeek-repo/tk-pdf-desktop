"""Disinstallazione della versione installata su Windows (senza exe dedicati: compatibile con Smart App Control)."""
import ctypes
import os
import subprocess
import sys
from ctypes import wintypes

UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\tk-pdf"
MB_YESNO, MB_ICONQUESTION, MB_ICONINFO, IDYES = 0x04, 0x20, 0x40, 6


def _msg(text, flags):
    return ctypes.windll.user32.MessageBoxW(None, text, "tk-pdf", flags)


def _process_paths():
    """Ritorna [(pid, percorso exe)] dei processi visibili (API Win32, niente dipendenze)."""
    psapi, kernel = ctypes.windll.psapi, ctypes.windll.kernel32
    arr = (wintypes.DWORD * 4096)()
    needed = wintypes.DWORD()
    psapi.EnumProcesses(ctypes.byref(arr), ctypes.sizeof(arr), ctypes.byref(needed))
    out = []
    for pid in arr[:needed.value // ctypes.sizeof(wintypes.DWORD)]:
        h = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            continue
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(1024)
            if kernel.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                out.append((pid, buf.value))
        finally:
            kernel.CloseHandle(h)
    return out


def kill_other_instances(root):
    prefix = os.path.normcase(os.path.join(root, ""))
    for pid, path in _process_paths():
        if pid != os.getpid() and os.path.normcase(path).startswith(prefix):
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True,
                           creationflags=0x08000000)


def run():
    import winreg

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if not any(os.path.exists(os.path.join(root, "python", n)) for n in ("tk-pdf.exe", "pythonw.exe")):
        _msg("La disinstallazione è disponibile solo per la versione installata di tk-pdf.", MB_ICONINFO)
        return 0
    if _msg("Vuoi disinstallare tk-pdf?\n\nLe firme salvate e le impostazioni restano nel tuo profilo.",
            MB_YESNO | MB_ICONQUESTION) != IDYES:
        return 0

    kill_other_instances(root)
    try:
        from tkpdf.winreg_assoc import unregister
        unregister()
    except Exception:
        pass
    shell = ctypes.windll.shell32
    for folder_id in (0x0002, 0x0010):  # CSIDL_PROGRAMS, CSIDL_DESKTOPDIRECTORY
        buf = ctypes.create_unicode_buffer(260)
        if shell.SHGetFolderPathW(None, folder_id, None, 0, buf) == 0:
            for name in ("tk-pdf.lnk", "tkPDF.lnk", "TK PDF.lnk"):  # «tkPDF.lnk» 1.0.18-1.0.28, «TK PDF.lnk» fino alla 1.0.17
                lnk = os.path.join(buf.value, name)
                try:
                    if os.path.exists(lnk):
                        os.remove(lnk)
                except OSError:
                    pass
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
    except OSError:
        pass

    _msg("tk-pdf è stato disinstallato.", MB_ICONINFO)
    # cancella solo i file di tk-pdf (mai la cartella intera con /s) dopo la chiusura di questo processo
    q = lambda p: f'"{p}"'
    cmd = (f"ping 127.0.0.1 -n 4 >nul & rmdir /s /q {q(os.path.join(root, 'python'))}"
           f" & rmdir /s /q {q(os.path.join(root, 'tkpdf'))} & rmdir /s /q {q(os.path.join(root, 'assets'))}"
           f" & del /q {q(os.path.join(root, 'run.py'))} {q(os.path.join(root, 'tk-pdf.exe'))}"
           f" & rmdir {q(root)}")
    subprocess.Popen(["cmd.exe", "/c", cmd], cwd=os.environ.get("TEMP", "C:\\"), creationflags=0x08000000 | 0x00000008,
                     close_fds=True)
    return 0


if __name__ == "__main__":
    sys.exit(run())
