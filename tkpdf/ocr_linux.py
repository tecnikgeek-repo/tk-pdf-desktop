"""Riconoscimento del testo (OCR) su Linux con Tesseract INCLUSO nel pacchetto: niente da installare nel sistema.

Copia IDENTICA in tk-pdf e tk-listino (originale: tk-pdf-desktop, ramo linux). Niente Qt e niente import del
programma: lavora su file immagine. La cartella «tesseract» (bin/tesseract, lib/ con le librerie prese dai pacchetti
Ubuntu, tessdata/ con ita+eng, licenze/) la prepara linux/prepara_tesseract.sh e build_linux.sh la mette accanto
all'eseguibile dentro l'AppImage. Tesseract gira con un ambiente costruito apposta (le sue librerie e i suoi dati),
mai con quello del programma. Uscita TSV: ogni parola con il suo riquadro (servono per le colonne dei listini).
"""
import os
import subprocess
import sys
import tempfile

LINGUE = "ita+eng"
DPI = 300  # le immagini arrivano già ingrandite (lato lungo >= 1800 px): evita l'avviso «risoluzione 0 dpi»


def cartella():
    """Cartella di Tesseract: TK_TESSERACT_DIR, poi «tesseract» accanto all'eseguibile del pacchetto,
    poi build/tesseract nel repo (sviluppo, dopo linux/prepara_tesseract.sh)."""
    env = os.environ.get("TK_TESSERACT_DIR")
    if env:
        return env
    if getattr(sys, "frozen", False):
        return os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "tesseract")
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "build", "tesseract")


def _eseguibile():
    return os.path.join(cartella(), "bin", "tesseract")


def _tessdata():
    return os.path.join(cartella(), "tessdata")


def disponibile():
    exe = _eseguibile()
    return (os.path.isfile(exe) and os.access(exe, os.X_OK)
            and all(os.path.isfile(os.path.join(_tessdata(), f"{l}.traineddata")) for l in LINGUE.split("+")))


def _ambiente():
    """Solo ciò che serve a Tesseract: le sue librerie, i suoi dati, locale C (Tesseract 4 la pretende)."""
    cpu = os.cpu_count() or 2
    return {
        "PATH": "/usr/bin:/bin",
        "HOME": os.environ.get("HOME") or tempfile.gettempdir(),
        "LC_ALL": "C",
        "LD_LIBRARY_PATH": os.path.join(cartella(), "lib"),
        "TESSDATA_PREFIX": _tessdata(),
        "OMP_THREAD_LIMIT": str(max(1, min(4, cpu // 2))),  # al massimo metà dei processori
    }


def _esegui(args, timeout):
    try:
        return subprocess.run([_eseguibile()] + args, env=_ambiente(), stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, cwd=cartella())
    except FileNotFoundError as exc:
        raise RuntimeError("Riconoscimento del testo non disponibile: manca Tesseract nel pacchetto") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Riconoscimento del testo troppo lento: interrotto") from exc


def versione():
    """Prima riga di «tesseract --version» (per il selftest), oppure ""."""
    try:
        r = _esegui(["--version"], 30)
    except RuntimeError:
        return ""
    testo = (r.stdout or r.stderr or b"").decode("utf-8", "replace").strip()
    return testo.splitlines()[0] if testo else ""


def leggi_tsv(testo):
    """TSV di Tesseract → righe di parole [[(testo, x, y, w, h), ...], ...] nell'ordine di lettura."""
    righe = {}
    for riga in testo.splitlines()[1:]:
        campi = riga.split("\t")
        if len(campi) < 12 or campi[0] != "5":
            continue
        parola = campi[11].strip()
        try:
            conf = float(campi[10])
            x, y, w, h = (int(float(v)) for v in campi[6:10])
        except ValueError:
            continue
        if not parola or conf < 0:
            continue
        chiave = tuple(campi[1:5])  # pagina, blocco, paragrafo, riga
        righe.setdefault(chiave, []).append((parola, float(x), float(y), float(w), float(h)))
    return list(righe.values())


def riconosci_file(percorso, psm=3):
    """Parole con i riquadri (pixel dell'immagine) di un file PNG/JPEG/TIFF."""
    r = _esegui([percorso, "stdout", "--tessdata-dir", _tessdata(), "-l", LINGUE, "--psm", str(psm),
                 "--dpi", str(DPI), "-c", "tessedit_create_txt=0", "-c", "tessedit_create_tsv=1"], 180)
    if r.returncode != 0:
        err = (r.stderr or b"").decode("utf-8", "replace").strip()
        raise RuntimeError(f"Riconoscimento del testo non riuscito:\n{err[-600:]}")
    return leggi_tsv(r.stdout.decode("utf-8", "replace"))


def riconosci(immagini, psm=3):
    """Per ogni immagine (percorso o oggetto con .save(percorso, "PNG"), es. QImage) le righe di parole."""
    lavoro = tempfile.mkdtemp(prefix="tk-ocr-")
    try:
        pagine = []
        for i, im in enumerate(immagini):
            if isinstance(im, str):
                percorso = im
            else:
                percorso = os.path.join(lavoro, f"p{i}.png")
                if not im.save(percorso, "PNG"):
                    raise RuntimeError("Impossibile preparare l'immagine per il riconoscimento del testo")
            pagine.append(riconosci_file(percorso, psm))
        return pagine
    finally:
        for nome in os.listdir(lavoro):
            try:
                os.remove(os.path.join(lavoro, nome))
            except OSError:
                pass
        try:
            os.rmdir(lavoro)
        except OSError:
            pass
