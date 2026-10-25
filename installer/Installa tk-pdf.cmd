@echo off
title Installazione tk-pdf
cd /d "%~dp0"
if not exist "%~dp0app\python\tk-pdf.exe" goto notextracted
if not exist "%~dp0app\run.py" goto notextracted
start "" "%~dp0app\python\tk-pdf.exe" "%~dp0app\run.py" --install-zip
exit /b 0

:notextracted
echo.
echo   Prima di installare devi estrarre TUTTO lo ZIP:
echo.
echo   1. tasto destro sul file ZIP  ^>  Estrai tutto...
echo   2. apri la cartella estratta
echo   3. doppio clic su "Installa tk-pdf"
echo.
pause
exit /b 1
