# Pubblica una versione di tk-pdf per Windows, Mac e Linux: gli utenti la ricevono con l'aggiornamento automatico.
# Uso:  powershell -ExecutionPolicy Bypass -File release\publish.ps1 -Notes "Novità 1|Novità 2"
# Prerequisiti: VERSION alzata in tkpdf\__init__.py, commit fatto (lo script fa push e attende le build Mac e Linux).
# -SkipMac: solo Windows (niente build su GitHub, manifest senza chiavi mac/linux).
param(
    [Parameter(Mandatory = $true)][string]$Notes,
    [switch]$SkipMac
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

# con -File PowerShell unisce più valori in una stringa: le novità si separano con |
$noteList = @($Notes -split '\|' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
$version = (Select-String -Path 'tkpdf\__init__.py' -Pattern 'VERSION = "(.+)"').Matches[0].Groups[1].Value
$sshConfig = 'C:\Users\TecnikGeek\Dropbox\CLAUDE\fleet\ssh-config'
$remoteDir = 'public_html/updates/tk-pdf'
$baseUrl = 'https://pietrodefilippis.it/updates/tk-pdf'
$dropbox = 'C:\Users\TecnikGeek\Dropbox\CLAUDE\tk-software\tk-pdf'
Write-Host "== Pubblicazione tk-pdf $version"

# --- sicurezza: la versione non deve essere già pubblicata
try {
    $current = Invoke-RestMethod "https://pietrodefilippis.it/updates/tk-pdf.json?t=$([DateTime]::Now.Ticks)" -TimeoutSec 15
    if ([version]$current.version -ge [version]$version) {
        throw "Sul server c'è già la versione $($current.version): alza VERSION in tkpdf\__init__.py"
    }
} catch [System.Net.WebException] { Write-Host "   nessun manifest precedente (prima pubblicazione)" }

# --- installer Windows
$winExe = "dist\tk-pdf-setup-$version.exe"
if (-not (Test-Path $winExe) -or -not (Test-Path "dist\tk-pdf-$version-windows.zip")) {
    & powershell -NoProfile -ExecutionPolicy Bypass -File installer\build.ps1
    if ($LASTEXITCODE -ne 0) { throw 'Build Windows fallita' }
}

# --- dmg macOS dalla build GitHub del commit corrente
$winZip = "dist\tk-pdf-$version-windows.zip"
if (-not (Test-Path $winZip)) { throw "Manca ${winZip} - rilancia installer\build.ps1" }
# 'windows' = installer exe (nuove installazioni e versioni <= 1.0.5), 'windows-zip' = aggiornamento senza exe
$winInstall = "dist\tk-pdf-$version-installa.zip"
if (-not (Test-Path $winInstall)) { throw "Manca ${winInstall} - rilancia installer\build.ps1" }
# 'windows-install' = ZIP di installazione senza exe (per PC con antivirus o Smart App Control)
$assets = @(@{ key = 'windows'; file = (Resolve-Path $winExe).Path }, @{ key = 'windows-zip'; file = (Resolve-Path $winZip).Path }, @{ key = 'windows-install'; file = (Resolve-Path $winInstall).Path })
if (-not $SkipMac) {
    if (git status --porcelain) { throw 'Ci sono modifiche non committate: fai commit prima di pubblicare' }
    git push -q
    if ($LASTEXITCODE -ne 0) { throw 'git push non riuscito' }
    # tag della versione: è il «codice sorgente di questa versione» linkato da Informazioni → Licenze
    if (-not (git tag --list "v$version")) {
        git tag "v$version"
        git push -q origin "v$version"
        if ($LASTEXITCODE -ne 0) { throw "Invio del tag v$version non riuscito" }
    }
    # le build Mac e Linux non partono più da sole a ogni push: le avvio io, in parallelo, sul commit appena inviato
    $repo = 'tecnikgeek-repo/tk-pdf-desktop'
    $sha = (git rev-parse HEAD).Trim()
    foreach ($wf in 'build-mac.yml', 'build-linux.yml') {
        gh workflow run $wf --repo $repo --ref main
        if ($LASTEXITCODE -ne 0) { throw "Avvio di $wf su GitHub non riuscito" }
    }
    Start-Sleep -Seconds 5
    $runs = @{}
    foreach ($wf in 'build-mac.yml', 'build-linux.yml') {
        $runId = $null
        for ($i = 0; $i -lt 30 -and -not $runId; $i++) {
            $runId = gh run list --repo $repo --workflow $wf --commit $sha --json databaseId --jq '.[0].databaseId'
            if (-not $runId) { Start-Sleep -Seconds 5 }
        }
        if (-not $runId) { throw "$wf non trovata su GitHub" }
        $runs[$wf] = $runId
    }
    Write-Host "   attendo le build macOS e Linux del commit $($sha.Substring(0,7))…"
    foreach ($wf in $runs.Keys) {
        gh run watch $runs[$wf] --repo $repo --exit-status | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "$wf fallita: https://github.com/$repo/actions/runs/$($runs[$wf])" }
    }
    $macDir = "dist\mac-$version"
    if (Test-Path $macDir) { Remove-Item $macDir -Recurse -Force }
    gh run download $runs['build-mac.yml'] --repo $repo --dir $macDir --pattern 'tk-pdf-mac-*'
    foreach ($arch in 'arm64', 'x86_64') {
        $dmg = Get-ChildItem $macDir -Recurse -Filter "tk-pdf-$version-mac-$arch.dmg" | Select-Object -First 1
        if (-not $dmg) { throw "Manca il dmg $arch" }
        $assets += @{ key = "mac-$arch"; file = $dmg.FullName }
    }
    # Linux: la build mette l'AppImage nella release v<versione> del repo
    gh release download "v$version" --repo $repo --dir $macDir --pattern '*.AppImage' --clobber
    if ($LASTEXITCODE -ne 0) { throw "Download dell'AppImage dalla release v$version fallito" }
    $appImage = Join-Path $macDir "tk-pdf-$version-linux-x86_64.AppImage"
    if (-not (Test-Path $appImage)) { throw "Manca l'AppImage Linux" }
    $assets += @{ key = 'linux-x86_64'; file = (Resolve-Path $appImage).Path }
}

# --- manifest
$manifest = [ordered]@{
    name    = 'tk-pdf'
    version = $version
    date    = (Get-Date -Format 'dd/MM/yyyy')
    notes   = $noteList
}
foreach ($a in $assets) {
    $name = Split-Path $a.file -Leaf
    $manifest[$a.key] = [ordered]@{
        url    = "$baseUrl/$name"
        sha256 = (Get-FileHash $a.file -Algorithm SHA256).Hash.ToLower()
        size   = (Get-Item $a.file).Length
    }
}
$json = $manifest | ConvertTo-Json -Depth 5
$manifestFile = Join-Path $env:TEMP 'tk-pdf.json'
[IO.File]::WriteAllText($manifestFile, $json, (New-Object Text.UTF8Encoding($false)))
# --- firma del manifest: tk-pdf installa un aggiornamento solo se la firma è valida (slug = nome del manifest)
& python -I "C:\Users\TecnikGeek\Dropbox\CLAUDE\tk-software\librerie\firma_aggiornamenti.py" firma --slug tk-pdf $manifestFile
if ($LASTEXITCODE -ne 0) { throw 'Firma del manifest non riuscita: niente pubblicazione' }

# --- upload: prima i file, per ultimo il manifest (così nessuno scarica file mancanti)
Write-Host "   caricamento sul server…"
ssh -F $sshConfig pietrodefilippis "mkdir -p ~/$remoteDir/old"
foreach ($a in $assets) {
    scp -q -F $sshConfig $a.file "pietrodefilippis:~/$remoteDir/"
    if ($LASTEXITCODE -ne 0) { throw "Upload fallito: $($a.file)" }
}
scp -q -F $sshConfig $manifestFile "pietrodefilippis:~/public_html/updates/tk-pdf.json.new"
# archivia le versioni precedenti (tiene solo la penultima in old/), poi attiva il manifest
$names = ($assets | ForEach-Object { Split-Path $_.file -Leaf }) -join ' '
$remote = @'
cd ~/__DIR__ && rm -f old/* && for f in tk-pdf-*; do keep=0; for k in __NAMES__; do [ "$f" = "$k" ] && keep=1; done; [ $keep = 1 ] || mv -f "$f" old/; done && mv -f ~/public_html/updates/tk-pdf.json.new ~/public_html/updates/tk-pdf.json && ls -la ~/__DIR__ ~/__DIR__/old
'@
$remote = $remote.Replace('__DIR__', $remoteDir).Replace('__NAMES__', $names).Trim()
ssh -F $sshConfig pietrodefilippis $remote
if ($LASTEXITCODE -ne 0) { throw 'Attivazione del manifest sul server fallita' }

# --- verifica pubblica
$check = Invoke-RestMethod "https://pietrodefilippis.it/updates/tk-pdf.json?t=$([DateTime]::Now.Ticks)" -TimeoutSec 15
if ($check.version -ne $version) { throw "Il manifest pubblico non mostra $version" }
foreach ($a in $assets) {
    $url = $manifest[$a.key].url
    $resp = Invoke-WebRequest $url -Method Head -UseBasicParsing -TimeoutSec 30
    if ([int64]$resp.Headers['Content-Length'] -ne $manifest[$a.key].size) { throw "Dimensione errata online: $url" }
}
Write-Host "   manifest e file online verificati"

# --- cartella Dropbox
New-Item -ItemType Directory -Force "$dropbox\installer\Windows", "$dropbox\installer\Mac", "$dropbox\installer\Linux" | Out-Null
Get-ChildItem "$dropbox\installer" -Recurse -File | Where-Object { $_.Name -notlike "*$version*" } | Remove-Item -Force
foreach ($a in $assets) {
    if ($a.key -eq 'windows-zip') { continue }
    $sub = if ($a.key -like 'windows*') { 'Windows' } elseif ($a.key -like 'linux-*') { 'Linux' } else { 'Mac' }
    Copy-Item $a.file "$dropbox\installer\$sub\" -Force
}
& robocopy $root "$dropbox\progetto" /MIR /NFL /NDL /NJH /NJS /NP /XD .venv .venv-mac .venv-linux build dist __pycache__ .git `
    /XF tk-pdf.exe *.pyc lavoro.pdf risultato.pdf protetto.pdf selftest*.png diag.png | Out-Null

Write-Host "== tk-pdf $version pubblicato: gli utenti lo riceveranno al prossimo avvio (entro 12 ore)."
