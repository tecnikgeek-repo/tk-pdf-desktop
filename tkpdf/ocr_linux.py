"""Riconoscimento del testo (OCR) su Linux con Tesseract INCLUSO nel pacchetto: niente da installare nel sistema.

Copia IDENTICA in tk-pdf e tk-listino (originale in Dropbox\\CLAUDE\\tk-software\\librerie, con
prepara_tesseract.sh che va in linux/). Niente Qt e niente import del
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
    """TSV di Tesseract → righe di parole [[(testo, x, y, w, h), ...], ...] nell'ordine di lettura.
    Ogni parola prende l'altezza della sua riga (come gli OCR di Windows e del Mac): il riquadro stretto di
    Tesseract farebbe sembrare «e» o «a» più piccole di «Listino» nella stessa riga."""
    righe, linee = {}, {}
    for riga in testo.splitlines()[1:]:
        campi = riga.split("\t")
        if len(campi) < 12 or campi[0] not in ("4", "5"):
            continue
        try:
            x, y, w, h = (int(float(v)) for v in campi[6:10])
            conf = float(campi[10])
        except ValueError:
            continue
        chiave = tuple(campi[1:5])  # pagina, blocco, paragrafo, riga
        if campi[0] == "4":
            linee[chiave] = (y, h)
            continue
        parola = campi[11].strip()
        if not parola or conf < 0:
            continue
        ly, lh = linee.get(chiave, (y, h))
        righe.setdefault(chiave, []).append((parola, float(x), float(ly), float(w), float(lh)))
    return list(righe.values())


def riconosci_file(percorso, psm=3):
    """Parole con i riquadri (pixel dell'immagine) di un file PNG/JPEG/TIFF."""
    r = _esegui([percorso, "stdout", "--tessdata-dir", _tessdata(), "-l", LINGUE, "--psm", str(psm),
                 "--dpi", str(DPI), "-c", "tessedit_create_txt=0", "-c", "tessedit_create_tsv=1"], 180)
    if r.returncode != 0:
        err = (r.stderr or b"").decode("utf-8", "replace").strip()
        raise RuntimeError(f"Riconoscimento del testo non riuscito:\n{err[-600:]}")
    return leggi_tsv(r.stdout.decode("utf-8", "replace"))


def _soglia(lo, hi):
    return bytes(255 if d <= lo else 0 if d >= hi else round(255 * (hi - d) / (hi - lo)) for d in range(256))


def normalizza(img, raggio=8, lo=5, hi=14):
    """QImage → testo nero su bianco qualunque sia lo sfondo (fasce colorate, ombre, scritte chiare su fondo scuro).
    Tesseract 4 usa una soglia unica per tutta la pagina: il testo scuro su una fascia grigia sparirebbe.
    Sfondo locale = chiusura (massimo poi minimo nei dintorni, che toglie i tratti sottili e lascia i bordi delle
    fasce al loro posto); poi |log(sfondo) - log(pixel)|, cioè di quanto ogni pixel si stacca dal suo sfondo.
    Solo operazioni di Qt sull'immagine intera: pochi centesimi di secondo per pagina."""
    import math

    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QImage, QPainter

    def traduci(im, tabella):
        g = im.convertToFormat(QImage.Format.Format_Grayscale8)
        w, h, bpl = g.width(), g.height(), g.bytesPerLine()
        dati = bytes(g.constBits())[: bpl * h].translate(tabella)
        return QImage(dati, w, h, bpl, QImage.Format.Format_Grayscale8).copy().convertToFormat(QImage.Format.Format_RGB32)

    log = bytes(round(255 * math.log1p(v) / math.log(256)) for v in range(256))
    grigio = img.convertToFormat(QImage.Format.Format_Grayscale8).convertToFormat(QImage.Format.Format_RGB32)
    sfondo = grigio.copy()
    p = QPainter(sfondo)
    # quadrato di lato 2*(2*raggio-1)+1, prima in orizzontale e poi in verticale: gli angoli delle fasce restano netti
    for modo in (QPainter.CompositionMode.CompositionMode_Lighten, QPainter.CompositionMode.CompositionMode_Darken):
        p.setCompositionMode(modo)
        for asse in ((1, 0), (0, 1)):
            r = 1
            while r <= raggio:
                copia = sfondo.copy()
                for s in (r, -r):
                    p.drawImage(QPoint(s * asse[0], s * asse[1]), copia)
                r *= 2
    p.end()
    diff = traduci(sfondo, log)
    p = QPainter(diff)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Difference)
    p.drawImage(0, 0, traduci(grigio, log))
    p.end()
    return traduci(diff, _soglia(lo, hi))


def riconosci(immagini, psm=3, pulisci=True):
    """Per ogni immagine (percorso o QImage) le righe di parole. pulisci: prima normalizza lo sfondo (vedi sopra)."""
    lavoro = tempfile.mkdtemp(prefix="tk-ocr-")
    try:
        pagine = []
        for i, im in enumerate(immagini):
            if pulisci:
                try:
                    from PySide6.QtGui import QImage
                    im = normalizza(QImage(im) if isinstance(im, str) else im)
                except ImportError:
                    pass
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
