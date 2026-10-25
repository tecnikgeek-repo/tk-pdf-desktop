"""Funzioni di supporto: percorsi, colori, font, conversioni coordinate."""
import os
import sys

import pymupdf as fitz
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage


# ------------------------------------------------------------------ percorsi
IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform == "win32"


def app_data_dir():
    if IS_MAC:
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    path = os.path.join(base, "tk-pdf")
    os.makedirs(path, exist_ok=True)
    return path


def signatures_dir():
    path = os.path.join(app_data_dir(), "firme")
    os.makedirs(path, exist_ok=True)
    return path


def resource_path(rel):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, rel)


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}".replace(".", ",")
        n /= 1024.0


# ------------------------------------------------------------------ colori
def qcolor_to_rgb(c: QColor):
    return (c.redF(), c.greenF(), c.blueF())


def rgb_to_qcolor(rgb):
    if not rgb:
        return QColor(0, 0, 0)
    if len(rgb) == 1:
        v = int(rgb[0] * 255)
        return QColor(v, v, v)
    if len(rgb) == 4:  # CMYK
        c, m, y, k = rgb
        return QColor(int(255 * (1 - c) * (1 - k)), int(255 * (1 - m) * (1 - k)), int(255 * (1 - y) * (1 - k)))
    return QColor(int(rgb[0] * 255), int(rgb[1] * 255), int(rgb[2] * 255))


def int_to_rgb(value):
    return (((value >> 16) & 255) / 255.0, ((value >> 8) & 255) / 255.0, (value & 255) / 255.0)


# ------------------------------------------------------------------ immagini
def pix_to_qimage(pix):
    fmt = QImage.Format.Format_RGBA8888 if pix.alpha else QImage.Format.Format_RGB888
    return QImage(pix.samples, pix.width, pix.height, pix.stride, fmt).copy()


def qimage_to_png_bytes(img: QImage):
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    return bytes(ba)


# ------------------------------------------------------------------ coordinate
# Le API di PyMuPDF lavorano sulla pagina NON ruotata; la vista mostra la pagina
# ruotata (page.rect). rotation_matrix: non ruotata -> vista.
def to_unrot_point(page, x, y):
    return fitz.Point(x, y) * page.derotation_matrix


def to_unrot_rect(page, rect):
    return (fitz.Rect(rect) * page.derotation_matrix).normalize()


def to_view_rect(page, rect):
    return (fitz.Rect(rect) * page.rotation_matrix).normalize()


def frect_to_qrect(r):
    return QRectF(r.x0, r.y0, r.width, r.height)


# ------------------------------------------------------------------ font
if IS_MAC:
    FONT_DIRS = ["/System/Library/Fonts/Supplemental", "/Library/Fonts", os.path.expanduser("~/Library/Fonts")]
    FAMILY_FILES = {
        "sans": ("Arial.ttf", "Arial Bold.ttf", "Arial Italic.ttf", "Arial Bold Italic.ttf"),
        "serif": ("Times New Roman.ttf", "Times New Roman Bold.ttf", "Times New Roman Italic.ttf",
                  "Times New Roman Bold Italic.ttf"),
        "mono": ("Courier New.ttf", "Courier New Bold.ttf", "Courier New Italic.ttf", "Courier New Bold Italic.ttf"),
    }
