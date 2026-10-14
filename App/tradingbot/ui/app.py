"""App-Shell: EINE GUI, vier Seiten (GUI_KONZEPT.md) — jede Seite auch
einzeln startbar.

- Seite 1  Daten          — Datenlage des Hubs, Abruf-Knöpfe
- Seite 2  TradeBot       — Live-/Paper-Betrieb (Profil "live")
- Seite 3  ValueScreener  — Screening-Registry (löst MarketScreener-GUI ab)
- Seite 4  Backtest       — fester Zeitraum + Zufallsfenster (Profil "test")

Start: `uv run bot_gui.py` (alle Seiten) oder die Einzelstarter
`gui_1_daten.py` … `gui_4_backtest.py` im Projektordner. Die Seiten sind
unabhängig voneinander (eigene Threads, gemeinsame Queue nur zur
Statusanzeige); gemeinsame Basis sind Daten-Hub und Einstellungs-Profile.

Alles Langlaufende läuft in Hintergrund-Threads; die Seiten kommunizieren
über eine gemeinsame Queue mit der GUI (app.queue → _poll_queue).
"""

from __future__ import annotations

import queue
import webbrowser

import tkinter as tk
from tkinter import messagebox, ttk

from ..config import PROJECT_ROOT, STRATEGIE_MD

# Seiten-Registry: key → (Tab-Titel, Modul, Klasse)
PAGES: dict[str, tuple[str, str, str]] = {
    "daten": ("  1 · Daten  ", "seite1_daten", "DataPage"),
    "tradebot": ("  2 · TradeBot  ", "seite2_tradebot", "TradeBotPage"),
    "valuescreener": ("  3 · ValueScreener  ", "seite3_valuescreener", "ScreenerPage"),
    "backtest": ("  4 · Backtest  ", "seite4_backtest", "BacktestPage"),
}


class BotApp:
    def __init__(self, root: tk.Tk, pages: list[str] | None = None):
        self.root = root
        wanted = [p for p in (pages or list(PAGES)) if p in PAGES]
        title = ("TradingBot — " + " · ".join(PAGES[p][0].strip().split(" · ")[1]
                                              for p in wanted))
        root.title(title)
        root.geometry("1280x800" if len(wanted) > 1 else "1150x760")
        self.queue: queue.Queue = queue.Queue()

        self._build_menu()

        notebook = ttk.Notebook(root)
        notebook.pack(fill="both", expand=True, padx=6, pady=6)

        # Seiten lazy importieren und nur die gewünschten bauen
        import importlib

        self.pages: dict[str, object] = {}
        for key in wanted:
            tab_title, module_name, class_name = PAGES[key]
            module = importlib.import_module(f".{module_name}", package=__package__)
            page = getattr(module, class_name)(notebook, self)
            self.pages[key] = page
            notebook.add(page, text=tab_title)
        if "tradebot" in self.pages and len(wanted) > 1:
            notebook.select(self.pages["tradebot"])

        self.status = tk.StringVar(value="Bereit.")
        ttk.Label(root, textvariable=self.status, padding=(8, 4)).pack(fill="x", side="bottom")

        self._poll_queue()

    # ---------------------------------------------------------------- Menü

    def _build_menu(self) -> None:
        menu = tk.Menu(self.root)
        help_ = tk.Menu(menu, tearoff=0)
        help_.add_command(label="Strategie-Methodik (STRATEGIE.md)",
                          command=lambda: webbrowser.open(STRATEGIE_MD.as_uri()))
        help_.add_command(label="GUI-Konzept (GUI_KONZEPT.md)",
                          command=lambda: webbrowser.open(
                              (PROJECT_ROOT / "GUI_KONZEPT.md").as_uri()))
        analyse = PROJECT_ROOT / "ANALYSE.md"
        if analyse.exists():
            help_.add_command(label="Screener-Methodik (ANALYSE.md)",
                              command=lambda: webbrowser.open(analyse.as_uri()))
        menu.add_cascade(label="Hilfe", menu=help_)
        self.root.config(menu=menu)

    # ---------------------------------------------------------------- Queue

    def set_status(self, message: str) -> None:
        self.status.set(str(message))

    def _page(self, key: str):
        return self.pages.get(key)

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "status":
                    self.set_status(payload)
                elif kind == "error":
                    self.set_status(str(payload))
                    messagebox.showerror("TradingBot", str(payload))
                elif kind == "tradebot_done" and self._page("tradebot"):
                    self._page("tradebot").on_cycle_done(payload)
                elif kind == "data_refreshed" and self._page("daten"):
                    self._page("daten").on_refreshed(payload)
                elif kind == "data_do_refresh" and self._page("daten"):
                    self._page("daten").refresh()
                elif kind == "screener_done" and self._page("valuescreener"):
                    self._page("valuescreener").on_done(payload)
                elif kind == "screener_history" and self._page("valuescreener"):
                    self._page("valuescreener").on_history(payload)
                elif kind == "backtest_done" and self._page("backtest"):
                    self._page("backtest").on_done(payload)
        except queue.Empty:
            pass
        self.root.after(150, self._poll_queue)


def main(pages: list[str] | str | None = None) -> None:
    """GUI starten. pages: None = alle Seiten; sonst Liste/String der Keys
    aus PAGES ("daten", "tradebot", "valuescreener", "backtest")."""
    if isinstance(pages, str):
        pages = [pages]
    root = tk.Tk()
    try:
        ttk.Style().theme_use("clam")
    except tk.TclError:
        pass
    BotApp(root, pages)
    root.mainloop()
