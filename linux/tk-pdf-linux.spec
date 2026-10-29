# -*- mode: python -*-
# PyInstaller: crea la cartella «dist/tk-pdf» per Linux, poi build_linux.sh la mette nell'AppImage (insieme alla
# cartella di Tesseract preparata da linux/prepara_tesseract.sh). Uso: pyinstaller --noconfirm --clean linux/tk-pdf-linux.spec
import os
import re
import shutil
import sys
from importlib import metadata

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
with open(os.path.join(ROOT, "tkpdf", "__init__.py"), encoding="utf-8") as fh:
    VERSION = re.search(r'VERSION = "(.+)"', fh.read()).group(1)

# licenze (finiscono in _internal/licenze): AGPL di tk-pdf, elenco dei componenti, testi generici, file di licenza
# ORIGINALI dei pacchetti Python inclusi, licenza di Python, Tesseract con le sue librerie, libxcb-cursor
LIC = os.path.join(ROOT, "build", "licenze")
shutil.rmtree(LIC, ignore_errors=True)
shutil.copytree(os.path.join(ROOT, "licenze"), LIC)
for pkg in ("pymupdf", "certifi", "pyside6_essentials", "shiboken6"):
    try:
        dist = metadata.distribution(pkg)
    except metadata.PackageNotFoundError:
        continue
    for f in dist.files or []:
        name = os.path.basename(str(f))
        if ".dist-info" in str(f) and re.match(r"(LICEN[CS]E|COPYING|NOTICE)", name):
            n = re.sub(r"\.txt$", "", name).replace(".", "-")
            shutil.copy(str(f.locate()), os.path.join(LIC, f"{pkg.lower()}-{n}.txt"))
for cand in (os.path.join(os.path.dirname(os.__file__), "LICENSE.txt"), os.path.join(sys.base_prefix, "LICENSE.txt"),
             f"/usr/share/doc/python{sys.version_info[0]}.{sys.version_info[1]}/copyright"):
    if os.path.isfile(cand):
        shutil.copy(cand, os.path.join(LIC, "Python-LICENSE.txt"))
        break
tess_lic = os.path.join(ROOT, "build", "tesseract", "licenze", "Tesseract-OCR-e-librerie.txt")
if os.path.isfile(tess_lic):
    shutil.copy(tess_lic, LIC)
xcb_lic = os.path.join(ROOT, "build", "xcb-cursor", "copyright")
if os.path.isfile(xcb_lic):
    shutil.copy(xcb_lic, os.path.join(LIC, "libxcb-cursor-LICENSE.txt"))

extra_bin = []
xcb_lib = os.path.join(ROOT, "build", "xcb-cursor", "libxcb-cursor.so.0")
if os.path.isfile(xcb_lib):
    extra_bin.append((xcb_lib, "."))

a = Analysis(
    [os.path.join(ROOT, "run.py")],
    pathex=[ROOT],
    binaries=extra_bin,
    datas=[(os.path.join(ROOT, "build", "tk-pdf-512.png"), "assets"), (LIC, "licenze")],
    hiddenimports=["PySide6.QtPrintSupport", "PySide6.QtSvg", "tkpdf.ocr_linux", "tkpdf.tk_linux"],
    excludes=["tkinter", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtWebEngineCore", "PySide6.QtMultimedia"],
)

# componenti Qt non usati da un'app a widget
DROP = ("QtQuick", "QtQml", "QtVirtualKeyboard", "QtPdf", "libqpdf", "QtWebEngine", "Qt3D", "QtMultimedia")
a.binaries = [b for b in a.binaries if not any(k in b[0] for k in DROP)]
# stampa: si usa la libcups del sistema (c'è in ogni Ubuntu e parla con il suo servizio di stampa)
a.binaries = [b for b in a.binaries if not os.path.basename(b[0]).startswith("libcups.so")]
a.datas = [d for d in a.datas if not any(k in d[0] for k in DROP)]

pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="tk-pdf", console=False, strip=False)
coll = COLLECT(exe, a.binaries, a.datas, name="tk-pdf")
