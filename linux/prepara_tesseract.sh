#!/bin/bash
# Prepara la cartella di Tesseract da mettere nel pacchetto (niente viene installato nel sistema):
#   <uscita>/bin/tesseract, <uscita>/lib/ (librerie che servono davvero), <uscita>/tessdata/ (ita + eng),
#   <uscita>/licenze/Tesseract-OCR-e-librerie.txt (file copyright di ogni pacchetto Ubuntu usato).
# I .deb si scaricano con apt-get download e si aprono con dpkg-deb -x. Si includono tutte le librerie che il
# binario carica (chiusura di ldd) tranne quelle che ogni Linux ha di sicuro (glibc, libstdc++, libgcc, zlib):
# così funziona anche dove le versioni sono diverse (Ubuntu 24.04 ha libtiff6 al posto di libtiff5…).
# Copia IDENTICA in tk-pdf e tk-listino. Uso: bash linux/prepara_tesseract.sh <cartella di uscita>
set -euo pipefail

OUT="$(realpath -m "${1:?cartella di uscita}")"
WORK="$OUT.deb"
rm -rf "$OUT" "$WORK"
mkdir -p "$OUT/bin" "$OUT/lib" "$OUT/tessdata" "$OUT/licenze" "$WORK/deb" "$WORK/x"

# tesseract, dati italiano e inglese e le dipendenze (solo scaricate; poi si tiene solo ciò che serve)
PKGS="$(apt-cache depends --recurse --no-recommends --no-suggests --no-conflicts --no-breaks --no-replaces \
    --no-enhances tesseract-ocr tesseract-ocr-ita tesseract-ocr-eng 2>/dev/null | grep -v '^[ <]' | sort -u \
    | grep -Ev '^(fonts-|xfonts-|x11-common|lsb-base|sysvinit-utils|libc6$|libc-bin|gcc-[0-9]+-base|libgcc-s1|libstdc\+\+6|zlib1g$|debconf|dpkg|perl|tar$|ucf|sensible-utils|fontconfig-config|fontconfig$|tesseract-ocr-osd)' || true)"
