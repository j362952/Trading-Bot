@echo off
cd /d "%~dp0"
echo Datensammler startet (alle Kategorien, Universum aus dem Live-Profil) ...
uv run run_collect.py 2> collect_error.log
if errorlevel 1 (
    echo.
    echo FEHLER — Details in collect_error.log:
    type collect_error.log
)
pause
