"""Genera le icone: assets/tk-pdf.ico (Windows), assets/tk-pdf.png e, con --iconset, assets/tk-pdf.iconset (macOS)."""
import os
import struct
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from tkpdf.icon import render_icon
from tkpdf.util import qimage_to_png_bytes

ROOT = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(ROOT, "assets")
os.makedirs(ASSETS, exist_ok=True)

# ICO multi-risoluzione (PNG incapsulati)
sizes = [16, 24, 32, 48, 64, 128, 256]
pngs = [qimage_to_png_bytes(render_icon(s)) for s in sizes]
header = struct.pack("<HHH", 0, 1, len(sizes))
offset = 6 + 16 * len(sizes)
entries = b""
data = b""
for s, png in zip(sizes, pngs):
    entries += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(png), offset + len(data))
    data += png
with open(os.path.join(ASSETS, "tk-pdf.ico"), "wb") as fh:
    fh.write(header + entries + data)
render_icon(256).save(os.path.join(ASSETS, "tk-pdf.png"))

if "--iconset" in sys.argv:
    iconset = os.path.join(ASSETS, "tk-pdf.iconset")
    os.makedirs(iconset, exist_ok=True)
    for base in (16, 32, 128, 256, 512):
        render_icon(base).save(os.path.join(iconset, f"icon_{base}x{base}.png"))
        render_icon(base * 2).save(os.path.join(iconset, f"icon_{base}x{base}@2x.png"))
print("icone generate")
