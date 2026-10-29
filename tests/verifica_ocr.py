"""Controlla il risultato dell'OCR su tests/ocr-it.png: parole italiane con gli accenti, prezzi con l'euro e posizioni.
Uso: python3 tests/verifica_ocr.py <file scritto da --ocr-test>   (oppure senza argomenti: OCR Linux diretto)
Il file ha le righe di testo, poi una riga «---» e una parola per riga: testo<TAB>x<TAB>y<TAB>w<TAB>h (pixel)."""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# parole che devono uscire esatte (accenti e prezzi) e dove: tolleranza in pixel sul bordo sinistro e sul centro
DA_TROVARE = ["Caffè", "espresso", "Cornetto", "12,50", "1,20", "3,00", "€", "Perché", "già", "così", "Più",
              "qualità!", "Partenope"]
TOLLERANZA = 22


def leggi(percorso):
    with open(percorso, encoding="utf-8") as fh:
        testo = fh.read()
    righe, _, parole = testo.partition("\n---\n")
    out = []
    for r in parole.splitlines():
        c = r.split("\t")
        if len(c) == 5:
            out.append((c[0], float(c[1]), float(c[2]), float(c[3]), float(c[4])))
    return righe, out


def ocr_diretto():
    sys.path.insert(0, os.path.dirname(HERE))
    import glob
    pkg = [os.path.basename(os.path.dirname(p)) for p in glob.glob(os.path.join(os.path.dirname(HERE), "*", "ocr_linux.py"))][0]
    ocr_linux = __import__(pkg + ".ocr_linux", fromlist=["x"])
    from PySide6.QtGui import QGuiApplication
    _app = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841 (normalizzazione dello sfondo con Qt)
    righe = ocr_linux.riconosci([os.path.join(HERE, "ocr-it.png")])[0]
    return "\n".join(" ".join(w[0] for w in r) for r in righe), [w for r in righe for w in r]


def main():
    testo, parole = leggi(sys.argv[1]) if len(sys.argv) > 1 else ocr_diretto()
    with open(os.path.join(HERE, "ocr-it.json"), encoding="utf-8") as fh:
        attese = json.load(fh)["parole"]
    print(testo)
    errori = []
    for nome in DA_TROVARE:
        attesa = next(a for a in attese if a["testo"] == nome)
        trovate = [p for p in parole if p[0] == nome]
        if not trovate:
            errori.append(f"manca «{nome}»")
            continue
        ok = [p for p in trovate if abs(p[1] - attesa["x"]) <= TOLLERANZA
              and abs((p[2] + p[4] / 2) - (attesa["y"] + attesa["h"] / 2)) <= TOLLERANZA]
        if not ok:
            p = trovate[0]
            errori.append(f"«{nome}» fuori posto: x={p[1]:.0f} y={p[2]:.0f} (attesa x={attesa['x']} y={attesa['y']})")
    if errori:
        print("OCR NON CORRETTO:\n  " + "\n  ".join(errori))
        sys.exit(1)
    print(f"OCR OK: {len(DA_TROVARE)} parole controllate (testo e posizione), {len(parole)} riconosciute")


if __name__ == "__main__":
    main()
