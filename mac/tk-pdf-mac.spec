# -*- mode: python -*-
# PyInstaller: crea "TK PDF.app" per macOS (nome visibile «tk-pdf»: il nome del file resta «TK PDF.app»
# perché gli aggiornamenti automatici delle versioni installate cercano quel bundle nel dmg). Uso: pyinstaller --noconfirm --clean mac/tk-pdf-mac.spec
import os
import re

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
with open(os.path.join(ROOT, "tkpdf", "__init__.py"), encoding="utf-8") as fh:
    VERSION = re.search(r'VERSION = "(.+)"', fh.read()).group(1)

a = Analysis(
    [os.path.join(ROOT, "run.py")],
    pathex=[ROOT],
    # testi delle licenze (AGPL di tk-pdf + componenti inclusi): vanno in Contents/Resources/licenze
    datas=[(os.path.join(ROOT, "licenze"), "licenze")],
    hiddenimports=["PySide6.QtPrintSupport", "Vision", "Foundation", "objc"],
    excludes=["tkinter", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtWebEngineCore", "PySide6.QtMultimedia"],
)

# componenti Qt non usati da un'app a widget
DROP = ("QtQuick", "QtQml", "QtVirtualKeyboard", "QtPdf", "libqpdf", "QtWebEngine", "Qt3D", "QtMultimedia")
a.binaries = [b for b in a.binaries if not any(k in b[0] for k in DROP)]
a.datas = [d for d in a.datas if not any(k in d[0] for k in DROP)]

pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="TK PDF", console=False, argv_emulation=False)
coll = COLLECT(exe, a.binaries, a.datas, name="TK PDF")
app = BUNDLE(
    coll,
    name="TK PDF.app",
    icon=os.path.join(ROOT, "assets", "tk-pdf.icns"),
    bundle_identifier="com.tecnikgeek.tkpdf",
    version=VERSION,
    info_plist={
        "CFBundleName": "tk-pdf",
        "CFBundleDisplayName": "tk-pdf",
        # il Finder e il Launchpad mostrano CFBundleDisplayName solo con i nomi localizzati (it/en.lproj da build_mac.sh)
        "LSHasLocalizedDisplayName": True,
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "NSHighResolutionCapable": True,
        "NSRequiresAquaSystemAppearance": True,
        "NSHumanReadableCopyright": "© 2026 Pietro De Filippis (TecnikGeek) - software libero AGPL-3.0",
        "LSApplicationCategoryType": "public.app-category.productivity",
        "CFBundleDocumentTypes": [
            {
                "CFBundleTypeName": "Documento PDF",
                "CFBundleTypeRole": "Editor",
                "LSHandlerRank": "Alternate",
                "LSItemContentTypes": ["com.adobe.pdf"],
            },
            {
                "CFBundleTypeName": "Immagine",
                "CFBundleTypeRole": "Viewer",
                "LSHandlerRank": "Alternate",
                "LSItemContentTypes": ["public.png", "public.jpeg", "public.tiff"],
            },
        ],
    },
)
