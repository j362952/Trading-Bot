@echo off
cd /d "%~dp0"
echo Starte MarketScreener (erster Start laedt Abhaengigkeiten) ...
uv run screener_gui.py
pause
