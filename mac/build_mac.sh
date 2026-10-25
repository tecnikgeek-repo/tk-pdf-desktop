#!/bin/bash
# Crea dist/tk-pdf-<versione>-mac-<arch>.dmg. Da eseguire su un Mac (o sul runner macOS di GitHub).
# Uso: bash mac/build_mac.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
ARCH="$(uname -m)"
PY="${PYTHON:-python3}"
VERSION="$($PY -c "import re;print(re.search(r'VERSION = \"(.+)\"', open('tkpdf/__init__.py').read()).group(1))")"
echo "== tk-pdf $VERSION per macOS ($ARCH)"

$PY -m venv .venv-mac
# shellcheck disable=SC1091
source .venv-mac/bin/activate
python -m pip install --quiet --upgrade pip
python -m pip install --quiet "pyside6-essentials==6.11.*" "pymupdf==1.28.*" certifi pyinstaller \
    pyobjc-core pyobjc-framework-Vision

echo "== icona"
python tools_make_icon.py --iconset
iconutil -c icns assets/tk-pdf.iconset -o assets/tk-pdf.icns

echo "== app"
rm -rf build dist
pyinstaller --noconfirm --clean mac/tk-pdf-mac.spec
APP="dist/TK PDF.app"
# nome mostrato da Finder e Launchpad: «tk-pdf» (il file resta «TK PDF.app» per gli aggiornamenti automatici)
for lang in it en; do
    mkdir -p "$APP/Contents/Resources/$lang.lproj"
    printf 'CFBundleDisplayName = "tk-pdf";\nCFBundleName = "tk-pdf";\n' >"$APP/Contents/Resources/$lang.lproj/InfoPlist.strings"
done
# licenze: versioni esatte dei componenti di questo pacchetto in coda a COMPONENTI.txt (prima della firma ad hoc)
LIC="$APP/Contents/Resources/licenze"
[ -f "$LIC/COMPONENTI.txt" ] || { echo "MANCANO LE LICENZE NEL PACCHETTO"; exit 1; }
python - "$LIC/COMPONENTI.txt" <<'EOF'
import sys, ssl, importlib.metadata as m
with open(sys.argv[1], "a", encoding="utf-8") as f:
    f.write("\nVERSIONI ESATTE IN QUESTO PACCHETTO (macOS)\n")
    f.write("Python %s\n%s\n" % (sys.version.split()[0], ssl.OPENSSL_VERSION))
    for n in ("pyside6_essentials", "shiboken6", "pymupdf", "certifi", "pyobjc-core", "pyobjc-framework-Vision"):
        f.write("%s %s\n" % (n, m.version(n)))
EOF
codesign --force --deep --sign - "$APP"

echo "== selftest"
SHOT="$ROOT/dist/selftest-$ARCH.png"
run_selftest() {
    "$APP/Contents/MacOS/TK PDF" "$ROOT/tests/prova.pdf" --selftest "$SHOT" &
    local pid=$!
    for _ in $(seq 1 60); do
        kill -0 "$pid" 2>/dev/null || break
        sleep 1
    done
    kill "$pid" 2>/dev/null || true
}
run_selftest
if [ ! -f "$SHOT" ]; then
    echo "   finestra non disponibile, riprovo in modalità offscreen"
    export QT_QPA_PLATFORM=offscreen
    run_selftest
    unset QT_QPA_PLATFORM
fi
[ -f "$SHOT" ] || { echo "SELFTEST FALLITO: l'app non si avvia"; exit 1; }
echo "   selftest OK"

echo "== test OCR (Apple Vision)"
OCR_OUT="$ROOT/dist/ocr-$ARCH.txt"
"$APP/Contents/MacOS/TK PDF" --ocr-test "$ROOT/tests/ocr.png" "$OCR_OUT" || true
cat "$OCR_OUT" 2>/dev/null || true
grep -q "OCR" "$OCR_OUT" 2>/dev/null || { echo "TEST OCR FALLITO"; exit 1; }
echo "   test OCR OK"

echo "== dmg"
STAGE="$(mktemp -d)"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applicazioni"
cp mac/LEGGIMI.txt "$STAGE/Leggimi - primo avvio.txt"
DMG="dist/tk-pdf-$VERSION-mac-$ARCH.dmg"
# i runner macOS a volte danno «Resource busy»: si riprova qualche volta
for tentativo in 1 2 3 4; do
    if hdiutil create -volname "tk-pdf $VERSION" -srcfolder "$STAGE" -ov -format UDZO "$DMG"; then
        break
    fi
    echo "   hdiutil occupato, riprovo ($tentativo)"
    sleep 6
    [ "$tentativo" = "4" ] && { echo "CREAZIONE DMG FALLITA"; exit 1; }
done
rm -rf "$STAGE"
echo "== Creato $DMG ($(du -h "$DMG" | cut -f1))"

if [ "${SKIP_UPDATE_TEST:-0}" != "1" ]; then
    echo "== test aggiornamento automatico"
    TESTAPP="$HOME/Applications/TK PDF.app"
    mkdir -p "$HOME/Applications"
    rm -rf "$TESTAPP"
    cp -R "$APP" "$TESTAPP"
    BEFORE="$(stat -f %i "$TESTAPP/Contents/Info.plist")"
    COPY="$(mktemp -d)/tk-pdf-test.dmg"
    cp "$DMG" "$COPY"   # lo script di aggiornamento cancella il dmg usato
    SHA="$(shasum -a 256 "$COPY" | cut -d' ' -f1)"
    SIZE="$(stat -f %z "$COPY")"
    MANIFEST="$(mktemp -d)/tk-pdf.json"
    printf '{"version":"99.0.0","notes":["test"],"mac-%s":{"url":"file://%s","sha256":"%s","size":%s}}' "$ARCH" "$COPY" "$SHA" "$SIZE" > "$MANIFEST"
    # aggiornamenti firmati: chiave usa e getta solo per questo test (la vera resta sul PC di Pietro)
    read -r SEME PUB <<< "$(python mac/firma_aggiornamenti.py prova)"
    TK_FIRMA_SEME_PROVA="$SEME" python mac/firma_aggiornamenti.py firma --slug tk-pdf "$MANIFEST"
    TK_AGGIORNAMENTI_PROVA="$PUB" "$TESTAPP/Contents/MacOS/TK PDF" --update-test "file://$MANIFEST" --no-relaunch
    AFTER="$BEFORE"
    for _ in $(seq 1 120); do
        if [ -f "$TESTAPP/Contents/Info.plist" ]; then
            # il bundle può sparire tra il controllo e stat (sostituzione in corso): non fermare lo script
            AFTER="$(stat -f %i "$TESTAPP/Contents/Info.plist" 2>/dev/null || echo "$BEFORE")"
            [ "$AFTER" != "$BEFORE" ] && break
        fi
        sleep 1
    done
    cat "$HOME/Library/Application Support/tk-pdf/aggiornamento.log" 2>/dev/null || true
    if [ "$AFTER" = "$BEFORE" ] || [ ! -x "$TESTAPP/Contents/MacOS/TK PDF" ]; then
        echo "TEST AGGIORNAMENTO FALLITO"
        exit 1
    fi
    rm -rf "$TESTAPP"
    echo "   aggiornamento OK (bundle sostituito)"
fi
