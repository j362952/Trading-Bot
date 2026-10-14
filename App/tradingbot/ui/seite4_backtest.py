"""Seite 4 — Backtest: eigenes Profil "test", unabhängig vom Live-Betrieb.

Zwei Modi (GUI_KONZEPT.md):
(a) fester Zeitraum (von–bis): alle konfigurierten Strategien einzeln
    (plus Budget-Kombination bei mehreren) gegen SPY-Benchmark, mit
    Segment-Auswertung (Sektor/Vol-Drittel) der Trades;
(b) randomisierte Zeitfenster: der Robustheits-Harness (zufällige Fenster
    × Teiluniversen) — Ergebnis als Verteilung inkl. Marktphasen-Analyse.

Immer mit voller Risk-Schicht und Kosten. Eigene Aktienauswahl über das
Test-Profil; Zahnrad = Risiko/Gates/Keys des Test-Profils.
"""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk

import pandas as pd

from ..config import REPORTS_DIR, load_settings, save_settings
from ..risk import RiskConfig
from .settings_dialog import SettingsDialog
from .source_panel import SourcePanel, StrategyPanel
from .widgets import make_tree


class BacktestPage(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.settings = load_settings("test")
        self.worker: threading.Thread | None = None

        main = ttk.PanedWindow(self, orient="horizontal")
        main.pack(fill="both", expand=True, padx=8, pady=8)

        # ---------------- linke Spalte: Test-Profil
        left = ttk.Frame(main)
        main.add(left, weight=1)
        head = ttk.Frame(left)
        head.pack(fill="x")
        ttk.Label(head, text="Profil 'test' (unabhängig vom Live-Betrieb)",
                  font=("", 10, "bold")).pack(side="left")
        ttk.Button(head, text="⚙", width=3, command=self._open_settings).pack(side="right")

        # Start-Zeile, Kapital und Modus FEST am unteren Rand verankern
        # (side="bottom", zuerst gepackt = ganz unten) — so bleibt der
        # Start-Button immer sichtbar, egal wie hoch die Panels darüber sind.
        bar = ttk.Frame(left)
        bar.pack(side="bottom", fill="x", pady=8)
        self.btn_run = tk.Button(bar, text="▶ BACKTEST STARTEN", font=("", 10, "bold"),
                                 command=self.run, bg="#e3f2fd", activebackground="#bbdefb")
        self.btn_run.pack(side="left")
        ttk.Button(bar, text="Profil speichern", command=self.save).pack(side="left", padx=8)
        self.sent_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="Sentiment-Gate (lädt FinBERT)",
                        variable=self.sent_var).pack(side="left", padx=8)

        cap_row = ttk.Frame(left)
        cap_row.pack(side="bottom", fill="x", pady=(8, 0))
        ttk.Label(cap_row, text="Startkapital je Strategie:").pack(side="left")
        self.capital_var = tk.StringVar(value="10000")
        ttk.Entry(cap_row, textvariable=self.capital_var, width=10).pack(side="left", padx=4)
        ttk.Label(cap_row, wraplength=340, justify="left",
                  text="(jede Strategie unabhängig mit diesem Betrag; Vergleich: "
                       "derselbe Betrag in SPY und QQQ)").pack(side="left")

        mode = ttk.LabelFrame(left, text="Modus", padding=8)
        mode.pack(side="bottom", fill="x", pady=(8, 0))

        # darüber: Aktienquelle (fix) + Strategien (nehmen den Rest)
        self.source = SourcePanel(left, self.settings, status=self.app.set_status)
        self.source.pack(fill="x", pady=(4, 0))
        self.strategies = StrategyPanel(left, self.settings)
        self.strategies.pack(fill="both", expand=True, pady=(8, 0))
        self.mode_var = tk.StringVar(value="fixed")
        ttk.Radiobutton(mode, text="Fester Zeitraum", variable=self.mode_var,
                        value="fixed").pack(anchor="w")
        row = ttk.Frame(mode)
        row.pack(anchor="w", padx=18)
        ttk.Label(row, text="von:").pack(side="left")
        self.start_var = tk.StringVar(value="2015-01-01")
        ttk.Entry(row, textvariable=self.start_var, width=11).pack(side="left", padx=4)
        ttk.Label(row, text="bis:").pack(side="left")
        self.end_var = tk.StringVar(value="")
        ttk.Entry(row, textvariable=self.end_var, width=11).pack(side="left", padx=4)
        ttk.Label(row, text="(leer = heute)").pack(side="left")

        ttk.Radiobutton(mode, text="Randomisierte Zeitfenster (Robustheits-Harness)",
                        variable=self.mode_var, value="random").pack(anchor="w", pady=(6, 0))
        row2 = ttk.Frame(mode)
        row2.pack(anchor="w", padx=18)
        ttk.Label(row2, text="Fenster:").pack(side="left")
        self.runs_var = tk.StringVar(value="40")
        ttk.Entry(row2, textvariable=self.runs_var, width=5).pack(side="left", padx=4)
        ttk.Label(row2, text="Seed:").pack(side="left", padx=(8, 0))
        self.seed_var = tk.StringVar(value="")
        ttk.Entry(row2, textvariable=self.seed_var, width=7).pack(side="left", padx=4)
        ttk.Label(row2, text="(leer = zufällig)").pack(side="left")
        ttk.Label(mode, wraplength=320, justify="left", text=(
            "Zufallsmodus: Fensterlängen 3 Monate–4 Jahre, zufällige Startdaten und "
            "Teiluniversen (40–150 Titel) aus dem Kurs-Cache; Auswertung als Verteilung "
            "inkl. Marktphasen (Bulle/Seitwärts/Bär).")).pack(anchor="w", pady=4)

        # ---------------- rechte Spalte: Ergebnisse
        right = ttk.PanedWindow(main, orient="vertical")
        main.add(right, weight=3)

        res_frame = ttk.LabelFrame(right, text="Ergebnis")
        self.res_tree = make_tree(res_frame, [("strategy", "Strategie/Kennlinie", 230),
                                              ("endwert", "Endkapital", 100),
                                              ("cagr", "CAGR/Median p.a.", 105),
                                              ("max_dd", "Max. DD", 85),
                                              ("sharpe", "Sharpe/pos. Fenster", 115),
                                              ("trades", "Trades/Fenster", 95),
                                              ("win", "Treffer/>SPY", 90),
                                              ("killed", "Kill?", 55)],
                                  stretch_col="strategy")
        right.add(res_frame, weight=2)

        detail_frame = ttk.LabelFrame(right, text="Auswertung (Marktphasen / Segmente)")
        self.detail = tk.Text(detail_frame, height=14, font=("Courier New", 9), wrap="none")
        ys = ttk.Scrollbar(detail_frame, orient="vertical", command=self.detail.yview)
        self.detail.configure(yscrollcommand=ys.set)
        self.detail.pack(side="left", fill="both", expand=True)
        ys.pack(side="right", fill="y")
        right.add(detail_frame, weight=2)

    # ------------------------------------------------------------- Profil

    def save(self) -> None:
        self.source.collect()
        self.strategies.collect()
        save_settings(self.settings, "test")
        self.app.set_status("Test-Profil gespeichert.")

    def _open_settings(self) -> None:
        SettingsDialog(self, self.settings,
                       on_save=lambda: (save_settings(self.settings, "test"),
                                        self.app.set_status("Test-Profil gespeichert.")),
                       profile="test", show_broker=False)

    # ---------------------------------------------------------------- Lauf

    def run(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        self.save()
        self.btn_run.config(state="disabled")
        mode = self.mode_var.get()
        self.worker = threading.Thread(
            target=self._fixed_worker if mode == "fixed" else self._random_worker,
            daemon=True)
        self.worker.start()

    # ---- Modus (a): fester Zeitraum

    def _fixed_worker(self) -> None:
        try:
            from ..data import load_daily
            from ..engine import resolve_strategies, resolve_symbols
            from ..portfolio_backtest import run_portfolio_backtest
            from ..strategies import BuyAndHold
            from ..validation import trade_segments

            s = self.settings
            symbols = resolve_symbols(s)
            start = self.start_var.get().strip() or "2015-01-01"
            end = self.end_var.get().strip() or None
            try:
                capital = float(self.capital_var.get())
            except ValueError:
                capital = 10_000.0
            say = lambda m: self.app.queue.put(("status", m))

            say(f"Lade Kurse für {len(symbols)} Titel …")
            bars = {}
            for i, sym in enumerate(symbols, 1):
                try:
                    df = load_daily(sym, start=start, end=end)
                    if len(df) >= 200:  # Titel braucht genug Historie im Zeitraum
                        bars[sym] = df
                except Exception as exc:
                    say(f"{sym} übersprungen: {exc}")
                if i % 25 == 0 or i == len(symbols):
                    say(f"Kurse: {i}/{len(symbols)} …")

            # ---- Datenprüfung VOR dem Start: genug Titel mit genug Historie?
            required = max(5, int(0.3 * len(symbols)))
            if len(bars) < required:
                raise ValueError(
                    f"Zu wenig Daten für einen aussagekräftigen Backtest: nur "
                    f"{len(bars)} von {len(symbols)} Titeln haben ≥200 Handelstage "
                    f"im Zeitraum ab {start} (nötig: {required}). Erst auf der "
                    f"Daten-Seite 'Kurse (EOD)' für dieses Universum laden.")

            risk = RiskConfig.from_dict(s.get("risk", {}))
            try:
                regime_df = load_daily(risk.regime_symbol, start=start, end=end)
            except ValueError:
                regime_df = None
            macro_series = None
            if s.get("macro_filter", True):
                try:
                    from ..macro import risk_on_series

                    macro_series = risk_on_series(start=start)
                except Exception:
                    macro_series = None
            sentiment = None
            if self.sent_var.get():
                from ..sentiment.history import daily_sentiment

                say("Score News-Archiv (FinBERT) …")
                sentiment = {sym: daily_sentiment(sym, refresh=False) for sym in bars}

            sectors = {}
            try:
                from ..data import hub

                sectors = hub.sector_map(hub.connect())
            except Exception:
                pass

            # ---- Jede Strategie läuft UNABHÄNGIG mit dem vollen Startkapital
            # (keine Budget-Aufteilung im Backtest — Budgets gelten nur live)
            rows, segments = [], []
            for key, strat, _budget in resolve_strategies(s):
                say(f"Backtest {strat.name} (Start {capital:,.0f}) …")
                r = run_portfolio_backtest(bars, strat, risk=risk, sentiment=sentiment,
                                           regime_df=regime_df, regime_series=macro_series,
                                           start_equity=capital)
                m = r.metrics()
                endwert = capital * (1 + m["total_return"])
                rows.append((m["strategy"], f"{endwert:,.0f}", f"{m['cagr']:+.1%}",
                             f"{m['max_drawdown']:.1%}", f"{m['sharpe']:.2f}",
                             m["trades"], f"{m['win_rate']:.0%}",
                             "ja" if m["killed"] else ""))
                seg = trade_segments(r, bars, sectors)
                if not seg.empty:
                    segments.append((m["strategy"], seg))

            # ---- Benchmarks: derselbe fixe Betrag in SPY und QQQ (Buy & Hold)
            from ..backtest import run_backtest

            for bench, label in [("SPY", "S&P 500 ETF"), ("QQQ", "Nasdaq 100 ETF")]:
                try:
                    b = run_backtest(load_daily(bench, start=start, end=end),
                                     BuyAndHold(), symbol=bench)
                    endwert = capital * (1 + b.total_return)
                    rows.append((f"Buy & Hold {bench} ({label})", f"{endwert:,.0f}",
                                 f"{b.cagr:+.1%}", f"{b.max_drawdown:.1%}",
                                 f"{b.sharpe:.2f}", b.num_trades, "", ""))
                except Exception as exc:
                    say(f"Benchmark {bench} übersprungen: {exc}")

            text = ""
            for name, seg in segments:
                text += f"\n=== Trade-Segmente: {name} ===\n"
                text += seg.to_string(index=False,
                                      formatters={"treffer": "{:.0%}".format,
                                                  "median_ret": "{:+.1%}".format,
                                                  "pnl_summe": "{:,.0f}".format}) + "\n"
            self.app.queue.put(("backtest_done", (rows, text or
                                                  "(keine geschlossenen Trades für die "
                                                  "Segment-Auswertung)")))
        except Exception as exc:
            self.app.queue.put(("error", f"Backtest fehlgeschlagen: {exc}"))
            self.app.queue.put(("backtest_done", None))

    # ---- Modus (b): randomisierte Fenster

    def _random_worker(self) -> None:
        try:
            from ..engine import resolve_strategies
            from ..strategies import STRATEGIES, make_strategy
            from ..validation import (load_cached_bars, robustness_test, summarize,
                                      summarize_by_phase, summary_text)

            s = self.settings
            say = lambda m: self.app.queue.put(("status", m))
            n_runs = int(self.runs_var.get() or 40)
            seed = int(self.seed_var.get()) if self.seed_var.get().strip() else None

            say("Lade Kurs-Cache (alle Symbole mit genug Historie) …")
            bars_all = load_cached_bars()
            if len(bars_all) < 50:
                raise ValueError(f"nur {len(bars_all)} Symbole im Kurs-Cache — erst auf "
                                 f"der Daten-Seite 'Kurse (EOD)' für ein Universum laden")
            risk = RiskConfig.from_dict(s.get("risk", {}))

            macro_series = None
            if s.get("macro_filter", True):
                try:
                    from ..macro import risk_on_series

                    closes = {sym: df["Close"] for sym, df in bars_all.items()}
                    macro_series = risk_on_series(closes=closes)
                except Exception:
                    macro_series = None

            rows, text = [], ""
            for key, strat, _budget in resolve_strategies(s):
                say(f"Robustheits-Test {strat.name}: {n_runs} Zufallsfenster …")
                params = next((e.get("params", {}) for e in (s.get("strategies") or [])
                               if e.get("key") == key), s.get("strategy_params", {}))
                factory = lambda k=key, p=params: make_strategy(STRATEGIES[k], p)
                results = robustness_test(factory, bars_all, n_runs=n_runs, risk=risk,
                                          macro_series=macro_series, seed=seed,
                                          progress=say)
                if results.empty:
                    continue
                agg = summarize(results)
                rows.append((strat.name, "—", f"{agg['median_return_pa']:+.1%}",
                             f"{agg['median_max_dd']:.1%}",
                             f"{agg['pct_positive']:.0%} positiv",
                             agg["runs"], f"{agg['pct_beat_spy']:.0%}",
                             str(agg["killed_runs"])))
                text += summary_text(strat.name, agg) + "\n\n"
                try:
                    text += "Marktphasen:\n" + summarize_by_phase(results).to_string(
                        formatters={"median_pa": "{:+.1%}".format,
                                    "pct_pos": "{:.0%}".format,
                                    "excess_spy": "{:+.1%}".format,
                                    "med_dd": "{:.1%}".format}) + "\n\n"
                except Exception:
                    pass
                REPORTS_DIR.mkdir(parents=True, exist_ok=True)
                out = REPORTS_DIR / (f"validation_{key}_"
                                     f"{pd.Timestamp.today():%Y-%m-%d_%H%M}.csv")
                results.to_csv(out, index=False)
                text += f"CSV: {out}\n\n"
            if not rows:
                raise ValueError("keine auswertbaren Läufe")
            self.app.queue.put(("backtest_done", (rows, text)))
        except Exception as exc:
            self.app.queue.put(("error", f"Robustheits-Test fehlgeschlagen: {exc}"))
            self.app.queue.put(("backtest_done", None))

    # -------------------------------------------------------------- Anzeige

    def on_done(self, payload) -> None:
        self.btn_run.config(state="normal")
        if not payload:
            return
        rows, text = payload
        self.res_tree.delete(*self.res_tree.get_children())
        for row in rows:
            self.res_tree.insert("", "end", values=row)
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", text)
        self.app.set_status("Backtest fertig.")
