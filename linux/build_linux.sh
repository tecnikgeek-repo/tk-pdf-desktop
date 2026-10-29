#!/bin/bash
# Crea dist/tk-pdf-<versione>-linux-<arch>.AppImage. Da eseguire su Linux (Ubuntu di casa o runner di GitHub).
# Uso: bash linux/build_linux.sh
# Usa al massimo METÀ dei processori (JOBS per cambiarlo): con tutti, sul PC di casa la memoria si riempie.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
JOBS="${JOBS:-$(( $(nproc) / 2 > 0 ? $(nproc) / 2 : 1 ))}"
if [ -z "${TK_BUILD_LIMITATA:-}" ] && command -v taskset >/dev/null; then
    export TK_BUILD_LIMITATA=1
    exec nice -n 10 taskset -c "0-$(( JOBS - 1 ))" bash "$0" "$@"
fi
ARCH="$(uname -m)"
PY="${PYTHON:-python3}"
VERSION="$($PY -c "import re;print(re.search(r'VERSION = \"(.+)\"', open('tkpdf/__init__.py').read()).group(1))")"
APPIMAGETOOL_VER="1.9.0"
export OMP_THREAD_LIMIT="$JOBS"
echo "== tk-pdf $VERSION per Linux ($ARCH), $JOBS processori"

$PY -m venv .venv-linux
# shellcheck disable=SC1091
source .venv-linux/bin/activate
python -m pip install --quiet --upgrade pip
python -m pip install --quiet "pyside6-essentials==6.11.*" "pymupdf==1.28.*" certifi pyinstaller

mkdir -p dist build
echo "== Tesseract (riconoscimento del testo): preso dai pacchetti Ubuntu, non installato"
bash linux/prepara_tesseract.sh build/tesseract
echo "== prova dell'OCR (testo italiano con accenti e prezzi, posizioni delle parole)"
TK_TESSERACT_DIR="$ROOT/build/tesseract" python tests/verifica_ocr.py | tail -n 1

if [ "${SKIP_SMOKE_TEST:-0}" != "1" ]; then
    echo "== collaudo delle funzioni (tests/smoke.py)"
    TKPDF_DATI="$(mktemp -d)" QT_QPA_PLATFORM=offscreen python tests/smoke.py > "dist/test-smoke-linux-$ARCH.txt" 2>&1 || {
        tail -n 40 "dist/test-smoke-linux-$ARCH.txt"; echo "COLLAUDO FALLITO"; exit 1; }
    tail -n 3 "dist/test-smoke-linux-$ARCH.txt"
    grep -q "^ERRORI: \[\]$" "dist/test-smoke-linux-$ARCH.txt" || { echo "COLLAUDO FALLITO: errori nelle funzioni"; exit 1; }
fi

echo "== icona"
QT_QPA_PLATFORM=offscreen python -c "
import sys; sys.path.insert(0, '.')
from PySide6.QtGui import QGuiApplication
app = QGuiApplication([])
from tkpdf.icon import render_icon
assert render_icon(512).save('build/tk-pdf-512.png')"

