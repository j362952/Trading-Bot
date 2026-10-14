"""Zahnrad-Dialog: Broker, Zyklus, Risiko, Sentiment/Makro, API-Keys.

Ein Dialog für beide Profile — die TradeBot-Seite öffnet ihn mit dem
"live"-Profil, die Backtest-Seite mit "test" (dort ohne Broker-Teil).
Schreibt direkt in das übergebene settings-Dict; Speichern übernimmt
der Aufrufer (Callback on_save).
"""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk

from ..risk import RiskConfig

INTERVALS = ["1d", "1 hour", "15 mins", "5 mins"]

RISK_LABELS = {
    "risk_per_trade": "Risiko je Trade (z.B. 0.01 = 1 %)",
    "atr_n": "ATR-Periode (Tage)",
    "atr_stop_mult": "Trailing-Stop (× ATR)",
    "max_positions": "Max. offene Positionen",
    "max_weight": "Max. Gewicht je Position (0.2 = 20 %)",
    "regime_symbol": "Regime-Referenzindex",
    "regime_sma": "Regime-SMA (0 = Filter aus)",
    "max_drawdown": "Kill-Switch bei Drawdown (0.25 = 25 %)",
    "cooldown_days": "Abkühl-Tage nach Stop-Out",
}


class SettingsDialog(tk.Toplevel):
    def __init__(self, parent, settings: dict, on_save, profile: str = "live",
                 show_broker: bool = True):
        super().__init__(parent)
        self.title(f"Einstellungen — Profil '{profile}'")
        self.settings = settings
        self.on_save = on_save
        self.show_broker = show_broker
        self.transient(parent)
        self.grab_set()

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=8, pady=8)
        self.tab_risk = ttk.Frame(nb)
        nb.add(self.tab_risk, text="  Risiko  ")
        self._build_risk(self.tab_risk)
        self.tab_gates = ttk.Frame(nb)
        nb.add(self.tab_gates, text="  Sentiment & Makro  ")
        self._build_gates(self.tab_gates)
        if show_broker:
            self.tab_broker = ttk.Frame(nb)
            nb.add(self.tab_broker, text="  Broker & Zyklus  ")
            self._build_broker(self.tab_broker)
        self.tab_keys = ttk.Frame(nb)
        nb.add(self.tab_keys, text="  API-Keys  ")
        self._build_keys(self.tab_keys)

        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(bar, text="Speichern & Schließen", command=self._save).pack(side="right")
        ttk.Button(bar, text="Abbrechen", command=self.destroy).pack(side="right", padx=8)

    # ---------------------------------------------------------------- Risiko

    def _build_risk(self, tab) -> None:
        frame = ttk.LabelFrame(tab, text="Risk-Management (gilt für Backtest UND Live)",
                               padding=12)
        frame.pack(anchor="nw", padx=8, pady=8)
        current = RiskConfig.from_dict(self.settings.get("risk", {}))
        self.risk_vars: dict[str, tk.StringVar] = {}
        for name in RiskConfig.__dataclass_fields__:
            row = ttk.Frame(frame)
            row.pack(anchor="w", pady=2)
            ttk.Label(row, text=RISK_LABELS.get(name, name), width=38).pack(side="left")
            var = tk.StringVar(value=str(getattr(current, name)))
            ttk.Entry(row, textvariable=var, width=10).pack(side="left")
            self.risk_vars[name] = var
        ttk.Label(tab, padding=8, justify="left", text=(
            "Regeln und Begründungen: STRATEGIE.md.\n"
            "Markt-Modus (§4.2): regime_sma=0, atr_stop_mult=5, risk_per_trade=0.0167 —\n"
            "nur zusammen mit der Makro-Ampel empfohlen.")).pack(anchor="nw")

    # ------------------------------------------------------ Sentiment/Makro

    def _build_gates(self, tab) -> None:
        sent = ttk.LabelFrame(tab, text="News-Sentiment-Gate (FinBERT)", padding=12)
        sent.pack(anchor="nw", fill="x", padx=8, pady=8)
        self.sent_var = tk.BooleanVar(value=bool(self.settings.get("sentiment_enabled")))
        ttk.Checkbutton(sent, text="Einstiege bei negativer Nachrichtenlage blockieren",
                        variable=self.sent_var).pack(anchor="w")
        row = ttk.Frame(sent)
        row.pack(anchor="w", pady=4)
        ttk.Label(row, text="Schwelle (-1 … +1):").pack(side="left")
        self.sent_min = ttk.Entry(row, width=8)
        self.sent_min.insert(0, str(self.settings.get("sentiment_min", -0.2)))
        self.sent_min.pack(side="left", padx=4)
        ttk.Label(row, text="Fenster (Tage):").pack(side="left", padx=(12, 0))
        self.sent_days = ttk.Entry(row, width=6)
        self.sent_days.insert(0, str(self.settings.get("sentiment_days", 7)))
        self.sent_days.pack(side="left", padx=4)

        macro = ttk.LabelFrame(tab, text="Makro-Schicht", padding=12)
        macro.pack(anchor="nw", fill="x", padx=8, pady=(0, 8))
        self.macro_var = tk.BooleanVar(value=bool(self.settings.get("macro_filter", True)))
        ttk.Checkbutton(macro, text="Makro-Ampel: neue Käufe nur bei Risk-on "
                        "(Index-Trend, VIX, Kredit, realisierte Vola — Mehrheitsvotum)",
                        variable=self.macro_var).pack(anchor="w")
        self.event_var = tk.BooleanVar(value=bool(self.settings.get("event_blackout", False)))
        ttk.Checkbutton(macro, text="Ereignis-Blackout: an Tagen mit Fed/CPI/Arbeitsmarkt-"
                        "Terminen keine Neueinstiege (nur Live, braucht FMP-Key)",
                        variable=self.event_var).pack(anchor="w")

    # -------------------------------------------------------- Broker/Zyklus

    def _build_broker(self, tab) -> None:
        broker_frame = ttk.LabelFrame(tab, text="Broker", padding=12)
        broker_frame.pack(anchor="nw", fill="x", padx=8, pady=8)
        self.broker_var = tk.StringVar(value=self.settings.get("broker", "paper"))
        ttk.Radiobutton(broker_frame, text="Simulation (PaperBroker, kein Konto nötig)",
                        variable=self.broker_var, value="paper").pack(anchor="w")
        ttk.Radiobutton(broker_frame, text="Interactive Brokers (TWS/IB Gateway muss laufen)",
                        variable=self.broker_var, value="ibkr").pack(anchor="w")
        ib = ttk.Frame(broker_frame)
        ib.pack(anchor="w", pady=6)
        self.ib_vars = {}
        for label, key, width in [("Host", "ibkr_host", 14), ("Port", "ibkr_port", 7),
                                  ("Client-ID", "ibkr_client_id", 5)]:
            ttk.Label(ib, text=label).pack(side="left", padx=(0, 2))
            var = tk.StringVar(value=str(self.settings.get(key, "")))
            ttk.Entry(ib, textvariable=var, width=width).pack(side="left", padx=(0, 10))
            self.ib_vars[key] = var
        ttk.Label(broker_frame, text="Ports: 7497 TWS-Paper · 4002 Gateway-Paper "
                  "(Live-Ports 7496/4001 erfordern den Live-Schalter)").pack(anchor="w")
        self.live_var = tk.BooleanVar(value=bool(self.settings.get("allow_live")))
        ttk.Checkbutton(broker_frame,
                        text="LIVE-Trading erlauben (erst nach überzeugendem Paper-Track-Record!)",
                        variable=self.live_var).pack(anchor="w", pady=4)
        row = ttk.Frame(broker_frame)
        row.pack(anchor="w", pady=4)
        ttk.Button(row, text="IBKR-Verbindung testen", command=self._test_ibkr).pack(side="left")
        row2 = ttk.Frame(broker_frame)
        row2.pack(anchor="w", pady=2)
        ttk.Label(row2, text="Paper-Startkapital:").pack(side="left")
        self.cash_var = tk.StringVar(value=str(self.settings.get("paper_start_cash", 100000.0)))
        ttk.Entry(row2, textvariable=self.cash_var, width=12).pack(side="left", padx=4)

        cyc = ttk.LabelFrame(tab, text="Zyklus", padding=12)
        cyc.pack(anchor="nw", fill="x", padx=8, pady=8)
        row = ttk.Frame(cyc)
        row.pack(anchor="w")
        ttk.Label(row, text="Intervall:").pack(side="left")
        self.interval_var = tk.StringVar(value=self.settings.get("interval", "1d"))
        ttk.Combobox(row, state="readonly", width=10, textvariable=self.interval_var,
                     values=INTERVALS).pack(side="left", padx=6)
        ttk.Label(row, text="Tageszyklus um:").pack(side="left", padx=(16, 2))
        self.runtime_var = tk.StringVar(value=self.settings.get("auto_run_time", "22:15"))
        ttk.Entry(row, textvariable=self.runtime_var, width=7).pack(side="left")
        ttk.Label(cyc, text="Intraday-Intervalle brauchen die IBKR-Verbindung als "
                  "Datenquelle;\nTagesdaten kommen aus dem Kurs-Cache.").pack(anchor="w", pady=4)

    # ---------------------------------------------------------------- Keys

    def _build_keys(self, tab) -> None:
        keys = ttk.LabelFrame(tab, text="Daten-API-Keys (lokal in data_cache/, "
                              "nicht versioniert)", padding=12)
        keys.pack(anchor="nw", fill="x", padx=8, pady=8)
        self.key_vars = {}
        for label, key in [("FMP-Key (Fundamental/Earnings/Events)", "fmp_api_key"),
                           ("Tiingo-Key (Kurse/Intraday-IEX)", "tiingo_api_key"),
                           ("FRED-Key (Makro — optional)", "fred_api_key")]:
            row = ttk.Frame(keys)
            row.pack(anchor="w", pady=2)
            ttk.Label(row, text=label, width=34).pack(side="left")
            var = tk.StringVar(value=str(self.settings.get(key, "")))
            ttk.Entry(row, textvariable=var, width=44, show="*").pack(side="left")
            self.key_vars[key] = var
        ttk.Label(tab, padding=8, justify="left", text=(
            "FRED geht auch ohne Key (fredgraph.csv), wird aber teils per Bot-Schutz\n"
            "gedrosselt — der kostenlose Key (fred.stlouisfed.org → API Keys) nutzt die\n"
            "offizielle API und ist zuverlässig. Zusätzliche Fallbacks laufen automatisch:\n"
            "EZB Data Portal (Europa-Reihen) und Yahoo-Renditeindizes (US-Zinsen).")).pack(anchor="w")

    # ---------------------------------------------------------------- Aktionen

    def _test_ibkr(self) -> None:
        from ..broker import make_broker

        def worker():
            try:
                broker = make_broker("ibkr", host=self.ib_vars["ibkr_host"].get(),
                                     port=int(self.ib_vars["ibkr_port"].get()),
                                     client_id=int(self.ib_vars["ibkr_client_id"].get()),
                                     allow_live=self.live_var.get())
                broker.connect()
                eq = broker.equity()
                broker.disconnect()
                self.after(0, lambda: messagebox.showinfo(
                    "IBKR", f"OK — {broker.name}, Equity {eq:,.0f}", parent=self))
            except Exception as exc:
                self.after(0, lambda: messagebox.showerror(
                    "IBKR", f"Verbindung fehlgeschlagen: {exc}", parent=self))
        threading.Thread(target=worker, daemon=True).start()

    def _save(self) -> None:
        s = self.settings
        risk = {}
        for name, var in self.risk_vars.items():
            raw = var.get()
            field_type = RiskConfig.__dataclass_fields__[name].type
            try:
                risk[name] = raw if field_type in ("str", str) else (
                    int(raw) if field_type in ("int", int) else float(raw))
            except ValueError:
                pass
        s["risk"] = risk
        s["sentiment_enabled"] = self.sent_var.get()
        try:
            s["sentiment_min"] = float(self.sent_min.get())
            s["sentiment_days"] = int(self.sent_days.get())
        except ValueError:
            pass
        s["macro_filter"] = self.macro_var.get()
        s["event_blackout"] = self.event_var.get()
        if self.show_broker:
            s["broker"] = self.broker_var.get()
            s["ibkr_host"] = self.ib_vars["ibkr_host"].get()
            try:
                s["ibkr_port"] = int(self.ib_vars["ibkr_port"].get())
                s["ibkr_client_id"] = int(self.ib_vars["ibkr_client_id"].get())
            except ValueError:
                pass
            s["allow_live"] = self.live_var.get()
            try:
                s["paper_start_cash"] = float(self.cash_var.get())
            except ValueError:
                pass
            s["interval"] = self.interval_var.get()
            s["auto_run_time"] = self.runtime_var.get()
        for key, var in self.key_vars.items():
            s[key] = var.get().strip()
        self.on_save()
        self.destroy()
