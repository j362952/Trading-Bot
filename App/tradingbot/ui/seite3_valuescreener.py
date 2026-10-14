"""Seite 3 — ValueScreener: löst die separate MarketScreener-GUI ab.

Eigene Aktienauswahl, Bewertungsalgorithmen als austauschbare Dateien in
tradingbot/screening/ (Registry wie bei den Bot-Strategien), Ergebnistabelle
mit Detail-Spalten + Score-Historie je Titel. Datenbasis: der Daten-Hub.
"""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk

import pandas as pd

from ..config import REPORTS_DIR
from ..screening import SCREENERS, SCREENER_LABELS
from .widgets import make_tree


class ScreenerPage(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.cancel_flag = threading.Event()
        self.result: pd.DataFrame | None = None
        self.universe_key = "manual"

        # ---------------- Kopfzeile
        bar = ttk.LabelFrame(self, text="Screening", padding=6)
        bar.pack(fill="x", padx=8, pady=8)

        from ..data.universe import universe_labels

        self.universe_labels = {}
        try:
            self.universe_labels = universe_labels()
        except Exception:
            pass
        ttk.Label(bar, text="Universum:").pack(side="left")
        self.universe_var = tk.StringVar(
            value=next(iter(self.universe_labels.values()), ""))
        ttk.Combobox(bar, state="readonly", width=32, textvariable=self.universe_var,
                     values=list(self.universe_labels.values())).pack(side="left", padx=4)

        ttk.Label(bar, text="Algorithmus:").pack(side="left", padx=(12, 2))
        self.algo_var = tk.StringVar(value=list(SCREENER_LABELS.values())[0])
        ttk.Combobox(bar, state="readonly", width=36, textvariable=self.algo_var,
                     values=list(SCREENER_LABELS.values())).pack(side="left", padx=4)

        self.btn_full = ttk.Button(bar, text="Daten aktualisieren + Analyse",
                                   command=lambda: self.run(update=True))
        self.btn_full.pack(side="left", padx=8)
        self.btn_score = ttk.Button(bar, text="Nur Analyse",
                                    command=lambda: self.run(update=False))
        self.btn_score.pack(side="left")
        ttk.Button(bar, text="Abbrechen", command=self.cancel_flag.set).pack(side="left", padx=8)

        ttk.Label(self, padding=(8, 0), text=(
            "Erster Lauf über ein großes Universum dauert (1 Abruf je Aktie); abgebrochene "
            "Läufe machen beim nächsten Start weiter. Danach reicht meist 'Nur Analyse' — "
            "Fundamentaldaten gelten 30 Tage als frisch. Methodik: ANALYSE.md."
                  )).pack(anchor="w")

        # ---------------- Ergebnis + Historie
        panes = ttk.PanedWindow(self, orient="vertical")
        panes.pack(fill="both", expand=True, padx=8, pady=8)

        res_frame = ttk.LabelFrame(panes, text="Ergebnis (Doppelklick: Score-Historie unten)")
        self.res_tree = make_tree(res_frame, [("rank", "#", 40), ("symbol", "Symbol", 90),
                                              ("score", "Score", 70),
                                              ("detail", "Details", 700)],
                                  stretch_col="detail")
        self.res_tree.bind("<Double-1>", self._show_history)
        panes.add(res_frame, weight=3)

        hist_frame = ttk.LabelFrame(panes, text="Score-Historie (gewählter Titel)")
        self.hist_tree = make_tree(hist_frame, [("run_at", "Lauf", 150),
                                                ("algo", "Algorithmus", 130),
                                                ("universe", "Universum", 130),
                                                ("rank", "Rang", 60),
                                                ("score", "Score", 70)],
                                   height=5)
        panes.add(hist_frame, weight=1)

    # ---------------------------------------------------------------- Lauf

    def _algo_key(self) -> str:
        label = self.algo_var.get()
        return next((k for k, v in SCREENER_LABELS.items() if v == label), "value_score")

    def _universe(self) -> str:
        label = self.universe_var.get()
        return next((k for k, v in self.universe_labels.items() if v == label), "")

    def run(self, update: bool) -> None:
        key = self._universe()
        if not key:
            self.app.set_status("Kein Universum gewählt.")
            return
        self.cancel_flag.clear()
        self.btn_full.config(state="disabled")
        self.btn_score.config(state="disabled")
        algo = self._algo_key()

        def worker():
            try:
                from ..data import hub
                from ..data.universe import load_universe

                conn = hub.connect()
                self.app.queue.put(("status", f"Universum {key} laden …"))
                universe = load_universe(key)
                symbols = list(universe["symbol"])

                if update:
                    from ..data import feeds
                    from ..data.fundamentals import update_fundamentals

                    hub.snapshot_universe(conn, key, universe)
                    stats = update_fundamentals(
                        universe, conn,
                        progress=lambda i, n, s, st: self.app.queue.put(
                            ("status", f"Fundamentals {i}/{n} {s}: {st}")),
                        cancelled=self.cancel_flag.is_set)
                    self.app.queue.put(("status", f"Fundamentals: {stats}"))
                    feeds.update_quotes(conn, symbols,
                                        progress=lambda m: self.app.queue.put(("status", m)))

                self.app.queue.put(("status", f"Score ({algo}) über {len(symbols)} Titel …"))
                result = SCREENERS[algo]().score(conn, symbols)
                if result is None or result.empty:
                    raise ValueError(
                        "keine bewertbaren Titel — erst 'Daten aktualisieren + Analyse' "
                        "laufen lassen (braucht Fundamentaldaten + aktuelle Preise)")
                hub.save_score_run(conn, algo, key, result)
                REPORTS_DIR.mkdir(parents=True, exist_ok=True)
                out = REPORTS_DIR / (f"screener_{algo}_{key}_"
                                     f"{pd.Timestamp.today():%Y-%m-%d}.csv")
                result.to_csv(out)
                conn.close()
                self.app.queue.put(("screener_done", (result, str(out))))
            except Exception as exc:
                self.app.queue.put(("error", f"Screening fehlgeschlagen: {exc}"))
                self.app.queue.put(("screener_done", None))
        threading.Thread(target=worker, daemon=True).start()

    def on_done(self, payload) -> None:
        self.btn_full.config(state="normal")
        self.btn_score.config(state="normal")
        if not payload:
            return
        result, path = payload
        self.result = result
        self.res_tree.delete(*self.res_tree.get_children())
        detail_cols = [c for c in result.columns if c != "score"]
        for rank, (symbol, row) in enumerate(result.iterrows(), 1):
            detail = ", ".join(f"{c}={row[c]}" for c in detail_cols[:10])
            self.res_tree.insert("", "end", values=(rank, symbol, row["score"], detail))
        self.app.set_status(f"Screening fertig: {len(result)} Titel — CSV: {path}")

    def _show_history(self, _event) -> None:
        sel = self.res_tree.selection()
        if not sel:
            return
        symbol = self.res_tree.item(sel[0], "values")[1]

        def worker():
            try:
                from ..data import hub

                conn = hub.connect()
                hist = hub.score_history(conn, symbol)
                conn.close()
                self.app.queue.put(("screener_history", (symbol, hist)))
            except Exception as exc:
                self.app.queue.put(("error", str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def on_history(self, payload) -> None:
        symbol, hist = payload
        self.hist_tree.delete(*self.hist_tree.get_children())
        for _, r in hist.iterrows():
            self.hist_tree.insert("", "end", values=(
                str(r["run_at"])[:16].replace("T", " "), r["algo"], r["universe"],
                r["rank"], r["score"]))
        self.app.set_status(f"Score-Historie: {symbol} ({len(hist)} Läufe)")
