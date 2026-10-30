# Crea l'installer autonomo dist\tk-pdf-setup-<versione>.exe
# Contiene: runtime Python ridotto + PySide6 (solo moduli usati) + PyMuPDF + tk-pdf + lanciatore + licenze\.
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

$version = (Select-String -Path 'tkpdf\__init__.py' -Pattern 'VERSION = "(.+)"').Matches[0].Groups[1].Value
$csc = "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
$stageRoot = Join-Path $env:TEMP 'tkpdf-stage'
$stage = Join-Path $stageRoot 'app'
$dist = Join-Path $root 'dist'
Write-Host "== tk-pdf ${version} - preparazione file"

if (Test-Path $stageRoot) { Remove-Item $stageRoot -Recurse -Force }
New-Item -ItemType Directory -Force $stage | Out-Null
New-Item -ItemType Directory -Force $dist | Out-Null

function Robo($src, $dst, [string[]]$extra) {
    & robocopy $src $dst /E /NFL /NDL /NJH /NJS /NP @extra | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy fallito ($LASTEXITCODE): $src" }
}

# --- runtime Python (interprete di base del venv)
$homeLine = Get-Content '.venv\pyvenv.cfg' | Where-Object { $_ -match '^home\s*=' }
$pyHome = ($homeLine -replace '^home\s*=\s*', '').Trim()
$py = Join-Path $stage 'python'
Robo $pyHome $py @('/XD', 'test', 'tests', 'idlelib', 'tkinter', 'turtledemo', 'tcl', 'include', 'libs', 'Scripts',
                   'ensurepip', 'lib2to3', 'site-packages', '__phello__', 'pydoc_data',
                   '/XF', '*.pdb', '_tkinter.pyd', 'tcl*.dll', 'tk*.dll', 'EXTERNALLY-MANAGED')
# tk-pdf.exe = copia identica di pythonw.exe: in Gestione attività si vede il nome dell'app e, essendo lo stesso file,
# Smart App Control lo accetta come pythonw.exe (NON modificarne icona o dati: cambierebbe il file).
# pythonw.exe resta: gli aggiornamenti dalle versioni <= 1.0.15 lo cercano e lo riavviano.
Copy-Item "$py\pythonw.exe" "$py\tk-pdf.exe"
if ((Get-FileHash "$py\pythonw.exe").Hash -ne (Get-FileHash "$py\tk-pdf.exe").Hash) { throw 'tk-pdf.exe diverso da pythonw.exe' }

# --- librerie
$sp = '.venv\Lib\site-packages'
$dsp = Join-Path $py 'Lib\site-packages'
New-Item -ItemType Directory -Force $dsp | Out-Null
Robo "$sp\pymupdf" "$dsp\pymupdf" @()
Get-ChildItem $sp -Directory -Filter 'pymupdf-*.dist-info' | ForEach-Object { Robo $_.FullName "$dsp\$($_.Name)" @() }
Robo "$sp\shiboken6" "$dsp\shiboken6" @()
Robo "$sp\certifi" "$dsp\certifi" @()

$ps = "$sp\PySide6"
$dps = "$dsp\PySide6"
New-Item -ItemType Directory -Force $dps | Out-Null
$files = @('pyside6.abi3.dll', 'QtCore.pyd', 'QtGui.pyd', 'QtWidgets.pyd', 'QtPrintSupport.pyd',
           'Qt6Core.dll', 'Qt6Gui.dll', 'Qt6Widgets.dll', 'Qt6PrintSupport.dll', 'Qt6Svg.dll')
