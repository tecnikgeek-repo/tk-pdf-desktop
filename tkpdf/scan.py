"""Da foto a PDF: ritaglio del foglio, raddrizzamento prospettico e filtri «scanner».

Solo Qt (niente OpenCV/numpy): il rilevamento dei bordi lavora su una copia ridotta della foto,
raddrizzamento e filtri usano QTransform/QPainter (codice C di Qt, veloce anche su foto da 12 MP)."""
import math
import os

import pymupdf as fitz
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor, QIcon, QImage, QImageReader, QPainter, QPainterPath, QPen, QPixmap, QPolygonF, QTransform,
)
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QMessageBox, QProgressDialog, QPushButton, QRadioButton, QSizePolicy,
    QVBoxLayout, QWidget,
)

from tkpdf import APP_TITLE

PHOTO_EXT = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".heic", ".heif")
PHOTO_FILTER = "Foto (*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff *.heic *.heif);;Tutti i file (*.*)"
MAX_SOURCE = 4200      # lato lungo massimo della foto caricata
PREVIEW_SIDE = 1400    # lato lungo della copia usata a schermo

FILTERS = [
    ("document", "📄 Documento", "Sfondo bianco e testo nitido, colori mantenuti"),
    ("gray", "🌓 Scala di grigi", "Come Documento, senza colori"),
    ("bw", "⬛ Bianco e nero", "Solo testo: file leggerissimo"),
    ("original", "🖼️ Foto originale", "Nessuna correzione"),
]
QUALITIES = [("Alta (300 dpi)", 3508, 88), ("Normale (200 dpi)", 2339, 80), ("Leggera (150 dpi)", 1754, 70)]
A4 = (595.0, 842.0)
THUMB_W, THUMB_H = 104, 136


# ====================================================================== immagini
def load_photo(path):
    """Legge la foto rispettando l'orientamento EXIF e riducendo le foto enormi."""
    reader = QImageReader(path)
    reader.setAutoTransform(True)
    size = reader.size()
    if size.isValid() and max(size.width(), size.height()) > MAX_SOURCE:
        reader.setScaledSize(size.scaled(MAX_SOURCE, MAX_SOURCE, Qt.AspectRatioMode.KeepAspectRatio))
    img = reader.read()
    if img.isNull():
        return None
    return img.convertToFormat(QImage.Format.Format_RGB32)


def fit_side(img, side):
    if max(img.width(), img.height()) <= side:
        return img
    return img.scaled(side, side, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)


def full_corners():
    return [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]


def order_corners(pts):
    """Ordina 4 punti come alto-sx, alto-dx, basso-dx, basso-sx."""
    cx = sum(p[0] for p in pts) / 4
    cy = sum(p[1] for p in pts) / 4
    pts = sorted(pts, key=lambda p: math.atan2(p[1] - cy, p[0] - cx))  # senso orario (y verso il basso)
    start = min(range(4), key=lambda i: pts[i][0] + pts[i][1])
    return pts[start:] + pts[:start]


def _gray_rows(img):
    g = img.convertToFormat(QImage.Format.Format_Grayscale8)
    w, h, bpl = g.width(), g.height(), g.bytesPerLine()
    data = bytes(g.constBits())
    return w, h, [data[y * bpl:y * bpl + w] for y in range(h)]


