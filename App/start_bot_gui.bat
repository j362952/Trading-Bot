@echo off
cd /d "%~dp0"
echo Starte TradingBot-GUI (erster Start laedt Abhaengigkeiten) ...
uv run bot_gui.py 2> start_gui_error.log
if errorlevel 1 (
    echo.
    echo FEHLER beim Start — Details in start_gui_error.log:
    echo ------------------------------------------------------
    type start_gui_error.log
    echo ------------------------------------------------------
)
pause
