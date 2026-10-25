"""Scompone un'immagine (già senza testo) in oggetti PDF modificabili.

- zone a tinta unita (sfondi, fasce)  → rettangoli vettoriali nel contenuto della pagina
- contorni rettangolari               → riquadri con bordo
- righe sottili                       → linee
- icone, loghi, disegni               → immagini con sfondo trasparente
Tutti diventano oggetti di objects.py (spostabili, ricolorabili, eliminabili).

L'analisi lavora su una copia ridotta (lato ≤ ANALYSIS_SIDE); i ritagli si prendono dall'immagine intera."""
from collections import Counter

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter

ANALYSIS_SIDE = 480
REGION_MIN = 0.012      # quota minima dell'immagine per una zona di sfondo
COLOR_TOL = 22 ** 2 * 3  # distanza di colore entro cui due pixel sono «la stessa tinta»
MAX_RECTS = 400


def _d2(a, b):
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2


def _pixels(img):
    img = img.convertToFormat(QImage.Format.Format_RGB32)
    w, h, bpl = img.width(), img.height(), img.bytesPerLine()
    data = bytes(img.constBits())
    px = [None] * (w * h)
    for y in range(h):
        base = y * bpl
        for x in range(w):
            i = base + x * 4
            px[y * w + x] = (data[i + 2], data[i + 1], data[i])
    return w, h, px