else:
    FONT_DIRS = [os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")]
    FAMILY_FILES = {
        "sans": ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"),
        "serif": ("times.ttf", "timesbd.ttf", "timesi.ttf", "timesbi.ttf"),
        "mono": ("cour.ttf", "courbd.ttf", "couri.ttf", "courbi.ttf"),
    }
FAMILY_BASE14 = {
    "sans": ("helv", "hebo", "heit", "hebi"),
    "serif": ("tiro", "tibo", "tiit", "tibi"),
    "mono": ("cour", "cobo", "coit", "cobi"),
}
FAMILY_LABELS = {"sans": "Sans (Arial)", "serif": "Serif (Times)", "mono": "Monospace (Courier)"}


def font_for(family, bold, italic):
    """Ritorna (fontname, fontfile) per insert_text: TTF di sistema se c'è, altrimenti Base-14."""
    idx = (1 if bold else 0) + (2 if italic else 0)
    family = family if family in FAMILY_FILES else "sans"
    path = next((os.path.join(d, FAMILY_FILES[family][idx]) for d in FONT_DIRS
                 if os.path.exists(os.path.join(d, FAMILY_FILES[family][idx]))), "")
    if path:
        return f"tk{family}{idx}", path
    return FAMILY_BASE14[family][idx], None


def guess_family(fontname, flags):
    name = (fontname or "").lower()
    if flags & 8 or any(k in name for k in ("courier", "mono", "consol")):
        return "mono"
    if "sans" not in name and (flags & 4 or any(k in name for k in ("times", "serif", "georgia", "garamond", "roman", "cambria", "book"))):
        return "serif"
    return "sans"


def guess_bold_italic(fontname, flags):
    name = (fontname or "").lower()
    bold = bool(flags & 16) or any(k in name for k in ("bold", "black", "heavy", "semibold", "demi"))
    italic = bool(flags & 2) or "italic" in name or "oblique" in name
    return bold, italic


_STYLE_NEUTRAL = ("", "regular", "roman", "book", "normal", "mt", "psmt", "regularmt")


def _font_key(name):
    import re
    return re.sub(r"[^a-z0-9]", "", (name or "").split("+", 1)[-1].lower())


def find_original_font(doc, page, span_font):
    """Cerca il font incorporato usato dallo span; ritorna (fitz.Font, buffer) o None.

    I nomi non coincidono sempre (es. span «Georgia» ↔ font «ABCDEF+Georgia Regular»): si confrontano
    senza prefisso di sottoinsieme, spazi e trattini, accettando suffissi neutri come Regular/MT."""
    target = _font_key(span_font)
    best, best_score = None, None
    try:
        for entry in page.get_fonts(full=True):
            xref, ext, basefont, name = entry[0], entry[1], entry[3], entry[4]
            for candidate in (basefont, name):
                key = _font_key(candidate)
                if not key or not target:
                    continue
                if key == target:
                    score = 0
                elif key.startswith(target) and key[len(target):] in _STYLE_NEUTRAL:
                    score = 1
                elif target.startswith(key) and target[len(key):] in _STYLE_NEUTRAL:
                    score = 1
                else:
                    continue
                if ext not in ("n/a", "", None) and (best_score is None or score < best_score):
                    best, best_score = xref, score
        if best is None:
            return None
        _, _, _, buf = doc.extract_font(best)
        if not buf:
            return None
        return fitz.Font(fontbuffer=buf), buf
    except Exception:
        return None


_TOUNICODE_FIX = {"00a0": "0020", "00ad": "002D"}


def fix_tounicode(doc, page, fontname):
    """I TTF condividono il glifo di spazio/trattino con NBSP/soft-hyphen: MuPDF mappa il glifo
    sul carattere sbagliato e copia/ricerca restituiscono spazi 'strani'. Corregge la ToUnicode."""
    import re
    try:
        for entry in page.get_fonts(full=True):
            if entry[4] != fontname:
                continue
            kind, value = doc.xref_get_key(entry[0], "ToUnicode")
            if kind != "xref":
                continue
            xref = int(value.split()[0])
            data = doc.xref_stream(xref).decode("latin-1")
            out = []
            for line in data.split("\n"):
                tokens = re.findall(r"<([0-9a-fA-F]+)>", line)
                single = (len(tokens) == 2) or (len(tokens) == 3 and tokens[0].lower() == tokens[1].lower())
                if single and tokens[-1].lower() in _TOUNICODE_FIX:
                    head = line[:line.rfind("<")]
                    line = f"{head}<{_TOUNICODE_FIX[tokens[-1].lower()]}>"
                out.append(line)
            new = "\n".join(out)
            if new != data:
                doc.update_stream(xref, new.encode("latin-1"))
    except Exception:
        pass


def font_renders_text(fontbuffer, text, size=40):
    """Scrive ogni lettera con il font su una pagina di prova e controlla che lasci davvero un segno.

    I font incorporati sono ridotti: la tabella può dichiarare una lettera il cui disegno è stato tolto
    (spazio riservato ma lettera invisibile) oppure mancare del tutto (font CID)."""
    chars = sorted({ch for ch in text if not ch.isspace()})
    if not chars:
        return True
    cell = 60
    try:
        font = fitz.Font(fontbuffer=fontbuffer)
        # lettera assente dalla tabella: verrebbe disegnata come quadratino (che lascia comunque un segno)
        if not all(font.has_glyph(ord(ch)) for ch in chars):
            return False
        doc = fitz.open()
        page = doc.new_page(width=cell * len(chars) + 20, height=80)
        page.insert_font(fontname="tkcheck", fontbuffer=fontbuffer)
        for i, ch in enumerate(chars):
            page.insert_text((10 + cell * i, 58), ch, fontname="tkcheck", fontsize=size)
        pix = page.get_pixmap(colorspace=fitz.csGRAY, alpha=False)
        samples, width, height = pix.samples, pix.width, pix.height
        for i in range(len(chars)):
            x0, x1 = 10 + cell * i - 4, min(width, 10 + cell * i + cell - 4)
            if not any(samples[y * width + x] < 140 for y in range(height) for x in range(max(0, x0), x1)):
                return False
        return True
    except Exception:
        return False


def font_has_text(font, text):
    try:
        return all(font.has_glyph(ord(ch)) for ch in text if not ch.isspace())
    except Exception:
        return False