echo "== libxcb-cursor (serve a Qt sotto X11; su Wayland no): presa dal pacchetto Ubuntu, non installata"
rm -rf build/xcb-cursor && mkdir -p build/xcb-cursor
(cd build/xcb-cursor && apt-get download libxcb-cursor0 >/dev/null && dpkg-deb -x libxcb-cursor0_*.deb x \
    && cp x/usr/lib/*/libxcb-cursor.so.0.* libxcb-cursor.so.0 && cp x/usr/share/doc/libxcb-cursor0/copyright .) \
    || echo "   libxcb-cursor non disponibile: il pacchetto funzionerà solo su Wayland o con la libreria di sistema"

echo "== programma"
rm -rf build/tk-pdf-linux dist/tk-pdf
pyinstaller --noconfirm --clean --workpath build/tk-pdf-linux linux/tk-pdf-linux.spec
# versioni esatte dei componenti di questo pacchetto in coda a COMPONENTI.txt
python - "dist/tk-pdf/_internal/licenze/COMPONENTI.txt" <<'EOF'
import sys, ssl, importlib.metadata as m
with open(sys.argv[1], "a", encoding="utf-8") as f:
    f.write("\nVERSIONI ESATTE IN QUESTO PACCHETTO (Linux)\n")
    f.write("Python %s\n%s\n" % (sys.version.split()[0], ssl.OPENSSL_VERSION))
    for n in ("pyside6_essentials", "shiboken6", "pymupdf", "certifi", "pyinstaller"):
        f.write("%s %s\n" % (n, m.version(n)))
EOF

echo "== AppImage"
APPDIR="build/AppDir"
rm -rf "$APPDIR" && mkdir -p "$APPDIR/usr/lib"
cp -a dist/tk-pdf "$APPDIR/usr/lib/tk-pdf"
# Tesseract accanto all'eseguibile (tkpdf/ocr_linux.py lo cerca lì), con i permessi di esecuzione
cp -a build/tesseract "$APPDIR/usr/lib/tk-pdf/tesseract"
cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/lib/tk-pdf/tk-pdf" "$@"
EOF
chmod 755 "$APPDIR/AppRun"
cat > "$APPDIR/tk-pdf.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=tk-pdf
GenericName=Lettore PDF
Comment=Lettore ed editor PDF: leggi, annota, firma e modifica i PDF (TecnikGeek)
Exec=tk-pdf %U
Icon=tk-pdf
Terminal=false
Categories=Office;Viewer;Graphics;
MimeType=application/pdf;image/png;image/jpeg;image/tiff;
StartupWMClass=tk-pdf
EOF
cp build/tk-pdf-512.png "$APPDIR/tk-pdf.png"
ln -sf tk-pdf.png "$APPDIR/.DirIcon"

TOOLS="${TK_STRUMENTI_BUILD:-$HOME/.cache/tk-build}"
TOOL="$TOOLS/appimagetool-$APPIMAGETOOL_VER-$ARCH.AppImage"
if [ ! -x "$TOOL" ]; then
    mkdir -p "$TOOLS"
    curl -fsSL -o "$TOOL.part" \
        "https://github.com/AppImage/appimagetool/releases/download/$APPIMAGETOOL_VER/appimagetool-$ARCH.AppImage"
    chmod 755 "$TOOL.part" && mv "$TOOL.part" "$TOOL"
fi
OUT="dist/tk-pdf-$VERSION-linux-$ARCH.AppImage"
rm -f "$OUT"
APPIMAGE_EXTRACT_AND_RUN=1 ARCH="$ARCH" "$TOOL" --no-appstream \
    --mksquashfs-opt -processors --mksquashfs-opt "$JOBS" "$APPDIR" "$OUT" > build/appimagetool.log 2>&1 || {
    tail -n 30 build/appimagetool.log; echo "CREAZIONE APPIMAGE FALLITA"; exit 1; }
chmod 755 "$OUT"
echo "== Creato $OUT ($(du -h "$OUT" | cut -f1))"

echo "== selftest (dal file AppImage)"
SHOT="$ROOT/dist/selftest-linux-$ARCH.png"
TXT="$ROOT/dist/selftest-linux-$ARCH.txt"
rm -f "$SHOT" "$TXT"
QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}" timeout 90 "$OUT" "$ROOT/tests/prova.pdf" --selftest "$SHOT" || true
[ -f "$SHOT" ] || { echo "SELFTEST FALLITO: il programma non si avvia"; exit 1; }
cat "$TXT"; echo
grep -q "^OK" "$TXT" || { echo "SELFTEST FALLITO: componenti mancanti nel pacchetto"; exit 1; }

echo "== OCR dal file AppImage"
OCR_OUT="$ROOT/dist/ocr-linux-$ARCH.txt"
rm -f "$OCR_OUT"
timeout 90 "$OUT" --ocr-test "$ROOT/tests/ocr-it.png" "$OCR_OUT" || true
python tests/verifica_ocr.py "$OCR_OUT" || { echo "TEST OCR FALLITO"; exit 1; }

if [ "${SKIP_UPDATE_TEST:-0}" != "1" ]; then
    echo "== test aggiornamento automatico"
    WORK="$(mktemp -d)"
    TESTAPP="$WORK/Programmi/tk-pdf.AppImage"     # copia «installata» che deve essere sostituita
    mkdir -p "$(dirname "$TESTAPP")"
    cp "$OUT" "$TESTAPP"
    BEFORE="$(stat -c %i "$TESTAPP")"
    COPY="$WORK/tk-pdf-nuova.AppImage"
    cp "$OUT" "$COPY"   # lo script di aggiornamento cancella il file usato
    SHA="$(sha256sum "$COPY" | cut -d' ' -f1)"
    SIZE="$(stat -c %s "$COPY")"
    MANIFEST="$WORK/tk-pdf.json"
    printf '{"version":"99.0.0","notes":["test"],"linux-%s":{"url":"file://%s","sha256":"%s","size":%s}}' \
        "$ARCH" "$COPY" "$SHA" "$SIZE" > "$MANIFEST"
    # aggiornamenti firmati: chiave usa e getta solo per questo test (la vera resta sul PC di Pietro)
    read -r SEME PUB <<< "$(python mac/firma_aggiornamenti.py prova)"
    TK_FIRMA_SEME_PROVA="$SEME" python mac/firma_aggiornamenti.py firma --slug tk-pdf "$MANIFEST"
    export TKPDF_DATI="$WORK/dati"
    # prima la prova contraria: manifest firmato con un'altra chiave = rifiutato
    read -r _ ALTRA <<< "$(python mac/firma_aggiornamenti.py prova)"
    TK_AGGIORNAMENTI_PROVA="$ALTRA" "$TESTAPP" --update-test "file://$MANIFEST" --no-relaunch || true
    grep -q "rifiutato" "$TKPDF_DATI/update-test.log" || { cat "$TKPDF_DATI/update-test.log"; echo "TEST FIRMA FALLITO: accettato con la chiave sbagliata"; exit 1; }
    TK_AGGIORNAMENTI_PROVA="$PUB" "$TESTAPP" --update-test "file://$MANIFEST" --no-relaunch
    AFTER="$BEFORE"
    for _ in $(seq 1 120); do
        AFTER="$(stat -c %i "$TESTAPP" 2>/dev/null || echo "$BEFORE")"
        [ "$AFTER" != "$BEFORE" ] && break
        sleep 1
    done
    cat "$TKPDF_DATI/update-test.log" "$TKPDF_DATI/aggiornamento.log" 2>/dev/null || true
    unset TKPDF_DATI
    if [ "$AFTER" = "$BEFORE" ] || [ ! -x "$TESTAPP" ] || ! cmp -s "$TESTAPP" "$OUT"; then
        echo "TEST AGGIORNAMENTO FALLITO"
        exit 1
    fi
    rm -rf "$WORK"
    echo "   aggiornamento OK (file AppImage sostituito, firma sbagliata rifiutata)"
fi
