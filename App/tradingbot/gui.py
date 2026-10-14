"""Kompatibilitäts-Einstieg: die GUI lebt jetzt in tradingbot/ui/
(eine GUI, vier Seiten — GUI_KONZEPT.md). bot_gui.py und bestehende
Aufrufer von tradingbot.gui:main funktionieren unverändert."""

from .ui.app import main

__all__ = ["main"]