[ -n "$PKGS" ] || { echo "apt-cache non trova tesseract-ocr"; exit 1; }
(cd "$WORK/deb" && for p in $PKGS; do apt-get download "$p" >/dev/null 2>&1 || echo "   (non scaricato: $p)"; done)
for deb in "$WORK"/deb/*.deb; do
    pkg="$(dpkg-deb -f "$deb" Package)"
    dpkg-deb -x "$deb" "$WORK/x/$pkg"
    printf '%s\t%s\n' "$pkg" "$(dpkg-deb -f "$deb" Version)" >> "$WORK/versioni.tsv"
done

python3 - "$WORK" "$OUT" <<'EOF'
import glob, os, re, shutil, subprocess, sys
work, out = sys.argv[1], sys.argv[2]
x = os.path.join(work, "x")
versioni = dict(l.rstrip("\n").split("\t") for l in open(os.path.join(work, "versioni.tsv"), encoding="utf-8"))
# mai incluse: ci sono in ogni Linux e devono essere quelle del sistema
SISTEMA = re.compile(r"^(linux-vdso|ld-linux|libc\.so|libm\.so|libdl\.so|libpthread\.so|librt\.so|libresolv\.so|"
                     r"libutil\.so|libstdc\+\+\.so|libgcc_s\.so|libz\.so)")
exe = os.path.join(x, "tesseract-ocr", "usr", "bin", "tesseract")
assert os.path.isfile(exe), "binario tesseract non trovato nel pacchetto"
dirs = sorted({os.path.dirname(p) for p in glob.glob(os.path.join(x, "*", "**", "*.so*"), recursive=True)})
r = subprocess.run(["ldd", exe], capture_output=True, text=True, env={"LD_LIBRARY_PATH": ":".join(dirs),
                                                                      "PATH": "/usr/bin:/bin"})
assert r.returncode == 0, r.stderr
pacchetti = {"tesseract-ocr"}
librerie = []
for riga in r.stdout.splitlines():
    m = re.match(r"\s*(\S+)\s+=>\s+(not found|\S+)", riga)
    if not m:
        continue
    soname, path = m.groups()
    if SISTEMA.match(soname):
        continue
    if path == "not found":
        sys.exit(f"libreria mancante: {soname}")
    if path.startswith(x + os.sep):
        pkg = os.path.relpath(path, x).split(os.sep)[0]
    else:  # presa dal sistema di build: si cerca il pacchetto per la licenza
        q = subprocess.run(["dpkg", "-S", os.path.realpath(path)], capture_output=True, text=True)
        pkg = q.stdout.split(":")[0].strip() if q.returncode == 0 else "?"
        print(f"   (dal sistema: {soname} -> {pkg})")
    shutil.copyfile(os.path.realpath(path), os.path.join(out, "lib", soname))
    librerie.append((soname, pkg))
    pacchetti.add(pkg)
shutil.copyfile(exe, os.path.join(out, "bin", "tesseract"))
os.chmod(os.path.join(out, "bin", "tesseract"), 0o755)
for lang in ("ita", "eng"):
    found = glob.glob(os.path.join(x, f"tesseract-ocr-{lang}", "usr", "share", "tesseract-ocr", "*", "tessdata",
                                   f"{lang}.traineddata"))
    assert found, f"dati {lang} non trovati"
    shutil.copyfile(found[0], os.path.join(out, "tessdata", f"{lang}.traineddata"))
    pacchetti.add(f"tesseract-ocr-{lang}")


def copyright_di(pkg):
    for base in (os.path.join(x, pkg), "/"):
        doc = os.path.join(base, "usr", "share", "doc", pkg)
        if os.path.islink(doc):  # cartella doc condivisa con un altro pacchetto (es. libjpeg-turbo8)
            alt = os.path.basename(os.readlink(doc))
            for b in (os.path.join(x, alt), "/"):
                f = os.path.join(b, "usr", "share", "doc", alt, "copyright")
                if os.path.isfile(f):
                    return f
        f = os.path.join(doc, "copyright")
        if os.path.isfile(f):
            return f
    return None


with open(os.path.join(out, "licenze", "Tesseract-OCR-e-librerie.txt"), "w", encoding="utf-8") as fh:
    fh.write("Tesseract OCR (Apache-2.0) e librerie incluse per il riconoscimento del testo su Linux.\n"
             "Prese dai pacchetti di Ubuntu (apt-get download), non modificate. Sorgenti: https://launchpad.net/ubuntu/+source/<pacchetto>\n\n"
             "LIBRERIE INCLUSE (file -> pacchetto versione)\n")
    for soname, pkg in librerie:
        fh.write(f"  {soname} -> {pkg} {versioni.get(pkg, '')}\n")
    fh.write("  tesseract -> tesseract-ocr " + versioni.get("tesseract-ocr", "") + "\n")
    for lang in ("ita", "eng"):
        fh.write(f"  tessdata/{lang}.traineddata -> tesseract-ocr-{lang} {versioni.get('tesseract-ocr-' + lang, '')}\n")
    for pkg in sorted(pacchetti):
        f = copyright_di(pkg)
        fh.write("\n" + "=" * 78 + f"\n{pkg} {versioni.get(pkg, '')}\n" + "=" * 78 + "\n")
        fh.write(open(f, encoding="utf-8", errors="replace").read() if f else "(file copyright non trovato)\n")
print(f"   {len(librerie)} librerie: " + " ".join(s for s, _ in librerie))
EOF

# prova: il binario parte con le sole librerie copiate (ambiente vuoto, come lo avvia il programma)
if env -i LD_LIBRARY_PATH="$OUT/lib" ldd "$OUT/bin/tesseract" | grep -q "not found"; then
    env -i LD_LIBRARY_PATH="$OUT/lib" ldd "$OUT/bin/tesseract" | grep "not found"; echo "LIBRERIE MANCANTI"; exit 1
fi
env -i LD_LIBRARY_PATH="$OUT/lib" LC_ALL=C "$OUT/bin/tesseract" --version 2>&1 | head -n 1
env -i LD_LIBRARY_PATH="$OUT/lib" LC_ALL=C "$OUT/bin/tesseract" --list-langs --tessdata-dir "$OUT/tessdata" 2>&1 | tail -n +2 | tr '\n' ' '
echo
rm -rf "$WORK"
echo "== Tesseract pronto in $OUT ($(du -sh "$OUT" | cut -f1))"