def detect_corners(img):
    """Cerca il foglio (zona chiara più grande) e ne ritorna i 4 angoli normalizzati 0..1, oppure None."""
    small = fit_side(img, 220)
    w, h, rows = _gray_rows(small)
    hist = [0] * 256
    for r in rows:
        for v in r:
            hist[v] += 1
    total = w * h
    # soglia di Otsu
    sum_all = sum(i * c for i, c in enumerate(hist))
    best_t, best_var, w_b, sum_b = 128, -1.0, 0, 0
    for t in range(256):
        w_b += hist[t]
        if w_b == 0 or w_b == total:
            continue
        sum_b += t * hist[t]
        m_b = sum_b / w_b
        m_f = (sum_all - sum_b) / (total - w_b)
        var = w_b * (total - w_b) * (m_b - m_f) ** 2
        if var > best_var:
            best_var, best_t = var, t
    # media locale: un angolo del foglio in ombra resta più chiaro del tavolo che ha intorno
    blur = small.scaled(max(2, w // 8), max(2, h // 8), Qt.AspectRatioMode.IgnoreAspectRatio,
                        Qt.TransformationMode.SmoothTransformation)
    blur = blur.scaled(w, h, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    _, _, means = _gray_rows(blur)
    low = best_t * 0.35
    mask = bytearray(total)
    for y, r in enumerate(rows):
        base, mr = y * w, means[y]
        for x, v in enumerate(r):
            if v > best_t or (v > low and v > mr[x] * 1.25):
                mask[base + x] = 1
    # componente connessa più grande
    seen = bytearray(total)
    best = []
    for start in range(total):
        if not mask[start] or seen[start]:
            continue
        seen[start] = 1
        stack, comp = [start], []
        while stack:
            i = stack.pop()
            comp.append(i)
            x, y = i % w, i // w
            for j in ((i - 1) if x > 0 else -1, (i + 1) if x < w - 1 else -1,
                      (i - w) if y > 0 else -1, (i + w) if y < h - 1 else -1):
                if j >= 0 and mask[j] and not seen[j]:
                    seen[j] = 1
                    stack.append(j)
        if len(comp) > len(best):
            best = comp
    if len(best) < total * 0.12:
        return None
    # angoli = punti estremi lungo le diagonali
    tl = min(best, key=lambda i: i % w + i // w)
    br = max(best, key=lambda i: i % w + i // w)
    tr = max(best, key=lambda i: i % w - i // w)
    bl = min(best, key=lambda i: i % w - i // w)
    pts = [((i % w + 0.5) / w, (i // w + 0.5) / h) for i in (tl, tr, br, bl)]
    # un pixel verso l'interno: niente filo di tavolo sui bordi
    cx, cy = sum(p[0] for p in pts) / 4, sum(p[1] for p in pts) / 4
    pts = [(x + (1.2 / w if x < cx else -1.2 / w), y + (1.2 / h if y < cy else -1.2 / h)) for x, y in pts]
    pts = [(min(1.0, max(0.0, x)), min(1.0, max(0.0, y))) for x, y in pts]
    if quad_area(pts) < 0.12:
        return None
    return order_corners(pts)


def paper_fraction(img):
    """Quota di pixel chiari e poco colorati (carta). Loghi, screenshot e foto normali ne hanno poca."""
    small = fit_side(img, 96).convertToFormat(QImage.Format.Format_RGB32)
    w, h, bpl = small.width(), small.height(), small.bytesPerLine()
    data = bytes(small.constBits())
    paper = 0
    for y in range(h):
        row = data[y * bpl:y * bpl + w * 4]
        for x in range(0, w * 4, 4):
            b, g, r = row[x], row[x + 1], row[x + 2]
            hi, lo = max(r, g, b), min(r, g, b)
            if hi > 110 and hi - lo < 45:
                paper += 1
    return paper / max(1, w * h)


def auto_setup(preview):
    """(angoli, è_documento): se non c'è un foglio chiaro si usa la foto intera senza filtri."""
    corners = detect_corners(preview)
    on_edge = corners and sum(1 for x, y in corners if min(x, y, 1 - x, 1 - y) < 0.012)
    if corners is None or on_edge >= 2:
        # nessun foglio, oppure zona chiara tagliata dal bordo (es. screenshot): foto intera
        return full_corners(), paper_fraction(preview) >= 0.55
    if paper_fraction(warp(preview, corners, 400)) < 0.55:
        return full_corners(), False
    return corners, True


def quad_area(pts):
    s = 0.0
    for i in range(4):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % 4]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def warp(img, corners, max_side=None):
    """Raddrizza il quadrilatero (angoli normalizzati) in un rettangolo."""
    W, H = img.width(), img.height()
    pts = [(x * W, y * H) for x, y in corners]
    out_w = max(_dist(pts[0], pts[1]), _dist(pts[3], pts[2]))
    out_h = max(_dist(pts[0], pts[3]), _dist(pts[1], pts[2]))
    if max_side and max(out_w, out_h) > max_side:
        k = max_side / max(out_w, out_h)
        out_w, out_h = out_w * k, out_h * k
    out_w, out_h = max(8, round(out_w)), max(8, round(out_h))
    if corners == full_corners() and (out_w, out_h) == (W, H):
        return img.copy()
    src = QPolygonF([QPointF(x, y) for x, y in pts])
    dst = QPolygonF([QPointF(0, 0), QPointF(out_w, 0), QPointF(out_w, out_h), QPointF(0, out_h)])
    tr = QTransform()
    if not QTransform.quadToQuad(src, dst, tr):
        return img.copy()
    out = QImage(out_w, out_h, QImage.Format.Format_RGB32)
    out.fill(QColor("white"))
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    p.setTransform(tr)
    p.drawImage(0, 0, img)
    p.end()
    return out


def _fill_mode(img, mode, gray):
    p = QPainter(img)
    p.setCompositionMode(mode)
    p.fillRect(img.rect(), QColor(gray, gray, gray))
    p.end()


def enhance(img):
    """Toglie ombre e sfondo grigio (divisione per l'illuminazione stimata) e rinforza il testo."""
    out = img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    # illuminazione: copia minuscola + dilatazione (massimo locale) per cancellare il testo
    small = out.scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    for _ in range(3):
        src = small.copy()
        p = QPainter(small)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Lighten)
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            p.drawImage(dx, dy, src)
        p.end()
    bg = small.scaled(out.size(), Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    bg.invertPixels()
    # colore / (sfondo): Color Dodge con lo sfondo invertito
    p = QPainter(out)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_ColorDodge)
    p.drawImage(0, 0, bg)
    p.end()
    # livelli: il grigio chiaro diventa bianco, il testo più scuro
    _fill_mode(out, QPainter.CompositionMode.CompositionMode_ColorDodge, 22)
    _fill_mode(out, QPainter.CompositionMode.CompositionMode_ColorBurn, 205)
    return out.convertToFormat(QImage.Format.Format_RGB32)


def apply_filter(img, name):
    if name == "original":
        return img
    out = enhance(img)
    if name == "gray":
        return out.convertToFormat(QImage.Format.Format_Grayscale8)
    if name == "bw":
        g = out.convertToFormat(QImage.Format.Format_Grayscale8)
        _fill_mode(g, QPainter.CompositionMode.CompositionMode_ColorBurn, 150)
        return g.convertToFormat(QImage.Format.Format_Mono, Qt.ImageConversionFlag.ThresholdDither)
    return out


def process(img, corners, filter_name, max_side=None):
    return apply_filter(warp(img, corners, max_side), filter_name)


def encode(img, filter_name, quality):
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    if filter_name == "bw":
        img.save(buf, "PNG")
    else:
        img.save(buf, "JPG", quality)
    buf.close()
    return bytes(ba)


def _median(values):
    values = sorted(values)
    return values[len(values) // 2] if values else 0


def _text_segments(lines):
    """Righe OCR → tratti di testo continui (le parole molto distanti, es. colonne, si separano)."""
    segments = []
    for words in lines:
        med_h = _median([r.height() for _, r in words])
        # icone tonde lette come «O»: carattere singolo molto più alto del testo della riga
        words = [(t, r) for i, (t, r) in enumerate(words)
                 if not (len(t) == 1 and not t.isdigit() and len(words) > 1 and
                         r.height() > _median([q.height() for j, (_, q) in enumerate(words) if j != i]) * 1.25)]
        med_h = _median([r.height() for _, r in words]) or med_h
        cur = []
        for t, r in sorted(words, key=lambda w: w[1].x()):
            if cur and r.x() - cur[-1][1].right() > max(med_h * 1.6, 12):
                segments.append(cur)
                cur = []
            cur.append((t, r))
        if cur:
            segments.append(cur)
    out = []
    for seg in segments:
        rect = QRectF(seg[0][1])
        for _, r in seg[1:]:
            rect = rect.united(r)
        out.append((" ".join(t for t, _ in seg), rect, [r for _, r in seg]))
    return out


def _dist2(a, b):
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2


def _analyze(img, rect):
    """Studia le lettere nel riquadro OCR: (sfondo, colore testo, riquadro reale delle lettere, spessore tratto).

    Il riquadro dell'OCR è approssimativo: le righe/colonne con «inchiostro» contigue alla parte centrale
    danno la posizione vera delle lettere (serve per cancellarle tutte e riscriverle allineate)."""
    W, H = img.width(), img.height()
    h = max(1.0, rect.height())
    ext = h * 0.35
    x0, y0 = max(0, int(rect.left() - ext)), max(0, int(rect.top() - ext))
    x1, y1 = min(W, int(rect.right() + ext) + 1), min(H, int(rect.bottom() + ext) + 1)
    if x1 - x0 < 2 or y1 - y0 < 2:
        return (255, 255, 255), (0, 0, 0), QRectF(rect), 0.0
    region = img.copy(x0, y0, x1 - x0, y1 - y0).convertToFormat(QImage.Format.Format_RGB32)
    rw, rh, bpl = region.width(), region.height(), region.bytesPerLine()
    data = bytes(region.constBits())

    def px(x, y):
        i = y * bpl + x * 4
        return data[i + 2], data[i + 1], data[i]

    ring = []
    for x in range(0, rw, max(1, rw // 40)):
        ring += [px(x, 0), px(x, rh - 1)]
    for y in range(0, rh, max(1, rh // 12)):
        ring += [px(0, y), px(rw - 1, y)]
    bg = (_median([c[0] for c in ring]), _median([c[1] for c in ring]), _median([c[2] for c in ring]))
    # parte centrale = riquadro OCR
    cx0, cy0 = int(rect.left()) - x0, int(rect.top()) - y0
    cx1, cy1 = min(rw, int(rect.right()) - x0 + 1), min(rh, int(rect.bottom()) - y0 + 1)
    core = [px(x, y) for y in range(max(0, cy0), cy1, max(1, (cy1 - cy0) // 16))
            for x in range(max(0, cx0), cx1, max(1, (cx1 - cx0) // 80))]
    if not core:
        return bg, (0, 0, 0), QRectF(rect), 0.0
    core.sort(key=lambda c: _dist2(c, bg), reverse=True)
    far = core[:max(1, len(core) // 10)]
    ink = tuple(sum(c[i] for c in far) // len(far) for i in range(3))
    contrast = _dist2(ink, bg)
    if contrast < 900:
        ink = (0, 0, 0) if sum(bg) > 384 else (255, 255, 255)
        return bg, ink, QRectF(rect), 0.0
    limit = contrast * 0.25
    mask = [[_dist2(px(x, y), bg) > limit for x in range(rw)] for y in range(rh)]
    rows = [any(r) for r in mask]
    cols = [any(mask[y][x] for y in range(rh)) for x in range(rw)]
    top, bottom = max(0, cy0), min(rh - 1, cy1 - 1)
    band = [y for y in range(top, bottom + 1) if rows[y]]
    if not band:
        return bg, ink, QRectF(rect), 0.0
    top, bottom = band[0], band[-1]
    while top > 0 and rows[top - 1]:
        top -= 1
    while bottom < rh - 1 and rows[bottom + 1]:
        bottom += 1
    left, right = max(0, cx0), min(rw - 1, cx1 - 1)
    span = [x for x in range(left, right + 1) if cols[x]]
    if span:
        left, right = span[0], span[-1]
        while left > 0 and cols[left - 1]:
            left -= 1
        while right < rw - 1 and cols[right + 1]:
            right += 1
    # spessore medio dei tratti orizzontali, relativo all'altezza delle lettere
    runs = total = 0
    for y in range(top, bottom + 1):
        prev = False
        for x in range(left, right + 1):
            on = mask[y][x]
            if on:
                total += 1
                if not prev:
                    runs += 1
            prev = on
    stroke = (total / runs) / max(1, bottom - top + 1) if runs else 0.0
    return bg, ink, QRectF(x0 + left, y0 + top, right - left + 1, bottom - top + 1), stroke


def make_editable(img, lines):
    """Cancella il testo riconosciuto dall'immagine. Ritorna (immagine pulita, [(testo, rect lettere px, colore, grassetto)])."""
    source = img.convertToFormat(QImage.Format.Format_RGB32)
    clean = source.copy()
    items = []
    p = QPainter(clean)
    for text, rect, word_rects in _text_segments(lines):
        bg, ink, letters, stroke = _analyze(source, rect)
        color = QColor(*bg)
        pad = max(2.0, letters.height() * 0.15)
        p.fillRect(letters.adjusted(-pad, -pad, pad, pad), color)
        for r in word_rects:
            p.fillRect(r.adjusted(-2, -2, 2, 2), color)
        items.append((text, letters, QColor(*ink), stroke > BOLD_STROKE))
    p.end()
    return clean, items


BOLD_STROKE = 0.20
_TALL = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789bdfhiklt/()[]{}|!?'\"%&#@€$£ÀÈÉÌÒÙ")
_DESC = set("gjpqyQ,;()[]{}|")


def _place_text(page, items, img_w, img_h, target):
    from tkpdf.util import fix_tounicode, font_for
    k = target.width / img_w
    used = set()
    for text, rect, color, bold in items:
        try:
            text.encode("cp1252")
            # Helvetica standard del PDF (non incorporata): con un font incorporato ridotto «Modifica testo»
            # userebbe quel font e le lettere nuove uscirebbero come quadratini
            fontname, fontfile = ("hebo" if bold else "helv"), None
        except UnicodeEncodeError:
            fontname, fontfile = font_for("sans", bold, False)
        if fontfile and fontname not in used:
            page.insert_font(fontname=fontname, fontfile=fontfile)
            used.add(fontname)
        font = fitz.Font(fontfile=fontfile) if fontfile else fitz.Font(fontname)
        x0 = target.x0 + rect.left() * k
        w, h = rect.width() * k, rect.height() * k
        bottom = target.y0 + rect.bottom() * k
        # altezza delle lettere = maiuscole/ascendenti (0,72) o solo minuscole (0,52) + discendenti (0,21)
        top_ratio = 0.72 if any(ch in _TALL for ch in text) else 0.52
        desc_ratio = 0.21 if any(ch in _DESC for ch in text) else 0.0
        size = h / (top_ratio + desc_ratio)
        length = font.text_length(text, fontsize=size)
        if length > w * 1.08:
            size *= w / length
        size = max(3.0, size)
        baseline = bottom - desc_ratio * size
        page.insert_text((x0, baseline), text, fontname=fontname, fontsize=size,
                         color=(color.redF(), color.greenF(), color.blueF()))
    for name in used:
        fix_tounicode(page.parent, page, name)


def _build_editable_page(page, img, items, target, filter_name, jpeg_q):
    """Pagina fatta di oggetti modificabili: sfondi/riquadri/righe/immagini (objects.py) + testo sopra."""
    from tkpdf import objects as tko
    from tkpdf import vectorize
    from tkpdf.util import qimage_to_png_bytes
    doc = page.parent
    ana = vectorize.analyze(img)
    kx, ky = target.width / img.width(), target.height / img.height()

    def box(x, y, w, h):
        return dict(X=target.x0 + x * kx, Y=target.y0 + y * ky, W=w * kx, H=h * ky)

    def rgb(c):
        return [round(v / 255, 3) for v in c[:3]]

    props = []
    if not ana["base_flat"]:
        base = vectorize.erase(img, ana)
        name = tko.image_resource(page, encode(base, filter_name, jpeg_q))
        props.append(dict(K="img", **box(0, 0, img.width(), img.height()), N=name))
    for gi, reg in enumerate(ana["regions"]):
        for x, y, w, h in reg["rects"]:
            props.append(dict(K="rect", G=gi + 1, **box(x, y, w, h), F=rgb(reg["color"])))
    for x, y, w, h, color, sw in ana["frames"]:
        props.append(dict(K="rect", **box(x, y, w, h), S=rgb(color), SW=round(sw * kx, 2)))
    for rect, cut in ana["images"]:
        name = tko.image_resource(page, qimage_to_png_bytes(cut))
        props.append(dict(K="img", **box(rect.x(), rect.y(), rect.width(), rect.height()), N=name))
    for x1, y1, x2, y2, sw, color in ana["lines"]:
        props.append(dict(K="line", X1=target.x0 + x1 * kx, Y1=target.y0 + y1 * ky, X2=target.x0 + x2 * kx,
                          Y2=target.y0 + y2 * ky, S=rgb(color), SW=round(sw * kx, 2)))
    # insert_image ha aggiunto anche i disegni: si riparte da un contenuto vuoto
    for xref in page.get_contents():
        doc.update_stream(xref, b"")
    if items:
        _place_text(page, items, img.width(), img.height(), target)
    blocks = b"".join(tko.block(page, dict(K=p.pop("K"), Id=i + 1, **p)) for i, p in enumerate(props))
    xref, data = tko._single_stream(page)
    doc.update_stream(xref, blocks + data)


def build_pdf(pages, page_size="a4", quality_index=0, progress=None, editable=False):
    """pages: dizionari con image/corners/filter. Ritorna i byte del PDF (None se annullato).

    editable: riconosce il testo e lo riscrive come testo PDF vero (modificabile), togliendolo dall'immagine."""
    _, side, jpeg_q = QUALITIES[quality_index]
    processed = [None] * len(pages)
    texts = [None] * len(pages)
    if editable:
        from tkpdf import ocr
        for i, pg in enumerate(pages):
            if progress and not progress(i, "Preparo"):
                return None
            processed[i] = process(pg["image"], pg["corners"], pg["filter"], side)
        if progress and not progress(len(pages) - 1, "Riconosco il testo di"):
            return None
        texts = ocr.recognize(processed)
    doc = fitz.open()
    try:
        for i, pg in enumerate(pages):
            if progress and not progress(i, "Creo"):
                return None
            img = processed[i] if processed[i] is not None else process(pg["image"], pg["corners"], pg["filter"], side)
            items = []
            if texts[i]:
                img, items = make_editable(img, texts[i])
                if pg["filter"] == "bw":
                    img = img.convertToFormat(QImage.Format.Format_Mono, Qt.ImageConversionFlag.ThresholdDither)
                elif pg["filter"] == "gray":
                    img = img.convertToFormat(QImage.Format.Format_Grayscale8)
            iw, ih = img.width(), img.height()
            if page_size == "a4":
                pw, ph = A4 if ih >= iw else (A4[1], A4[0])
            else:  # stessa proporzione della foto, lato lungo come l'A4
                k = A4[1] / max(iw, ih)
                pw, ph = iw * k, ih * k
            page = doc.new_page(width=pw, height=ph)
            k = min(pw / iw, ph / ih)
            tw, th = iw * k, ih * k
            target = fitz.Rect((pw - tw) / 2, (ph - th) / 2, (pw + tw) / 2, (ph + th) / 2)
            if editable:
                _build_editable_page(page, img, items, target, pg["filter"], jpeg_q)
            else:
                page.insert_image(target, stream=encode(img, pg["filter"], jpeg_q))
        return doc.tobytes(garbage=3, deflate=True)
    finally:
        doc.close()


def rotate_page(pg, delta):
    """Ruota foto, anteprima e angoli di 90° (delta = 90 orario, -90 antiorario)."""
    t = QTransform().rotate(delta)
    pg["image"] = pg["image"].transformed(t)
    pg["preview"] = pg["preview"].transformed(t)
    if delta > 0:
        pts = [(1 - y, x) for x, y in pg["corners"]]
    else:
        pts = [(y, 1 - x) for x, y in pg["corners"]]
    pg["corners"] = order_corners(pts)


# ====================================================================== editor angoli
class CropView(QWidget):
    cornersChanged = Signal()

    HANDLE = 10
    LOUPE = 140

    def __init__(self, parent=None):
        super().__init__(parent)
        self.page = None
        self._drag = None
        self._hover = None
        self.setMouseTracking(True)
        self.setMinimumSize(420, 420)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_page(self, page):
        self.page = page
        self._drag = None
        self.update()

    def _image_rect(self):
        img = self.page["preview"]
        area = QRectF(self.rect()).adjusted(28, 28, -28, -28)
        size = QSize(img.width(), img.height()).scaled(area.size().toSize(), Qt.AspectRatioMode.KeepAspectRatio)
        return QRectF(area.center().x() - size.width() / 2, area.center().y() - size.height() / 2,
                      size.width(), size.height())

    def _points(self):
        r = self._image_rect()
        return [QPointF(r.x() + x * r.width(), r.y() + y * r.height()) for x, y in self.page["corners"]]

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor("#e2e8f0"))
        if self.page is None:
            p.setPen(QColor("#64748b"))
            f = p.font()
            f.setPointSizeF(f.pointSizeF() * 1.25)
            p.setFont(f)
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "📷\n\nTrascina qui le foto dei documenti\noppure clicca «Aggiungi foto»")
            return
        r = self._image_rect()
        p.drawImage(r, self.page["preview"])
        pts = self._points()
        poly = QPolygonF(pts)
        shade = QPainterPath()
        shade.addRect(r)
        inner = QPainterPath()
        inner.addPolygon(poly)
        inner.closeSubpath()
        p.fillPath(shade.subtracted(inner), QColor(15, 23, 42, 150))
        p.setPen(QPen(QColor("#e11d48"), 2.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPolygon(poly)
        for i, pt in enumerate(pts):
            active = i in (self._drag, self._hover)
            p.setPen(QPen(QColor("#e11d48"), 3))
            p.setBrush(QColor("#ffe4e6") if active else QColor("white"))
            rad = self.HANDLE + (3 if active else 0)
            p.drawEllipse(pt, rad, rad)
        if self._drag is not None:
            self._paint_loupe(p, pts[self._drag], r)

    def _paint_loupe(self, p, pt, r):
        img = self.page["preview"]
        size = self.LOUPE
        zoom = 3.0 * r.width() / img.width()  # 3x rispetto a quanto mostrato
        # la lente sta nell'angolo in alto opposto al puntatore
        x = 12 if pt.x() > self.width() / 2 else self.width() - size - 12
        box = QRectF(x, 12, size, size)
        src_w = size / zoom
        sx = (pt.x() - r.x()) / r.width() * img.width()
        sy = (pt.y() - r.y()) / r.height() * img.height()
        src = QRectF(sx - src_w / 2, sy - src_w / 2, src_w, src_w)
        clip = QPainterPath()
        clip.addEllipse(box)
        p.save()
        p.setClipPath(clip)
        p.fillRect(box, QColor("#0f172a"))
        p.drawImage(box, img, src)
        p.restore()
        p.setPen(QPen(QColor("#e11d48"), 1.5))
        c = box.center()
        p.drawLine(QPointF(c.x() - 12, c.y()), QPointF(c.x() + 12, c.y()))
        p.drawLine(QPointF(c.x(), c.y() - 12), QPointF(c.x(), c.y() + 12))
        p.setPen(QPen(QColor("white"), 3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(box)

    def _handle_at(self, pos):
        if self.page is None:
            return None
        best, best_d = None, 26.0
        for i, pt in enumerate(self._points()):
            d = math.hypot(pt.x() - pos.x(), pt.y() - pos.y())
            if d < best_d:
                best, best_d = i, d
        return best

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag = self._handle_at(e.position())
            self.update()

    def mouseMoveEvent(self, e):
        if self._drag is None:
            h = self._handle_at(e.position())
            if h != self._hover:
                self._hover = h
                self.setCursor(Qt.CursorShape.SizeAllCursor if h is not None else Qt.CursorShape.ArrowCursor)
                self.update()
            return
        r = self._image_rect()
        x = min(1.0, max(0.0, (e.position().x() - r.x()) / r.width()))
        y = min(1.0, max(0.0, (e.position().y() - r.y()) / r.height()))
        self.page["corners"][self._drag] = (x, y)
        self.update()

    def mouseReleaseEvent(self, e):
        if self._drag is not None:
            corners = self.page["corners"]
            if quad_area(corners) > 0.01:
                self.page["corners"] = order_corners(corners)
            self._drag = None
            self.update()
            self.cornersChanged.emit()


# ====================================================================== finestra
class ScanDialog(QDialog):
    """Foto → pagine PDF. Dopo exec() il PDF è in self.pdf_bytes; self.append dice se accodarlo."""

    def __init__(self, parent=None, start_dir="", can_append=False, settings=None):
        super().__init__(parent)
        self.setWindowTitle("Da foto a PDF")
        self.setAcceptDrops(True)
        self.resize(1180, 780)
        self.start_dir = start_dir
        self.settings = settings
        self.pdf_bytes = None
        self.append = False
        self.made_editable = False
        self.pages = []
        self._by_id = {}
        self._next_id = 0
        self.current = None

        root = QHBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(14)

        # --- colonna pagine
        left = QVBoxLayout()
        left.addWidget(self._title("PAGINE"))
        self.list = QListWidget()
        self.list.setIconSize(QSize(THUMB_W, THUMB_H))
        self.list.setFixedWidth(THUMB_W + 34)
        self.list.setSpacing(3)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list.setStyleSheet("QListWidget{background:white;border:1px solid #e2e8f0;border-radius:10px;padding:4px;}"
                                "QListWidget::item{border-radius:6px;padding:4px;color:#64748b;}"
                                "QListWidget::item:selected{background:#ffe4e6;color:#be123c;}")
        self.list.currentRowChanged.connect(self._select)
        self.list.model().rowsMoved.connect(self._reordered)
        left.addWidget(self.list, 1)
        add_b = QPushButton("➕ Aggiungi foto")
        add_b.setObjectName("primary")
        add_b.clicked.connect(self.add_dialog)
        self.remove_b = QPushButton("🗑️ Rimuovi")
        self.remove_b.clicked.connect(self._remove)
        left.addWidget(add_b)
        left.addWidget(self.remove_b)
        root.addLayout(left)

        # --- editor
        center = QVBoxLayout()
        hint = QLabel("Trascina i cerchi rossi sugli angoli del foglio: la pagina verrà raddrizzata.")
        hint.setStyleSheet("color:#64748b;")
        center.addWidget(hint)
        self.crop = CropView()
        self.crop.cornersChanged.connect(self._schedule_preview)
        center.addWidget(self.crop, 1)
        tools = QHBoxLayout()
        self.page_tools = []
        for text, tip, slot in (("🎯 Rileva bordi", "Trova di nuovo il foglio nella foto", self._detect),
                                ("⛶ Tutta la foto", "Usa la foto intera senza ritagliare", self._full),
                                ("↺ Ruota", "Ruota a sinistra", lambda: self._rotate(-90)),
                                ("↻ Ruota", "Ruota a destra", lambda: self._rotate(90))):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            tools.addWidget(b)
            self.page_tools.append(b)
        tools.addStretch(1)
        center.addLayout(tools)
        root.addLayout(center, 1)

        # --- pannello opzioni
        side_w = QWidget()
        side_w.setFixedWidth(290)
        side = QVBoxLayout(side_w)
        side.setContentsMargins(0, 0, 0, 0)
        side.addWidget(self._title("ANTEPRIMA PAGINA"))
        self.preview = QLabel()
        self.preview.setFixedSize(290, 300)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setStyleSheet("background:#e2e8f0;border-radius:10px;")
        side.addWidget(self.preview)
        side.addSpacing(8)
        side.addWidget(self._title("FILTRO"))
        self.filter_group = QButtonGroup(self)
        for i, (_, label, tip) in enumerate(FILTERS):
            rb = QRadioButton(label)
            rb.setToolTip(tip)
            self.filter_group.addButton(rb, i)
            side.addWidget(rb)
        self.filter_group.idClicked.connect(self._filter_changed)
        self.all_filter = QPushButton("Usa questo filtro per tutte le pagine")
        self.all_filter.clicked.connect(self._filter_all)
        side.addWidget(self.all_filter)
        side.addSpacing(8)
        side.addWidget(self._title("PDF"))
        self.page_size = QComboBox()
        self.page_size.addItem("Formato A4", "a4")
        self.page_size.addItem("Stessa proporzione della foto", "photo")
        self.quality = QComboBox()
        for label, _, _ in QUALITIES:
            self.quality.addItem(label)
        side.addWidget(self.page_size)
        side.addWidget(self.quality)
        from tkpdf import ocr
        self.editable = QCheckBox("✏️ Rendi tutto modificabile")
        self.editable.setToolTip("Le scritte diventano testo vero (le cambi con «Modifica testo»);\n"
                                 "sfondi, riquadri, righe e immagini diventano oggetti che puoi spostare,\n"
                                 "ridimensionare, ricolorare ed eliminare (strumento «🧩 Oggetti»).")
        self.editable.setVisible(ocr.available())
        self.editable.setChecked(ocr.available() and (settings is None or
                                                      settings.value("scan/editable", True, type=bool)))
        side.addWidget(self.editable)
        self.dest = QComboBox()
        self.dest.addItem("Crea un nuovo PDF", False)
        self.dest.addItem("Aggiungi in fondo al PDF aperto", True)
        self.dest.setVisible(can_append)
        side.addWidget(self.dest)
        side.addStretch(1)
        self.count = QLabel()
        self.count.setStyleSheet("color:#64748b;")
        side.addWidget(self.count)
        btns = QHBoxLayout()
        cancel = QPushButton("Annulla")
        cancel.clicked.connect(self.reject)
        self.create_b = QPushButton("📄 Crea PDF")
        self.create_b.setObjectName("accent")
        self.create_b.setMinimumHeight(38)
        self.create_b.clicked.connect(self.accept)
        btns.addWidget(cancel)
        btns.addWidget(self.create_b, 1)
        side.addLayout(btns)
        root.addWidget(side_w)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._update_preview)

        self.default_filter = "document"
        if settings is not None:
            self.default_filter = settings.value("scan/filter", "document")
            self.page_size.setCurrentIndex(max(0, self.page_size.findData(settings.value("scan/page", "a4"))))
            try:
                self.quality.setCurrentIndex(min(len(QUALITIES) - 1, max(0, int(settings.value("scan/quality", 1)))))
            except (TypeError, ValueError):
                self.quality.setCurrentIndex(1)
        self._set_filter_radio(self.default_filter)
        self._renumber()
        self._refresh_state()

    def _page_of(self, item):
        return self._by_id[item.data(Qt.ItemDataRole.UserRole)]

    @staticmethod
    def _title(text):
        lab = QLabel(text)
        lab.setStyleSheet("color:#64748b; font-size:8.5pt; font-weight:700;")
        return lab

    # ------------------------------------------------------------ foto
    def add_dialog(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Scegli le foto", self.start_dir, PHOTO_FILTER)
        if files:
            self.start_dir = os.path.dirname(files[0])
            self.add_files(files)

    def add_files(self, files):
        progress = None
        if len(files) > 2:
            progress = QProgressDialog("Carico le foto…", "Annulla", 0, len(files), self)
            progress.setWindowModality(Qt.WindowModality.WindowModal)
            progress.setMinimumDuration(0)
        failed = []
        first_new = len(self.pages)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for i, path in enumerate(files):
                if progress:
                    progress.setValue(i)
                    QApplication.processEvents()
                    if progress.wasCanceled():
                        break
                img = load_photo(path)
                if img is None:
                    failed.append(os.path.basename(path))
                    continue
                preview = fit_side(img, PREVIEW_SIDE)
                corners, is_doc = auto_setup(preview)
                page = dict(path=path, image=img, preview=preview, corners=corners,
                            filter=self.default_filter if is_doc else "original")
                self.pages.append(page)
                item = QListWidgetItem()
                # nella lista solo l'id: PySide restituirebbe una copia del dizionario
                self._next_id += 1
                self._by_id[self._next_id] = page
                item.setData(Qt.ItemDataRole.UserRole, self._next_id)
                self.list.addItem(item)
                self._update_thumb(item)
        finally:
            QApplication.restoreOverrideCursor()
            if progress:
                progress.close()
        self._renumber()
        if len(self.pages) > first_new:
            self.list.setCurrentRow(first_new)
        self._refresh_state()
        if failed:
            msg = "Impossibile leggere:\n" + "\n".join(failed[:8])
            if any(f.lower().endswith((".heic", ".heif")) for f in failed):
                msg += ("\n\nLe foto HEIC dell'iPhone non sono leggibili: inviale come JPG (es. via WhatsApp o "
                        "e-mail) oppure sull'iPhone imposta Impostazioni → Fotocamera → Formati → «Più compatibile».")
            QMessageBox.warning(self, APP_TITLE, msg)

    def _remove(self):
        row = self.list.currentRow()
        if row < 0:
            return
        item = self.list.takeItem(row)
        self.pages.remove(self._by_id.pop(item.data(Qt.ItemDataRole.UserRole)))
        self._renumber()
        if not self.pages:
            self.current = None
            self.crop.set_page(None)
            self.preview.clear()
        self._refresh_state()

    def _reordered(self, *_):
        self.pages = [self._page_of(self.list.item(i)) for i in range(self.list.count())]
        self._renumber()

    def _renumber(self):
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.data(Qt.ItemDataRole.UserRole + 1) != i + 1:
                self._update_thumb(item)
        n = len(self.pages)
        self.count.setText("Nessuna foto" if not n else (f"{n} pagine" if n > 1 else "1 pagina"))

    def _refresh_state(self):
        has = bool(self.pages)
        for w in self.page_tools + [self.remove_b, self.create_b]:
            w.setEnabled(has)
        for b in self.filter_group.buttons():
            b.setEnabled(has)
        self.all_filter.setVisible(len(self.pages) > 1)

    # ------------------------------------------------------------ pagina corrente
    def _select(self, row):
        if row < 0:
            return
        self.current = self._page_of(self.list.item(row))
        self.crop.set_page(self.current)
        self._set_filter_radio(self.current["filter"])
        self._update_preview()

    def _set_filter_radio(self, key):
        idx = next((i for i, f in enumerate(FILTERS) if f[0] == key), 0)
        self.filter_group.button(idx).setChecked(True)

    def _filter_changed(self, idx):
        self.default_filter = FILTERS[idx][0]
        if self.current is not None:
            self.current["filter"] = self.default_filter
            self._update_preview()

    def _filter_all(self):
        for pg in self.pages:
            pg["filter"] = self.default_filter
        for i in range(self.list.count()):
            self._update_thumb(self.list.item(i))

    def _detect(self):
        if self.current is None:
            return
        found = detect_corners(self.current["preview"])
        if found is None:
            QMessageBox.information(self, APP_TITLE, "Non trovo il foglio in questa foto: sposta a mano i cerchi "
                                                     "sugli angoli.")
            return
        self.current["corners"] = found
        self.crop.update()
        self._update_preview()

    def _full(self):
        if self.current is not None:
            self.current["corners"] = full_corners()
            self.crop.update()
            self._update_preview()

    def _rotate(self, delta):
        if self.current is not None:
            rotate_page(self.current, delta)
            self.crop.update()
            self._update_preview()

    def _schedule_preview(self):
        self._timer.start(60)

    def _update_preview(self):
        if self.current is None:
            return
        pg = self.current
        img = process(pg["preview"], pg["corners"], pg["filter"], 900)
        pix = QPixmap.fromImage(img).scaled(self.preview.size() - QSize(16, 16), Qt.AspectRatioMode.KeepAspectRatio,
                                            Qt.TransformationMode.SmoothTransformation)
        self.preview.setPixmap(pix)
        item = self.list.currentItem()
        if item is not None:
            self._update_thumb(item, img)

    def _update_thumb(self, item, processed=None):
        pg = self._page_of(item)
        if processed is None:
            processed = process(fit_side(pg["preview"], 500), pg["corners"], pg["filter"], 300)
        number = self.list.row(item) + 1
        thumb = QImage(THUMB_W, THUMB_H, QImage.Format.Format_ARGB32)
        thumb.fill(Qt.GlobalColor.transparent)
        scaled = processed.scaled(THUMB_W - 2, THUMB_H - 2, Qt.AspectRatioMode.KeepAspectRatio,
                                  Qt.TransformationMode.SmoothTransformation)
        p = QPainter(thumb)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        x, y = (THUMB_W - scaled.width()) // 2, (THUMB_H - scaled.height()) // 2
        p.fillRect(x - 1, y - 1, scaled.width() + 2, scaled.height() + 2, QColor("#cbd5e1"))
        p.drawImage(x, y, scaled)
        # numero di pagina sul bordo in basso
        badge = QRectF(THUMB_W / 2 - 14, y + scaled.height() - 26, 28, 20)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#0f172a"))
        p.drawRoundedRect(badge, 10, 10)
        p.setPen(QColor("white"))
        f = p.font()
        f.setBold(True)
        p.setFont(f)
        p.drawText(badge, Qt.AlignmentFlag.AlignCenter, str(number))
        p.end()
        pix = QPixmap.fromImage(thumb)
        icon = QIcon()
        icon.addPixmap(pix, QIcon.Mode.Normal)
        icon.addPixmap(pix, QIcon.Mode.Selected)  # niente velo azzurro sulla pagina scelta
        item.setIcon(icon)
        item.setData(Qt.ItemDataRole.UserRole + 1, number)
        item.setToolTip(os.path.basename(pg["path"]))

    # ------------------------------------------------------------ drag & drop
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        files = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        files = [f for f in files if os.path.isfile(f) and f.lower().endswith(PHOTO_EXT)]
        if files:
            self.add_files(files)

    # ------------------------------------------------------------ crea
    def accept(self):
        if not self.pages:
            QMessageBox.information(self, APP_TITLE, "Aggiungi almeno una foto.")
            return
        if self.settings is not None:
            self.settings.setValue("scan/filter", self.default_filter)
            self.settings.setValue("scan/page", self.page_size.currentData())
            self.settings.setValue("scan/quality", self.quality.currentIndex())
            if self.editable.isVisible():
                self.settings.setValue("scan/editable", self.editable.isChecked())
        progress = QProgressDialog("Creo il PDF…", "Annulla", 0, len(self.pages), self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)

        def step(i, verb="Elaboro"):
            progress.setValue(i)
            progress.setLabelText(f"{verb} la pagina {i + 1} di {len(self.pages)}…" if verb != "Riconosco il testo di"
                                  else "Riconosco il testo…")
            QApplication.processEvents()
            return not progress.wasCanceled()

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.made_editable = self.editable.isVisible() and self.editable.isChecked()
            data = build_pdf(self.pages, self.page_size.currentData(), self.quality.currentIndex(), step,
                             editable=self.made_editable)
        except Exception as exc:
            QMessageBox.critical(self, APP_TITLE, f"Creazione del PDF non riuscita:\n{exc}")
            return
        finally:
            QApplication.restoreOverrideCursor()
            progress.close()
        if data is None:
            return
        self.pdf_bytes = data
        self.append = bool(self.dest.isVisibleTo(self) and self.dest.currentData())
        super().accept()
