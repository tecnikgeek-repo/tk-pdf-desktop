"""Crea tests/ocr-it.png e tests/ocr-it.json: immagine di prova per l'OCR (accenti, prezzi con l'euro) e posizioni
attese delle parole (pixel dell'immagine). Serve Pillow e il font Arial (creata su Windows; il risultato è nel repo).
Uso: python tests/crea_ocr_it.py"""
import json
import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
FONT = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "arial.ttf")
RIGHE = [  # (testo a sinistra, prezzo nella colonna di destra)
    ("Listino prezzi bar Partenope", ""),
    ("Caffè espresso", "1,20 €"),
    ("Cornetto alla crema", "12,50 €"),
    ("Spremuta d'arancia", "3,00 €"),
    ("Perché è già così buono? Più qualità!", ""),
]
X_TESTO, X_PREZZO, Y0, PASSO, SIZE = 60, 1000, 50, 100, 44

img = Image.new("RGB", (1400, Y0 * 2 + PASSO * len(RIGHE)), "white")
draw = ImageDraw.Draw(img)
font = ImageFont.truetype(FONT, SIZE)
parole = []


def scrivi(x, y, testo):
    draw.text((x, y), testo, font=font, fill=(17, 24, 39))
    pos = 0
    for parola in testo.split(" "):
        start = testo.index(parola, pos)
        pos = start + len(parola)
        x0 = x + draw.textlength(testo[:start], font=font)
        box = draw.textbbox((x0, y), parola, font=font)
        parole.append({"testo": parola, "x": round(box[0]), "y": round(box[1]), "w": round(box[2] - box[0]),
                       "h": round(box[3] - box[1])})


for i, (testo, prezzo) in enumerate(RIGHE):
    y = Y0 + i * PASSO
    scrivi(X_TESTO, y, testo)
    if prezzo:
        scrivi(X_PREZZO, y, prezzo)

img.save(os.path.join(HERE, "ocr-it.png"), optimize=True)
with open(os.path.join(HERE, "ocr-it.json"), "w", encoding="utf-8") as fh:
    json.dump({"larghezza": img.width, "altezza": img.height, "parole": parole}, fh, ensure_ascii=False, indent=1)
print(len(parole), "parole")
