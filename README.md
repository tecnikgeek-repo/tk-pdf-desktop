<!-- README generato da Dropbox/CLAUDE/dev/agpl-rollout/readme/genera_readme.py: modificare lì -->
<div align="center">

<img src="docs/vetrina.png" alt="tk-pdf: Leggi, annota, firma e modifica i PDF. Senza abbonamenti." width="100%">

<br><br>

<a href="https://pietrodefilippis.it/scarica-programma/tk-pdf/windows/"><img alt="Scarica per Windows" src="https://img.shields.io/badge/%E2%AC%87%20%20Windows-scarica%20gratis-0078D4?style=for-the-badge&logo=windows&logoColor=white"></a> &nbsp; <a href="https://pietrodefilippis.it/scarica-programma/tk-pdf/mac/"><img alt="Scarica per macOS" src="https://img.shields.io/badge/%E2%AC%87%20%20macOS-scarica%20gratis-111111?style=for-the-badge&logo=apple&logoColor=white"></a> &nbsp; <a href="https://pietrodefilippis.it/donazione/"><img alt="Offrimi un caffè" src="https://img.shields.io/badge/%E2%98%95%20%20Offrimi%20un%20caff%C3%A8-facoltativo-f59e0b?style=for-the-badge"></a>

<br><br>

<a href="COPYING"><img alt="Licenza AGPL-3.0" src="https://img.shields.io/badge/licenza-AGPL--3.0-16a34a?style=for-the-badge"></a> <img alt="Windows" src="https://img.shields.io/badge/Windows-10%20%C2%B7%2011-0078D4?style=for-the-badge&logo=windows&logoColor=white"> <img alt="macOS" src="https://img.shields.io/badge/macOS-Intel%20%C2%B7%20Apple%20Silicon-111111?style=for-the-badge&logo=apple&logoColor=white"> <img alt="Versione" src="https://img.shields.io/github/v/tag/tecnikgeek-repo/tk-pdf-desktop?label=versione&style=for-the-badge&color=e11d48"> <img alt="Zero pubblicità" src="https://img.shields.io/badge/pubblicit%C3%A0-zero-0f172a?style=for-the-badge">

<br>

### Leggi, annota, firma e modifica i PDF. Senza abbonamenti.

Un editor PDF completo per Windows, macOS e Linux: tutte le funzioni, gratis, per sempre.

</div>

---

## ✨ Cosa fa

<table>
<tr>
<td width="50%" valign="top">

### 📖&nbsp; Leggi e cerca
Miniature delle pagine, zoom, ricerca nel testo e stampa.

</td>
<td width="50%" valign="top">

### 🖍️&nbsp; Annota
Evidenzia, sottolinea, scrivi note, disegna a mano libera, aggiungi frecce, forme e timbri.

</td>
</tr>
<tr>
<td width="50%" valign="top">

### ✍️&nbsp; Firma e moduli
Compila i moduli, aggiungi una firma grafica disegnata o da immagine, spunte e caselle di testo.

</td>
<td width="50%" valign="top">

### ✏️&nbsp; Modifica il testo
Correggi le parole direttamente nel PDF, sposta righe e oggetti, cancella per davvero con il bianchetto.

</td>
</tr>
<tr>
<td width="50%" valign="top">

### 📑&nbsp; Pagine
Riordina, ruota, elimina, estrai, dividi e unisci più PDF in uno.

</td>
<td width="50%" valign="top">

### 🔐&nbsp; Proteggi e comprimi
Password con cifratura AES-256, compressione in un file nuovo, foto di documenti trasformate in PDF con il testo riconosciuto.

</td>
</tr>
</table>

## 🖥️ Com'è fatto

<div align="center">
<img src="docs/screenshot.png" alt="tk-pdf in funzione" width="100%">
</div>

## 📱 Anche sul telefono

