"""Riconoscimento del testo (OCR) con i motori del sistema: Windows.Media.Ocr e Apple Vision.

Niente Tesseract: su Windows servirebbero exe non firmati (bloccati da Smart App Control).
Su Windows l'OCR gira in PowerShell (firmato Microsoft) con un solo avvio per tutte le pagine."""
import json
import os
import subprocess
import sys
import tempfile

from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage
from PySide6.QtCore import Qt

from tkpdf.util import app_data_dir

MIN_SIDE = 1800  # le immagini piccole si ingrandiscono: l'OCR legge meglio

_PS_SCRIPT = r"""
param([string]$InList, [string]$OutFile)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
})[0]
function Await($op, [Type]$type) {
    $task = $asTask.MakeGenericMethod($type).Invoke($null, @($op))
    $null = $task.Wait(-1)
    $task.Result
}
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType = WindowsRuntime]
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if ($engine -eq $null) {
    $lang = [Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages | Select-Object -First 1
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($lang)
}
$pages = @()
foreach ($path in [IO.File]::ReadAllLines($InList, [Text.Encoding]::UTF8)) {
    if (-not $path) { continue }
    $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($path)) ([Windows.Storage.StorageFile])
    $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
    $lines = @()
    foreach ($l in $result.Lines) {
        $words = @()
        foreach ($w in $l.Words) {
            $r = $w.BoundingRect
            $words += ,@($w.Text, $r.X, $r.Y, $r.Width, $r.Height)
        }
        $lines += ,@($words)
    }
    $stream.Dispose()
    $pages += ,@($lines)
}
[IO.File]::WriteAllText($OutFile, (ConvertTo-Json -InputObject @($pages) -Depth 8 -Compress), (New-Object Text.UTF8Encoding($false)))
"""


def available():
    if sys.platform == "win32":
        return os.path.exists(_powershell())
    if sys.platform == "darwin":
        try:
            import importlib
            importlib.import_module("Vision")
            return True
        except Exception:
            return False
    return False


def _powershell():
    return os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "WindowsPowerShell", "v1.0",
                        "powershell.exe")


def _prepare(img):
    """Immagine RGB ingrandita se piccola; ritorna (immagine, fattore)."""
    img = img.convertToFormat(QImage.Format.Format_RGB32)
    side = max(img.width(), img.height())
    k = 1.0
    if side < MIN_SIDE:
        k = MIN_SIDE / side
        img = img.scaled(round(img.width() * k), round(img.height() * k), Qt.AspectRatioMode.IgnoreAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    elif side > 9000:
        k = 9000 / side
        img = img.scaled(round(img.width() * k), round(img.height() * k), Qt.AspectRatioMode.IgnoreAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    return img, k


def recognize(images):
    """Per ogni QImage ritorna le righe: [[(testo, QRectF in pixel dell'immagine originale), ...], ...]."""
    if not images:
        return []
    prepared = [_prepare(im) for im in images]
    if sys.platform == "win32":
        raw = _recognize_windows([p[0] for p in prepared])
    elif sys.platform == "darwin":
        raw = [_recognize_mac(p[0]) for p in prepared]
    else:
        raise RuntimeError("Riconoscimento del testo non disponibile su questo sistema")
    out = []
    for (_, k), lines in zip(prepared, raw):
        page = []
        for words in lines:
            items = [(t, QRectF(x / k, y / k, w / k, h / k)) for t, x, y, w, h in words if str(t).strip()]
            if items:
                page.append(items)
        out.append(page)
    return out


def _recognize_windows(images):
    work = tempfile.mkdtemp(prefix="tkpdf-ocr-")
    try:
        paths = []
        for i, im in enumerate(images):
            p = os.path.join(work, f"p{i}.png")
            if not im.save(p, "PNG"):
                raise RuntimeError("Impossibile preparare l'immagine per il riconoscimento del testo")
            paths.append(p)
        script = os.path.join(app_data_dir(), "ocr.ps1")
        with open(script, "w", encoding="utf-8-sig") as fh:
            fh.write(_PS_SCRIPT)
        in_list = os.path.join(work, "pagine.txt")
        with open(in_list, "w", encoding="utf-8") as fh:
            fh.write("\n".join(paths))
        out_file = os.path.join(work, "testo.json")
        proc = subprocess.run(
            [_powershell(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", script,
             in_list, out_file],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=0x08000000, timeout=60 + 30 * len(images))  # CREATE_NO_WINDOW
        if not os.path.exists(out_file):
            err = (proc.stderr or proc.stdout or b"").decode("utf-8", "replace").strip()
            raise RuntimeError(f"Riconoscimento del testo non riuscito:\n{err[-600:]}")
        with open(out_file, encoding="utf-8") as fh:
            data = json.load(fh)
        # ConvertTo-Json appiattisce gli array con un solo elemento: si normalizza
        pages = _as_list(data)
        return [[[_word(w) for w in _as_list(line) if _word(w)] for line in _as_list(page)] for page in pages]
    finally:
        for name in os.listdir(work):
            try:
                os.remove(os.path.join(work, name))
            except OSError:
                pass
        try:
            os.rmdir(work)
        except OSError:
            pass


def _as_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _word(w):
    if isinstance(w, list) and len(w) == 5 and isinstance(w[0], str):
        return (w[0], float(w[1]), float(w[2]), float(w[3]), float(w[4]))
    return None


def _recognize_mac(img):
    import Vision
    from Foundation import NSData

    from tkpdf.util import qimage_to_png_bytes
    png = qimage_to_png_bytes(img)
    data = NSData.dataWithBytes_length_(png, len(png))
    handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(data, None)
    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(0)  # accurato
    request.setUsesLanguageCorrection_(True)
    try:
        request.setRecognitionLanguages_(["it-IT", "en-US"])
    except Exception:
        pass
    ok = handler.performRequests_error_([request], None)
    if isinstance(ok, tuple):
        ok = ok[0]
    if not ok:
        raise RuntimeError("Riconoscimento del testo non riuscito")
    W, H = img.width(), img.height()
    lines = []
    for obs in request.results() or []:
        cands = obs.topCandidates_(1)
        if not cands:
            continue
        text = str(cands[0].string())
        box = obs.boundingBox()  # normalizzato, origine in basso a sinistra
        x, y = box.origin.x * W, (1 - box.origin.y - box.size.height) * H
        lines.append([(text, x, y, box.size.width * W, box.size.height * H)])
    return lines
