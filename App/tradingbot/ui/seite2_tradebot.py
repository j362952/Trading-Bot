"""Seite 2 — TradeBot: alles zum Live-/Paper-Betrieb an EINEM Ort.

Aktienquelle + Strategie(n) mit Budgets, Trading-Schalter, Kontobalance +
Equity-Kurve, offene Positionen, Trade-Übersicht, Entscheidungs-Log.
Bot-Einstellungen (Broker, Zyklus, Risiko, Keys) hinter dem Zahnrad.
Konfigurations-Profil: "live".
"""

from __future__ import annotations

import threading
from datetime import datetime

import tkinter as tk
from tkinter import messagebox, ttk

from .. import botdb
from ..broker import make_broker
from ..config import load_settings, save_settings
from ..engine import TradingEngine
from .settings_dialog import SettingsDialog
from .source_panel import SourcePanel, StrategyPanel
from .widgets import EquityCanvas, make_tree


class TradeBotPage(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.settings = load_settings("live")
        self.worker: threading.Thread | None = None
        self.auto_stop = threading.Event()
        self.auto_thread: threading.Thread | None = None

        # ---------------- Kopfzeile: Status + Schalter + Zahnrad
        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")
        self.lbl_broker = ttk.Label(top, text="Broker: –", font=("", 10, "bold"))
        self.lbl_broker.pack(side="left", padx=(0, 16))
        self.lbl_equity = ttk.Label(top, text="Equity: –")
        self.lbl_equity.pack(side="left", padx=(0, 16))
        self.lbl_kill = ttk.Label(top, text="")
        self.lbl_kill.pack(side="left")
        ttk.Button(top, text="⚙ Einstellungen", command=self._open_settings).pack(side="right")

        btns = ttk.Frame(self, padding=(8, 0))
        btns.pack(fill="x")
        self.btn_cycle = ttk.Button(btns, text="Zyklus jetzt ausführen", command=self.run_cycle)
        self.btn_cycle.pack(side="left", padx=2)
        self.btn_auto = tk.Button(btns, text="▶ TRADING AKTIV SCHALTEN",
                                  font=("", 10, "bold"), command=self.toggle_auto,
                                  bg="#e8f5e9", activebackground="#c8e6c9")
        self.btn_auto.pack(side="left", padx=8)
        ttk.Button(btns, text="Aktualisieren", command=self.refresh).pack(side="left", padx=2)
        ttk.Button(btns, text="Kill-Switch zurücksetzen", command=self.reset_kill).pack(side="left", padx=12)
        ttk.Button(btns, text="Speichern", command=self.save).pack(side="left", padx=12)
        ttk.Button(btns, text="Paper-Konto zurücksetzen", command=self._reset_paper).pack(side="right")

        # ---------------- Hauptbereich: links Konfig, rechts Betrieb
        main = ttk.PanedWindow(self, orient="horizontal")
        main.pack(fill="both", expand=True, padx=8, pady=8)

        left = ttk.Frame(main)
        main.add(left, weight=1)
        self.source = SourcePanel(left, self.settings, status=self.app.set_status)
        self.source.pack(fill="x")
        self.strategies = StrategyPanel(left, self.settings)
        self.strategies.pack(fill="both", expand=True, pady=(8, 0))

        right = ttk.Frame(main)
        main.add(right, weight=3)

        eq_frame = ttk.LabelFrame(right, text="Equity-Kurve (Bot-DB)")
        eq_frame.pack(fill="x")
        self.equity_canvas = EquityCanvas(eq_frame)
        self.equity_canvas.pack(fill="x", padx=4, pady=4)

        panes = ttk.PanedWindow(right, orient="vertical")
        panes.pack(fill="both", expand=True, pady=(8, 0))

        pos_frame = ttk.LabelFrame(panes, text="Offene Positionen")
        self.pos_tree = make_tree(pos_frame, [("symbol", "Symbol", 90),
                                              ("qty", "Stück", 70),
                                              ("avg", "Ø Einstand", 90),
                                              ("stop", "Stop-Level", 90),
                                              ("owner", "Strategie", 140)],
                                  height=5)
        panes.add(pos_frame, weight=1)

        ord_frame = ttk.LabelFrame(panes, text="Trade-Übersicht (letzte Orders)")
        self.ord_tree = make_tree(ord_frame, [("time", "Zeit", 140),
                                              ("symbol", "Symbol", 80),
                                              ("qty", "Stück", 70),
                                              ("price", "Preis", 80),
                                              ("comm", "Gebühr", 70),
                                              ("reason", "Grund", 180)],
                                  height=5, stretch_col="reason")
        panes.add(ord_frame, weight=1)

        log_frame = ttk.LabelFrame(panes, text="Entscheidungs-Log (Bot-DB)")
        self.log_tree = make_tree(log_frame, [("time", "Zeit", 140),
                                              ("level", "Level", 55),
                                              ("msg", "Meldung", 640)],
                                  stretch_col="msg")
        panes.add(log_frame, weight=2)

        self.refresh()

        # Trading-Zustand überlebt Neustarts
        if self.settings.get("trading_active"):
            self.auto_stop.clear()
            self.auto_thread = threading.Thread(target=self._auto_loop, daemon=True)
            self.auto_thread.start()
            self._set_trading_button(True)
            self.app.set_status("Trading ist AKTIV (aus letzter Sitzung übernommen).")

    # ------------------------------------------------------------ Speichern

    def save(self) -> None:
        self.source.collect()
        self.strategies.collect()
        save_settings(self.settings, "live")
        self.app.set_status("Live-Profil gespeichert.")

    def _open_settings(self) -> None:
        SettingsDialog(self, self.settings,
                       on_save=lambda: (save_settings(self.settings, "live"),
                                        self.app.set_status("Einstellungen gespeichert."),
                                        self.refresh()),
                       profile="live", show_broker=True)

    # ------------------------------------------------------------- Anzeige

    def refresh(self) -> None:
        conn = botdb.connect()
        try:
            broker = self._make_broker(connect=False)
            self.lbl_broker.config(text=f"Broker: {broker.name}")
            if self.settings.get("broker", "paper") == "paper":
                self.lbl_equity.config(
                    text=f"Equity: {broker.equity():,.0f}   Cash: {broker.cash():,.0f}")
                stops = botdb.get_stops(conn)
                self.pos_tree.delete(*self.pos_tree.get_children())
                for p in broker.positions():
                    owner = botdb.get_meta(conn, f"owner_{p.symbol}") or ""
                    self.pos_tree.insert("", "end", values=(
                        p.symbol, f"{p.quantity:g}", f"{p.avg_price:.2f}",
                        f"{stops.get(p.symbol, 0):.2f}", owner))
            else:
                self.lbl_equity.config(text="Equity: (IBKR — Zyklus ausführen oder Verbindung testen)")
        except Exception as exc:
            self.lbl_equity.config(text=f"Broker nicht erreichbar: {exc}")

        killed = botdb.get_meta(conn, "killed") == "1"
        self.lbl_kill.config(text="⚠ KILL-SWITCH AKTIV" if killed else "",
                             foreground="red" if killed else "black")

        eq = botdb.equity_curve(conn)
        self.equity_canvas.plot(eq.set_index("time")["equity"] if len(eq) else None)

        self.ord_tree.delete(*self.ord_tree.get_children())
        for _, r in botdb.recent_orders(conn, 100).iterrows():
            self.ord_tree.insert("", "end", values=(
                r["time"], r["symbol"], f"{r['quantity']:g}", f"{r['price']:.2f}",
                f"{r['commission'] or 0:.2f}", r["reason"]))

        self.log_tree.delete(*self.log_tree.get_children())
        for _, row in botdb.recent_events(conn, 200).iterrows():
            self.log_tree.insert("", "end", values=(row["time"], row["level"], row["message"]))
        conn.close()

    def reset_kill(self) -> None:
        if messagebox.askyesno(
                "Kill-Switch", "Kill-Switch wirklich zurücksetzen?\n\n"
                "Vorher klären, WARUM der Drawdown entstanden ist —\n"
                "dafür ist die Sperre absichtlich unbequem."):
            engine = TradingEngine(self.settings, self._make_broker(connect=False))
            engine.reset_kill_switch()
            self.refresh()

    def _reset_paper(self) -> None:
        if messagebox.askyesno("Paper-Konto",
                               "Simulationskonto wirklich auf Startkapital zurücksetzen?"):
            broker = make_broker("paper",
                                 start_cash=float(self.settings.get("paper_start_cash", 100_000)))
            broker.reset()
            self.refresh()

    # ------------------------------------------------------------- Zyklus

    def _make_broker(self, connect: bool = True):
        s = self.settings
        if s.get("broker") == "ibkr":
            broker = make_broker("ibkr", host=s["ibkr_host"], port=int(s["ibkr_port"]),
                                 client_id=int(s["ibkr_client_id"]),
                                 allow_live=bool(s.get("allow_live")))
            if connect:
                broker.connect()
            return broker
        return make_broker("paper", start_cash=float(s.get("paper_start_cash", 100_000)))

    def run_cycle(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        self.save()
        self.btn_cycle.config(state="disabled")
        self.worker = threading.Thread(target=self._cycle_worker, daemon=True)
        self.worker.start()

    def _cycle_worker(self) -> None:
        try:
            broker = self._make_broker()
            engine = TradingEngine(self.settings, broker,
                                   status=lambda m: self.app.queue.put(("status", m)))
            summary = engine.run_cycle()
            self.app.queue.put(("tradebot_done", summary))
        except Exception as exc:
            self.app.queue.put(("error", f"Zyklus fehlgeschlagen: {exc}"))
            self.app.queue.put(("tradebot_done", None))

    def on_cycle_done(self, payload) -> None:
        self.btn_cycle.config(state="normal")
        if payload:
            self.app.set_status(str(payload))
        self.refresh()

    # ---------------------------------------------------------- Auto-Modus

    def toggle_auto(self) -> None:
        if self.auto_thread and self.auto_thread.is_alive():
            self.auto_stop.set()
            self.settings["trading_active"] = False
            save_settings(self.settings, "live")
            self._set_trading_button(False)
            botdb.log_event(botdb.connect(), "Trading PAUSIERT (Schalter)", "warn")
            self.app.set_status("Trading pausiert — es werden keine Zyklen mehr ausgeführt.")
            return
        self.save()
        self.settings["trading_active"] = True
        save_settings(self.settings, "live")
        self.auto_stop.clear()
        self.auto_thread = threading.Thread(target=self._auto_loop, daemon=True)
        self.auto_thread.start()
        self._set_trading_button(True)
        botdb.log_event(botdb.connect(), "Trading AKTIV geschaltet (Schalter)", "info")

    def _set_trading_button(self, active: bool) -> None:
        if active:
            self.btn_auto.config(text="⏸ TRADING PAUSIEREN  (aktiv)",
                                 bg="#ffebee", activebackground="#ffcdd2")
        else:
            self.btn_auto.config(text="▶ TRADING AKTIV SCHALTEN",
                                 bg="#e8f5e9", activebackground="#c8e6c9")

    def _auto_loop(self) -> None:
        interval = self.settings.get("interval", "1d")
        minutes = {"1 hour": 60, "15 mins": 15, "5 mins": 5}.get(interval)
        last_run_day = None
        self.app.queue.put(("status", f"Auto-Modus aktiv (Intervall {interval})"))
        while not self.auto_stop.wait(30):
            now = datetime.now()
            due = False
            if minutes:
                due = now.minute % minutes == 0 and now.second < 30
            else:
                run_at = self.settings.get("auto_run_time", "22:15")
                due = now.strftime("%H:%M") >= run_at and last_run_day != now.date()
            if due and not (self.worker and self.worker.is_alive()):
                last_run_day = now.date()
                self.app.queue.put(("status", "Auto-Zyklus startet …"))
                self._cycle_worker()