**tk-pdf** c'è anche per Android, gratis e libera come questo programma:
[tk-pdf-app](https://github.com/tecnikgeek-repo/tk-pdf-app).

<a href="https://github.com/tecnikgeek-repo/tk-pdf-app"><img alt="tk-pdf per Android" src="https://img.shields.io/badge/%F0%9F%93%B1%20%20tk--pdf-per%20Android-e11d48?style=for-the-badge&logo=android&logoColor=white"></a>

## 🔒 I tuoi dati

tk-pdf lavora tutto sul tuo computer: i PDF non vengono mai caricati su internet, nemmeno per il riconoscimento del testo (usa quello di Windows o di macOS; su Linux è incluso nel programma).

| Resta sul tuo computer | Va in rete (e perché) |
|---|---|
| I tuoi PDF e le modifiche | Controllo degli aggiornamenti su pietrodefilippis.it |
| Le firme che salvi | Statistiche anonime, solo se le accetti |
| Il riconoscimento del testo (OCR) | Google Fonts, solo se lo consenti, quando riscrivi un testo con un carattere che manca |

Nessuna pubblicità, nessun account da creare. Le statistiche anonime partono **solo se le accetti** al primo avvio
(si cambiano quando vuoi). Gli aggiornamenti sono **firmati digitalmente**: il programma installa solo quelli
pubblicati dall'autore.

## 📥 Installazione

- **Windows 10 / 11** — scarica l'installer `.exe` e avvialo. Non servono i permessi di amministratore.
- **macOS** (Intel o Apple Silicon) — apri il `.dmg` e trascina l'app in *Applicazioni*. Al primo avvio: clic destro sull'app → *Apri*.
- **Linux** (Ubuntu 22.04 o più recente, x86_64) — scarica il file `.AppImage`, rendilo eseguibile (*Proprietà* → *Esegui come programma*) e aprilo: si aggiunge da solo al menu delle applicazioni.

Gli aggiornamenti arrivano da soli: quando esce una versione nuova il programma te lo propone.

<details>
<summary><b>🛠️ Avviarlo dal codice sorgente</b></summary>

<br>

Serve **Python 3.13**.

```bash
python -m venv .venv
.venv\Scripts\python -m pip install "pyside6-essentials==6.11.*" "pymupdf==1.28.*" certifi
.venv\Scripts\python run.py
```

Su macOS: `source .venv/bin/activate`, poi `pip install "pyside6-essentials==6.11.*" "pymupdf==1.28.*" certifi pyobjc-core pyobjc-framework-Vision` e `python run.py`.

Pacchetti: Windows con `installer\build.ps1`, macOS con `mac/build_mac.sh`, Linux con `linux/build_linux.sh` (AppImage, Tesseract incluso).

</details>

## 📜 Licenza

**tk-pdf** è software libero: © 2026 Pietro De Filippis (TecnikGeek), licenza
**[GNU Affero General Public License v3.0](COPYING)** o successiva. Puoi usarlo, studiarlo, modificarlo e
condividerlo; è fornito **così com'è, senza alcuna garanzia**. I testi delle licenze dei componenti inclusi
(PyMuPDF/MuPDF, Qt/PySide6, Python, certifi) sono nella cartella [`licenze/`](licenze/) e nel programma, in *Informazioni → Licenze e codice
sorgente*.

> Il nome **tk-pdf** e il logo non sono coperti dalla licenza (AGPL, sezione 7): una versione modificata deve
> avere un nome e un logo diversi.

---

<div align="center">

**Ti è utile?** Tutte le funzioni sono gratis per tutti. Se vuoi, un caffè aiuta a migliorarlo e a crearne altri.

<a href="https://pietrodefilippis.it/donazione/"><img alt="Offrimi un caffè" src="https://img.shields.io/badge/%E2%98%95%20%20Offrimi%20un%20caff%C3%A8-pietrodefilippis.it-f59e0b?style=for-the-badge"></a>

<sub>Creato da <a href="https://pietrodefilippis.it">Pietro De Filippis · TecnikGeek</a> — Webmaster & UX/UI Designer</sub>

</div>