def analyze(img):
    """Ritorna dict(regions=[(colore, [(x, y, w, h) px immagine intera])], lines=[...], images=[...], base_flat=bool).

    lines: (x1, y1, x2, y2, spessore, colore) · images: (QRectF, QImage ARGB con trasparenza)."""
    W, H = img.width(), img.height()
    k = min(1.0, ANALYSIS_SIDE / max(W, H))
    small = img if k == 1.0 else img.scaled(max(1, round(W * k)), max(1, round(H * k)),
                                            Qt.AspectRatioMode.IgnoreAspectRatio,
                                            Qt.TransformationMode.SmoothTransformation)
    w, h, px = _pixels(small)
    n = w * h
    sx, sy = W / w, H / h

    # 1) zone di tinta unita: riempimento a tolleranza dal colore del seme
    label = [-1] * n
    comps = []
    for start in range(n):
        if label[start] != -1:
            continue
        seed = px[start]
        cid = len(comps)
        label[start] = cid
        stack, members = [start], []
        while stack:
            i = stack.pop()
            members.append(i)
            x, y = i % w, i // w
            for j in ((i - 1) if x else -1, (i + 1) if x < w - 1 else -1, (i - w) if y else -1, (i + w) if y < h - 1 else -1):
                if j >= 0 and label[j] == -1 and _d2(px[j], seed) < COLOR_TOL:
                    label[j] = cid
                    stack.append(j)
        comps.append(members)
    region_of = {}
    regions = []
    for cid, members in enumerate(comps):
        if len(members) >= n * REGION_MIN:
            cols = [px[i] for i in members[::max(1, len(members) // 400)]]
            color = tuple(sorted(c[t] for c in cols)[len(cols) // 2] for t in range(3))
            region_of[cid] = len(regions)
            regions.append(color)
    owner = [region_of.get(label[i], -1) for i in range(n)]

    # 2) bordi sfumati tra due zone: si assegnano alla zona vicina più simile
    for _ in range(2):
        changed = []
        for i in range(n):
            if owner[i] != -1:
                continue
            x, y = i % w, i // w
            best, best_d = -1, 70 ** 2 * 3
            for j in ((i - 1) if x else -1, (i + 1) if x < w - 1 else -1, (i - w) if y else -1, (i + w) if y < h - 1 else -1):
                if j >= 0 and owner[j] != -1:
                    d = _d2(px[i], regions[owner[j]])
                    if d < best_d:
                        best, best_d = owner[j], d
            if best != -1:
                changed.append((i, best))
        for i, r in changed:
            owner[i] = r
        if not changed:
            break

    # 3) oggetti in primo piano: gruppi di pixel non di sfondo (vicini entro 2 px)
    seen = bytearray(n)
    objects = []
    for start in range(n):
        if owner[start] != -1 or seen[start]:
            continue
        seen[start] = 1
        stack, members = [start], []
        while stack:
            i = stack.pop()
            members.append(i)
            x, y = i % w, i // w
            for dy in (-2, -1, 0, 1, 2):
                yy = y + dy
                if yy < 0 or yy >= h:
                    continue
                for dx in (-2, -1, 0, 1, 2):
                    xx = x + dx
                    if 0 <= xx < w:
                        j = yy * w + xx
                        if owner[j] == -1 and not seen[j]:
                            seen[j] = 1
                            stack.append(j)
        objects.append(members)

    lines, images, frames, leftovers = [], [], [], []
    min_area = max(4, n * 0.00025)
    for members in objects:
        xs = [i % w for i in members]
        ys = [i // w for i in members]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        bw, bh = x1 - x0 + 1, y1 - y0 + 1
        if len(members) < min_area or max(bw, bh) < 3:
            leftovers.append(members)
            continue
        # zona di sfondo prevalente attorno all'oggetto
        around = Counter()
        for i in members:
            x, y = i % w, i // w
            for j in ((i - 1) if x else -1, (i + 1) if x < w - 1 else -1, (i - w) if y else -1, (i + w) if y < h - 1 else -1):
                if j >= 0 and owner[j] != -1:
                    around[owner[j]] += 1
        bg_region = around.most_common(1)[0][0] if around else (0 if regions else -1)
        bg = regions[bg_region] if bg_region >= 0 else (255, 255, 255)
        cols = sorted((px[i] for i in members), key=lambda c: -_d2(c, bg))
        top = cols[:max(1, len(cols) // 2)]
        color = tuple(sum(c[t] for c in top) // len(top) for t in range(3))
        thin, long_ = min(bw, bh), max(bw, bh)
        edge_t = max(1, round(thin * 0.12))
        on_edge = sum(1 for i in members if min(i % w - x0, x1 - i % w, i // w - y0, y1 - i // w) < edge_t)
        perimeter = 2 * (bw + bh)
        is_line = thin <= max(2, round(long_ * 0.06)) and long_ >= 6 * thin and long_ >= 8
        if is_line and _on_boundary(owner, w, h, x0, y0, x1, y1, bw >= bh):
            # sfumatura sul confine tra due zone, non una riga vera
            leftovers.append(members)
            continue
        if is_line:
            if bw >= bh:
                cy = (y0 + y1 + 1) / 2 * sy
                lines.append((x0 * sx, cy, (x1 + 1) * sx, cy, max(1.0, bh * sy * 0.6), color))
            else:
                cx = (x0 + x1 + 1) / 2 * sx
                lines.append((cx, y0 * sy, cx, (y1 + 1) * sy, max(1.0, bw * sx * 0.6), color))
        elif thin >= 10 and on_edge >= len(members) * 0.9 and len(members) >= perimeter * 0.7:
            # contorno rettangolare → riquadro con bordo
            sw = max(1.0, len(members) / perimeter * min(sx, sy))
            frames.append((x0 * sx, y0 * sy, bw * sx, bh * sy, color, sw))
        else:
            rect = QRectF((x0 - 1) * sx, (y0 - 1) * sy, (bw + 2) * sx, (bh + 2) * sy).intersected(QRectF(0, 0, W, H))
            images.append((rect, _cutout(img, rect, bg)))
        for i in members:
            owner[i] = bg_region

    # 4) residui (puntini, sfumature): alla zona vicina, se c'è
    for members in leftovers:
        for i in members:
            x, y = i % w, i // w
            for j in ((i - 1) if x else -1, (i + 1) if x < w - 1 else -1, (i - w) if y else -1, (i + w) if y < h - 1 else -1):
                if j >= 0 and owner[j] != -1:
                    owner[i] = owner[j]
                    break

    # 5) sfondo vettoriale solo se è davvero a tinte unite (screenshot, grafiche); foto e carta restano immagine
    unowned = sum(1 for o in owner if o == -1)
    flat = bool(regions) and unowned <= n * 0.01 and _is_flat(px, owner, regions)
    shapes = _region_shapes(owner, w, h, sx, sy, regions) if flat else None
    if shapes is None:
        flat = False
    return dict(base_flat=flat, regions=shapes or [], frames=frames, lines=lines, images=images)


def _on_boundary(owner, w, h, x0, y0, x1, y1, horizontal):
    """Vero se ai due lati della riga ci sono zone diverse (bordo tra due sfondi)."""
    diff = total = 0
    if horizontal:
        for x in range(x0, x1 + 1, max(1, (x1 - x0) // 40)):
            a = owner[(y0 - 1) * w + x] if y0 > 0 else -1
            b = owner[(y1 + 1) * w + x] if y1 < h - 1 else -1
            total += 1
            diff += a != -1 and b != -1 and a != b
    else:
        for y in range(y0, y1 + 1, max(1, (y1 - y0) // 40)):
            a = owner[y * w + x0 - 1] if x0 > 0 else -1
            b = owner[y * w + x1 + 1] if x1 < w - 1 else -1
            total += 1
            diff += a != -1 and b != -1 and a != b
    return total > 0 and diff >= total * 0.6


def _region_shapes(owner, w, h, sx, sy, regions):
    """Zone → riquadri in ordine di disegno. Ogni zona è un solo riquadro (il suo ingombro) se, disegnando
    prima i più grandi, il risultato coincide con l'immagine; altrimenti si scompone in più riquadri."""
    boxes = {}
    for i, o in enumerate(owner):
        if o == -1:
            continue
        x, y = i % w, i // w
        b = boxes.get(o)
        boxes[o] = (x, y, x, y) if b is None else (min(b[0], x), min(b[1], y), max(b[2], x), max(b[3], y))
    order = sorted(boxes, key=lambda o: -(boxes[o][2] - boxes[o][0] + 1) * (boxes[o][3] - boxes[o][1] + 1))
    canvas = [-1] * (w * h)
    for o in order:
        x0, y0, x1, y1 = boxes[o]
        for y in range(y0, y1 + 1):
            canvas[y * w + x0:y * w + x1 + 1] = [o] * (x1 - x0 + 1)
    wrong = sum(1 for i, o in enumerate(owner) if o != -1 and canvas[i] != o)
    if wrong <= len(owner) * 0.015:
        return [dict(color=regions[o], rects=[(boxes[o][0] * sx, boxes[o][1] * sy, (boxes[o][2] - boxes[o][0] + 1) * sx,
                                               (boxes[o][3] - boxes[o][1] + 1) * sy)]) for o in order]
    runs = _region_rects(owner, w, h, sx, sy)
    if len(runs) > MAX_RECTS:
        return None
    grouped = {}
    for o, r in runs:
        grouped.setdefault(o, []).append(r)
    return [dict(color=regions[o], rects=grouped[o]) for o in order if o in grouped]


def _is_flat(px, owner, regions):
    """Le zone devono essere uniformi (niente sfumature/grana sotto la tolleranza)."""
    far = total = 0
    for i in range(0, len(px), 3):
        o = owner[i]
        if o == -1:
            continue
        total += 1
        if _d2(px[i], regions[o]) > 14 ** 2 * 3:
            far += 1
    return total > 0 and far <= total * 0.04


def _region_rects(owner, w, h, sx, sy):
    """Zone → rettangoli: tratti orizzontali per riga, uniti verticalmente se identici."""
    out = []
    open_runs = {}
    for y in range(h + 1):
        runs = {}
        if y < h:
            x = 0
            row = owner[y * w:(y + 1) * w]
            while x < w:
                o = row[x]
                x2 = x
                while x2 + 1 < w and row[x2 + 1] == o:
                    x2 += 1
                if o != -1:
                    runs[(x, x2, o)] = y
                x = x2 + 1
        for key, y_start in list(open_runs.items()):
            if key in runs:
                runs[key] = y_start
            else:
                x0, x1, o = key
                out.append((o, (x0 * sx, y_start * sy, (x1 - x0 + 1) * sx, (y - y_start) * sy)))
        open_runs = runs
        if len(out) > MAX_RECTS:
            break
    return out


def _cutout(img, rect, bg):
    """Ritaglio con trasparenza dove il colore è quello dello sfondo (bordi morbidi)."""
    crop = img.copy(rect.toAlignedRect()).convertToFormat(QImage.Format.Format_ARGB32)
    side = max(crop.width(), crop.height())
    if 0 < side < 240:  # ritagli da immagini piccole: ingranditi morbidi, niente bordi a scalini
        k = min(4.0, 240 / side)
        crop = crop.scaled(round(crop.width() * k), round(crop.height() * k), Qt.AspectRatioMode.IgnoreAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
    w, h, bpl = crop.width(), crop.height(), crop.bytesPerLine()
    buf = bytearray(bytes(crop.constBits()))
    t0, t1 = 18 ** 2 * 3, 60 ** 2 * 3
    for y in range(h):
        base = y * bpl
        for x in range(w):
            i = base + x * 4
            d = _d2((buf[i + 2], buf[i + 1], buf[i]), bg)
            if d <= t0:
                buf[i + 3] = 0
            elif d < t1:
                buf[i + 3] = int(255 * (d - t0) / (t1 - t0))
    out = QImage(bytes(buf), w, h, bpl, QImage.Format.Format_ARGB32)
    return out.copy()


def erase(img, analysis):
    """Immagine di sfondo senza gli oggetti estratti (riempiti con il colore attorno)."""
    out = img.convertToFormat(QImage.Format.Format_RGB32)
    p = QPainter(out)
    for rect, cut in analysis["images"]:
        # colore dominante del bordo del ritaglio = sfondo
        p.fillRect(rect, _border_color(img, rect))
    for x1, y1, x2, y2, width, _ in analysis["lines"]:
        pad = width * 1.2 + 1
        r = QRectF(min(x1, x2) - pad, min(y1, y2) - pad, abs(x2 - x1) + 2 * pad, abs(y2 - y1) + 2 * pad)
        p.fillRect(r, _border_color(img, r))
    p.end()
    return out


def _border_color(img, rect):
    r = rect.toAlignedRect().adjusted(-1, -1, 1, 1).intersected(img.rect())
    cols = []
    for x in range(r.left(), r.right() + 1, max(1, r.width() // 20)):
        cols += [img.pixelColor(x, r.top()), img.pixelColor(x, r.bottom())]
    for y in range(r.top(), r.bottom() + 1, max(1, r.height() // 20)):
        cols += [img.pixelColor(r.left(), y), img.pixelColor(r.right(), y)]
    if not cols:
        return QColor("white")
    key = Counter((c.red() // 8, c.green() // 8, c.blue() // 8) for c in cols).most_common(1)[0][0]
    match = [c for c in cols if (c.red() // 8, c.green() // 8, c.blue() // 8) == key]
    return QColor(sum(c.red() for c in match) // len(match), sum(c.green() for c in match) // len(match),
                  sum(c.blue() for c in match) // len(match))