Get-ChildItem $ps -File | Where-Object {
    $_.Extension -eq '.py' -or $files -contains $_.Name -or $_.Name -match '^(msvcp140|vcruntime140|concrt140)'
} | ForEach-Object { Copy-Item $_.FullName $dps }
foreach ($plug in @('platforms\qwindows.dll', 'styles\qmodernwindowsstyle.dll', 'iconengines\qsvgicon.dll',
                    'imageformats\qjpeg.dll', 'imageformats\qgif.dll', 'imageformats\qico.dll',
                    'imageformats\qsvg.dll', 'imageformats\qwebp.dll', 'imageformats\qtiff.dll')) {
    $srcp = Join-Path "$ps\plugins" $plug
    if (Test-Path $srcp) {
        $dstp = Join-Path "$dps\plugins" $plug
        New-Item -ItemType Directory -Force (Split-Path $dstp) | Out-Null
        Copy-Item $srcp $dstp
    }
}
New-Item -ItemType Directory -Force "$dps\translations" | Out-Null
Copy-Item "$ps\translations\qtbase_it.qm" "$dps\translations\" -ErrorAction SilentlyContinue

# --- applicazione
Robo 'tkpdf' "$stage\tkpdf" @('/XD', '__pycache__')
Robo 'assets' "$stage\assets" @()
Copy-Item 'run.py' $stage

# --- testi delle licenze accanto a run.py: AGPL di tk-pdf + componenti inclusi (Informazioni → Licenze)
Robo 'licenze' "$stage\licenze" @()
Copy-Item "$pyHome\LICENSE.txt" "$stage\licenze\Python-LICENSE.txt"   # Python + librerie incluse nel runtime
$verCode = "import sys,ssl,sqlite3,importlib.metadata as m`nv=lambda n:m.version(n)`nwith open(sys.argv[1],'a',encoding='utf-8') as f:`n  f.write('\nVERSIONI ESATTE IN QUESTO PACCHETTO (Windows)\n')`n  f.write('Python %s\n%s\nSQLite %s\n' % (sys.version.split()[0], ssl.OPENSSL_VERSION, sqlite3.sqlite_version))`n  for n in ('pyside6_essentials','shiboken6','pymupdf','certifi'): f.write('%s %s\n' % (n, v(n)))"
# Python di base + librerie del venv: Smart App Control blocca .venv\Scripts\python.exe (lanciatore non firmato)
$env:PYTHONPATH = (Resolve-Path '.venv\Lib\site-packages').Path
& "$pyHome\python.exe" -c $verCode "$stage\licenze\COMPONENTI.txt"
Remove-Item Env:PYTHONPATH
if ($LASTEXITCODE -ne 0) { throw 'Versioni dei componenti non scritte in COMPONENTI.txt' }

# --- precompila i .py (avvio più rapido)
& "$py\python.exe" -m compileall -q "$py\Lib" 2>$null | Out-Null
# il codice di tk-pdf va nel pacchetto SOLO compilato: .pyc accanto ai moduli (-b), sorgenti tolti
# (Python importa i .pyc anche senza il .py; run.py resta perché è il punto d'avvio dei collegamenti)
& "$py\python.exe" -m compileall -q -b "$stage\tkpdf" 2>$null | Out-Null
Get-ChildItem "$stage\tkpdf" -Recurse -File -Filter '*.py' | Remove-Item -Force
Get-ChildItem "$stage\tkpdf" -Recurse -Directory -Filter '__pycache__' | Remove-Item -Recurse -Force
if (Get-ChildItem "$stage\tkpdf" -Recurse -File -Filter '*.py') { throw 'Nel pacchetto sono rimasti dei sorgenti .py' }
# python.exe (console) all'app non serve più dopo la precompilazione
Remove-Item "$py\python.exe"

# --- verifica: avvio reale dal runtime ridotto
$shot = Join-Path $stageRoot 'selftest.png'
$p = Start-Process "$py\tk-pdf.exe" -ArgumentList "`"$stage\run.py`"", "`"$root\tests\prova.pdf`"", '--selftest', "`"$shot`"" -PassThru
if (-not $p.WaitForExit(60000)) { Stop-Process -Id $p.Id -Force; throw 'Selftest in timeout' }
if (-not (Test-Path $shot)) { throw 'Selftest fallito: il runtime ridotto non avvia tk-pdf' }
Remove-Item $shot
Write-Host "   selftest runtime OK"

