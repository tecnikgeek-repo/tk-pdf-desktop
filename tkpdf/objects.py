"""Oggetti grafici modificabili nel contenuto della pagina (sfondi, riquadri, righe, immagini).

Ogni oggetto è una sequenza marcata PDF standard:
    /TkObj <</K /rect /Id 3 /X 10 /Y 20 /W 200 /H 80 /F [0 .4 .6] /S [1 1 1] /SW 2>> BDC ...disegno... EMC
Le proprietà (in punti, coordinate della pagina non ruotata con origine in alto a sinistra) descrivono
l'oggetto: il disegno si rigenera da queste, quindi spostare/ricolorare/eliminare = riscrivere il blocco.
Stanno nel contenuto (non sono annotazioni) così il testo resta sopra e «Modifica testo» continua a funzionare;
sopravvivono alle redazioni di MuPDF usate da Modifica testo."""
import re

import pymupdf as fitz

OBJ_RE = re.compile(rb"/TkObj\s*<<(.*?)>>\s*BDC(.*?)EMC", re.S)
_TOKEN_RE = re.compile(rb"/(\w+)\s*(\[[^\]]*\]|/[\w.]+|[-+]?\d*\.?\d+)")
KINDS = ("rect", "line", "img")


def _num(v):
    return f"{v:.3f}".rstrip("0").rstrip(".") if isinstance(v, float) else str(v)


def _parse_props(raw):
    props = {}
    for key, val in _TOKEN_RE.findall(raw):
        k = key.decode()
        if val.startswith(b"["):
            props[k] = [float(x) for x in val[1:-1].split()]
        elif val.startswith(b"/"):
            props[k] = val[1:].decode()
        else:
            props[k] = float(val)
    return props


def _serialize(props):
    parts = []
    for k, v in props.items():
        if v is None:
            continue
        if isinstance(v, (list, tuple)):
            parts.append(f"/{k} [{' '.join(_num(float(x)) for x in v)}]")
        elif isinstance(v, str):
            parts.append(f"/{k} /{v}")
        else:
            parts.append(f"/{k} {_num(float(v))}")
    return " ".join(parts)


def _pdf_point(page, x, y):
    return fitz.Point(x, y) * ~page.transformation_matrix


def _ops(page, p):
    k = p["K"]
    if k == "rect":
        a = _pdf_point(page, p["X"], p["Y"] + p["H"])
        fill, stroke = p.get("F"), p.get("S")
        sw = float(p.get("SW") or 0)
        out = ["q"]
        if fill:
            out.append(f"{' '.join(_num(float(c)) for c in fill)} rg")
        if stroke and sw > 0:
            out.append(f"{' '.join(_num(float(c)) for c in stroke)} RG {_num(sw)} w")
            # il bordo sta dentro il riquadro
            inset = sw / 2
            out.append(f"{_num(a.x + inset)} {_num(a.y + inset)} {_num(p['W'] - sw)} {_num(p['H'] - sw)} re")
            if fill:
                out.append("B" if p["W"] > sw and p["H"] > sw else "f")
            else:
                out.append("S")
        elif fill:
            out.append(f"{_num(a.x)} {_num(a.y)} {_num(p['W'])} {_num(p['H'])} re f")
        out.append("Q")
        return " ".join(out)
    if k == "line":
        a = _pdf_point(page, p["X1"], p["Y1"])
        b = _pdf_point(page, p["X2"], p["Y2"])
        color = p.get("S") or [0, 0, 0]
        return (f"q {' '.join(_num(float(c)) for c in color)} RG {_num(float(p.get('SW') or 1))} w 2 J "
                f"{_num(a.x)} {_num(a.y)} m {_num(b.x)} {_num(b.y)} l S Q")
    if k == "img":
        a = _pdf_point(page, p["X"], p["Y"] + p["H"])
        return f"q {_num(p['W'])} 0 0 {_num(p['H'])} {_num(a.x)} {_num(a.y)} cm /{p['N']} Do Q"
    raise ValueError(k)


def block(page, props):
    return f"/TkObj <<{_serialize(props)}>> BDC {_ops(page, props)} EMC\n".encode()


def bbox(o):
    if o["K"] == "line":
        pad = max(float(o.get("SW") or 1) / 2, 3.0)
        return fitz.Rect(min(o["X1"], o["X2"]) - pad, min(o["Y1"], o["Y2"]) - pad,
                         max(o["X1"], o["X2"]) + pad, max(o["Y1"], o["Y2"]) + pad)
    return fitz.Rect(o["X"], o["Y"], o["X"] + o["W"], o["Y"] + o["H"])


