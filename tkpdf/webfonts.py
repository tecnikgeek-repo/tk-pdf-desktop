"""Font da Google Fonts: quando il font incorporato nel PDF è incompleto si scarica quello completo.

Molti PDF (soprattutto quelli generati da siti web) usano font di Google Fonts, liberi e scaricabili
senza chiave. Il file TTF viene salvato in cache nella cartella dati dell'app.
Si scarica solo col consenso dell'utente (chiesto la prima volta, ricordato, modificabile in Informazioni):
Google riceve l'indirizzo IP e il nome del font. Senza consenso si usano i font del computer.
"""
import os
import re
import urllib.error

from tkpdf.util import app_data_dir

CONSENT_KEY = "webfonts/consenso"   # "si" / "no"; assente = non ancora chiesto
CONSENT_TEXT = ("Per riscrivere questo testo con lo stesso carattere del PDF, tk-pdf può scaricare il font "
                "gratuito da Google Fonts (fonts.googleapis.com). Google riceve l'indirizzo IP del computer e "
                "il nome del font, nient'altro. Senza il download si usa un font simile del computer.")


def _settings():
    from PySide6.QtCore import QSettings
    return QSettings("TecnikGeek", "tk-pdf")


def consent():
    """True/False = scelta dell'utente, None = non ancora chiesto."""
    v = _settings().value(CONSENT_KEY, "", type=str)
    return {"si": True, "no": False}.get(v)


def set_consent(on):
    _settings().setValue(CONSENT_KEY, "si" if on else "no")


def ask_consent(parent=None):
    """Chiede la prima volta se scaricare i font da Google Fonts; poi risponde con la scelta ricordata."""
    v = consent()
    if v is not None:
        return v
    from PySide6.QtWidgets import QMessageBox
    box = QMessageBox(parent)
    box.setWindowTitle("tk-pdf")
    box.setIcon(QMessageBox.Icon.Question)
    box.setText("Scaricare il font da Google Fonts?")
    box.setInformativeText(CONSENT_TEXT + "\n\nLa scelta viene ricordata: puoi cambiarla in ☰ → Informazioni.")
    yes = box.addButton("Sì, scarica", QMessageBox.ButtonRole.AcceptRole)
    box.addButton("No, usa i font del computer", QMessageBox.ButtonRole.RejectRole)
    box.exec()
    on = box.clickedButton() is yes
    set_consent(on)
    return on

CSS_URL = "https://fonts.googleapis.com/css2?family={family}:ital,wght@{ital},{weight}"
# suffissi di stile più lunghi prima (extrabold prima di bold)
WEIGHT_WORDS = [
    ("extralight", 200), ("ultralight", 200), ("extrabold", 800), ("ultrabold", 800), ("semibold", 600),
    ("demibold", 600), ("hairline", 100), ("regular", 400), ("medium", 500), ("normal", 400), ("light", 300),
    ("heavy", 900), ("black", 900), ("thin", 100), ("bold", 700), ("book", 400), ("roman", 400),
]
_failed = set()  # famiglie/pesi non trovati in questa sessione (niente richieste ripetute)


def parse_font_name(name, flags=0):
    """«ABCDEF+OpenSans-SemiBoldItalic» → (["OpenSans", "Open Sans"], 600, True)."""
    base = (name or "").split("+", 1)[-1].strip()
    if "-" in base:
        family, style = base.split("-", 1)
    elif "," in base:
        family, style = base.split(",", 1)
    else:
        words = base.split()
        style_words = []
        while len(words) > 1 and any(w.lower().startswith(k) or w.lower() in ("italic", "oblique")
                                     for k, _ in WEIGHT_WORDS for w in [words[-1]]):
            style_words.insert(0, words.pop())
        family, style = " ".join(words), " ".join(style_words)
    style_key = re.sub(r"[^a-z]", "", style.lower())
    italic = "italic" in style_key or "oblique" in style_key or bool(flags & 2)
    weight = next((w for k, w in WEIGHT_WORDS if k in style_key), 700 if flags & 16 else 400)
    raw = family.strip()
    stripped = re.sub(r"(MT|PS|Std|Pro)$", "", raw).strip() or raw

    def spaced(text):
        return re.sub(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Za-z])(?=[0-9])", " ", text)

    candidates = []
    for c in (spaced(raw), spaced(stripped), raw, stripped):
        if c and c not in candidates:
            candidates.append(c)
    return candidates, weight, italic


def _same_family(data, family):
    """Google a volte risponde con un altro font: si accetta solo se il nome interno corrisponde."""
    try:
        import pymupdf as fitz
        inner = re.sub(r"[^a-z0-9]", "", fitz.Font(fontbuffer=data).name.lower())
        wanted = re.sub(r"[^a-z0-9]", "", family.lower())
        return bool(wanted) and wanted in inner
    except Exception:
        return False


def _cache_path(family, weight, italic):
    folder = os.path.join(app_data_dir(), "fonts")
    os.makedirs(folder, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9]", "", family)
    return os.path.join(folder, f"{safe}-{weight}{'i' if italic else ''}.ttf")


def _download(family, weight, italic):
    from tkpdf.updater import _open  # stessa connessione HTTPS (certifi) degli aggiornamenti
    url = CSS_URL.format(family=family.replace(" ", "+"), ital=1 if italic else 0, weight=weight)
    with _open(url, 8) as resp:
        css = resp.read().decode("utf-8", "replace")
    match = re.search(r"url\((https://[^)]+)\)\s*format\('truetype'\)", css)
    if not match:
        return None
    with _open(match.group(1), 15) as resp:
        return resp.read()


def fetch(font_name, flags=0, download=True):
    """Percorso del TTF completo da Google Fonts per quel font, oppure None se non esiste o manca la rete.
    download=False: solo i font già in cache (nessuna rete)."""
    candidates, weight, italic = parse_font_name(font_name, flags)
    tries = [(weight, italic)]
    if weight != 400:
        tries.append((400 if weight < 600 else 700, italic))  # peso non disponibile: il più vicino comune
    if italic:
        tries.append((weight, False))
    for family in candidates:
        for w, it in tries:
            path = _cache_path(family, w, it)
            if os.path.exists(path) and os.path.getsize(path) > 1000:
                return path
            key = (family.lower(), w, it)
            if not download or key in _failed:
                continue
            try:
                data = _download(family, w, it)
            except urllib.error.HTTPError:
                data = None  # 400 = famiglia o peso non presenti su Google Fonts
            except Exception:
                return None  # rete assente o lenta: nessun altro tentativo
            if data and _same_family(data, family):
                with open(path, "wb") as fh:
                    fh.write(data)
                return path
            _failed.add(key)
    return None