# --- verifica: riconoscimento del testo (OCR di Windows via PowerShell) dal runtime ridotto
$ocrOut = Join-Path $stageRoot 'ocr.txt'
$p = Start-Process "$py\tk-pdf.exe" -ArgumentList "`"$stage\run.py`"", '--ocr-test', "`"$root\tests\ocr.png`"", "`"$ocrOut`"" -PassThru
if (-not $p.WaitForExit(90000)) { Stop-Process -Id $p.Id -Force; throw 'Test OCR in timeout' }
$ocrText = if (Test-Path $ocrOut) { Get-Content $ocrOut -Raw -Encoding UTF8 } else { '' }
if ($ocrText -notmatch 'OCR') { throw "Test OCR fallito: $ocrText" }
Remove-Item $ocrOut
Write-Host "   test OCR OK"

# --- pacchetto
$payload = Join-Path $stageRoot 'payload.zip'
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::CreateFromDirectory($stage, $payload, [System.IO.Compression.CompressionLevel]::Optimal, $false)
$sizeKb = [int]((Get-ChildItem $stage -Recurse -File | Measure-Object Length -Sum).Sum / 1KB)

# --- pacchetto di aggiornamento Windows (lo estrae tar.exe di sistema: percorsi con /)
$updateZip = Join-Path $dist "tk-pdf-$version-windows.zip"
$zipCode = "import os,sys,zipfile`nsrc,dst=sys.argv[1],sys.argv[2]`nwith zipfile.ZipFile(dst,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:`n  for d,_,fs in os.walk(src):`n    for f in fs:`n      p=os.path.join(d,f); z.write(p, os.path.relpath(p,src).replace(os.sep,'/'))"
& "$pyHome\python.exe" -c $zipCode $stage $updateZip
if ($LASTEXITCODE -ne 0) { throw 'Creazione ZIP di aggiornamento fallita' }

# --- ZIP di installazione senza exe (niente blocchi di antivirus / Smart App Control)
$installRoot = Join-Path $stageRoot 'installa'
$installDir = Join-Path $installRoot "tk-pdf-$version"  # cartella che vede chi estrae lo ZIP
New-Item -ItemType Directory -Force $installDir | Out-Null
Robo $stage "$installDir\app" @()
$cmdText = Get-Content "$PSScriptRoot\Installa tk-pdf.cmd" -Raw
[IO.File]::WriteAllText("$installDir\Installa tk-pdf.cmd", ($cmdText -replace "`r?`n", "`r`n"), [Text.Encoding]::ASCII)
$readme = Get-Content "$PSScriptRoot\Leggimi-zip.txt" -Raw -Encoding UTF8
[IO.File]::WriteAllText("$installDir\Leggimi.txt", ($readme -replace "`r?`n", "`r`n"), (New-Object Text.UTF8Encoding($true)))
$installZip = Join-Path $dist "tk-pdf-$version-installa.zip"
& "$pyHome\python.exe" -c $zipCode $installRoot $installZip
if ($LASTEXITCODE -ne 0) { throw 'Creazione ZIP di installazione fallita' }

$setupSrc = Get-Content "$PSScriptRoot\setup.cs" -Raw -Encoding UTF8
$setupSrc = $setupSrc.Replace('@@VERSION@@', $version).Replace('@@SIZEKB@@', "$sizeKb")
$genSrc = Join-Path $stageRoot 'setup.cs'
Set-Content $genSrc $setupSrc -Encoding utf8

$out = Join-Path $dist "tk-pdf-setup-$version.exe"
& $csc /nologo /optimize+ /target:winexe /platform:anycpu `
    /win32icon:"$root\assets\tk-pdf.ico" `
    /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.Core.dll `
    /reference:System.IO.Compression.dll /reference:System.IO.Compression.FileSystem.dll `
    /resource:"$payload",payload.zip /out:"$out" $genSrc
if ($LASTEXITCODE -ne 0) { throw 'Compilazione installer fallita' }

Remove-Item $stageRoot -Recurse -Force
$mb = [math]::Round((Get-Item $out).Length / 1MB, 1)
Write-Host "== Creato $out ($mb MB, installato $([math]::Round($sizeKb/1024)) MB)"