def list_objects(page):
    """Oggetti della pagina dal basso verso l'alto."""
    try:
        data = page.read_contents()
    except Exception:
        return []
    out = []
    for m in OBJ_RE.finditer(data):
        props = _parse_props(m.group(1))
        if props.get("K") in KINDS and "Id" in props:
            props["Id"] = int(props["Id"])
            out.append(props)
    return out


def has_objects(page):
    try:
        return b"/TkObj" in page.read_contents()
    except Exception:
        return False


def _single_stream(page):
    doc = page.parent
    xrefs = page.get_contents()
    data = page.read_contents()
    if not xrefs:
        xref = doc.get_new_xref()
        doc.update_object(xref, "<<>>")
        doc.update_stream(xref, data)
        doc.xref_set_key(page.xref, "Contents", f"{xref} 0 R")
        return xref, data
    if len(xrefs) > 1:
        doc.xref_set_key(page.xref, "Contents", f"{xrefs[0]} 0 R")
    doc.update_stream(xrefs[0], data)
    return xrefs[0], data


def _rewrite(page, fn):
    xref, data = _single_stream(page)
    matches = [(m, _parse_props(m.group(1))) for m in OBJ_RE.finditer(data)]
    new = fn(data, matches)
    page.parent.update_stream(xref, new)


def update(page, obj_id, changes):
    """changes: dict di proprietà da cambiare (None = togli la proprietà)."""
    def fn(data, matches):
        for m, props in matches:
            if int(props.get("Id", -1)) == obj_id:
                props.update(changes)
                props = {k: v for k, v in props.items() if v is not None}
                return data[:m.start()] + block(page, props).rstrip(b"\n") + data[m.end():]
        return data
    _rewrite(page, fn)


def delete(page, obj_id):
    def fn(data, matches):
        for m, props in matches:
            if int(props.get("Id", -1)) == obj_id:
                return data[:m.start()] + data[m.end():]
        return data
    _rewrite(page, fn)


def duplicate(page, obj_id, dx=12.0, dy=12.0):
    """Copia l'oggetto spostata di poco; ritorna il nuovo Id."""
    nid = new_id(page)

    def fn(data, matches):
        for m, props in matches:
            if int(props.get("Id", -1)) == obj_id:
                copy = dict(props, Id=nid, **moved(props, dx, dy))
                copy.pop("G", None)
                return data[:m.end()] + b"\n" + block(page, copy).rstrip(b"\n") + data[m.end():]
        return data
    _rewrite(page, fn)
    return nid


def restack(page, obj_id, where):
    """where: 'top' (sopra gli altri oggetti, sempre sotto il testo) o 'bottom'."""
    def fn(data, matches):
        target = next(((m, p) for m, p in matches if int(p.get("Id", -1)) == obj_id), None)
        if target is None or len(matches) < 2:
            return data
        m = target[0]
        chunk = data[m.start():m.end()]
        rest = data[:m.start()] + data[m.end():]
        others = [x for x, _ in matches if x is not m]
        if where == "bottom":
            pos = others[0].start()
            pos -= m.end() - m.start() if pos > m.start() else 0
        else:
            pos = others[-1].end()
            pos -= m.end() - m.start() if pos > m.start() else 0
        return rest[:pos] + b"\n" + chunk + b"\n" + rest[pos:]
    _rewrite(page, fn)


def moved(o, dx, dy):
    if o["K"] == "line":
        return dict(X1=o["X1"] + dx, Y1=o["Y1"] + dy, X2=o["X2"] + dx, Y2=o["Y2"] + dy)
    return dict(X=o["X"] + dx, Y=o["Y"] + dy)


def image_resource(page, data):
    """Registra l'immagine (PNG/JPEG) tra le risorse della pagina e ritorna il nome da usare con Do.

    insert_image aggiunge anche il disegno: il chiamante ricostruisce poi il contenuto della pagina."""
    xref = page.insert_image(page.rect, stream=data)
    for item in page.get_images(full=True):
        if item[0] == xref:
            return item[7]
    raise RuntimeError("Immagine non registrata")


def new_id(page):
    return max((o["Id"] for o in list_objects(page)), default=0) + 1
