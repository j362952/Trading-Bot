"""Seite 1 — Daten: Visualisierung der Datenlage aus den Hub-Metadaten.

Kategorien-Überblick (Umfang, Zeitraum, letzter Abruf), Frische-Ampeln,
Symbol-Abdeckung des aktuellen Universums, Makro-Reihen als Mini-Charts,
letzte Abruffehler — plus Abruf-Knöpfe je Kategorie.
"""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk

import pandas as pd

from ..config import load_settings
from .widgets import SparkCanvas, make_tree


class DataPage(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.busy = False

        # ---------------- Abruf-Knöpfe
        bar = ttk.LabelFrame(self, text="Abrufen (je Kategorie; Quelle: Live-Profil-Universum)",
                             padding=6)
        bar.pack(fill="x", padx=8, pady=8)
        buttons = [
            ("Kurse (EOD)", self._fetch_prices),
            ("Aktuelle Preise", self._fetch_quotes),
            ("Fundamentaldaten", self._fetch_fundamentals),
            ("Makro (FRED + Proxys)", self._fetch_macro),
            ("Earnings-Termine", self._fetch_earnings),
            ("Ereignis-Kalender", self._fetch_events),
            ("Corporate Actions", self._fetch_actions),
            ("News-Archiv", self._fetch_news),
            ("Intraday (1 Std)", self._fetch_intraday),
            ("Universum-Snapshot", self._fetch_universe),
        ]
        for text, cmd in buttons:
            ttk.Button(bar, text=text, command=cmd).pack(side="left", padx=3, pady=2)
        ttk.Button(bar, text="APIs testen", command=self._test_apis).pack(side="left", padx=(12, 3))
        ttk.Label(bar, text="Ansicht aktualisiert sich automatisch").pack(side="right", padx=6)

        body = ttk.PanedWindow(self, orient="vertical")
        body.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        # ---------------- API-Schnittstellen (wo kommen die Daten her?)
        api_frame = ttk.LabelFrame(body, text="API-Schnittstellen "
                                   "(● grün = zuletzt erfolgreich geliefert)")
        self.api_tree = make_tree(api_frame, [("ampel", "", 30),
                                              ("schnittstelle", "Schnittstelle", 210),
                                              ("konfig", "Konfiguration", 170),
                                              ("letzter_ok", "zuletzt geliefert", 120),
                                              ("letzter_fehler", "letzter Fehler", 120),
                                              ("sitzung", "diese Sitzung", 100),
                                              ("zweck", "liefert", 420)],
                                  height=7, stretch_col="zweck")
        self.api_tree.tag_configure("green", foreground="#2e7d32")
        self.api_tree.tag_configure("yellow", foreground="#f9a825")
        self.api_tree.tag_configure("red", foreground="#c62828")
        self.api_tree.tag_configure("gray", foreground="#888")
        body.add(api_frame, weight=2)

        # ---------------- Kategorien-Überblick
        cat_frame = ttk.LabelFrame(body, text="Datenkategorien (Hub)")
        self.cat_tree = make_tree(cat_frame, [("ampel", "", 30),
                                              ("kategorie", "Kategorie", 240),
                                              ("umfang", "Umfang", 200),
                                              ("von", "von", 90), ("bis", "bis", 90),
                                              ("abruf", "letzter Abruf", 130)],
                                  height=10, stretch_col="umfang")
        self.cat_tree.tag_configure("green", foreground="#2e7d32")
        self.cat_tree.tag_configure("yellow", foreground="#f9a825")
        self.cat_tree.tag_configure("red", foreground="#c62828")
        body.add(cat_frame, weight=2)

        # ---------------- Makro-Minicharts + Fehler nebeneinander
        lower = ttk.PanedWindow(body, orient="horizontal")
        body.add(lower, weight=2)

        self.macro_frame = ttk.LabelFrame(lower, text="Makro-Reihen (letzter Wert + 1 Jahr)")
        lower.add(self.macro_frame, weight=1)

        err_frame = ttk.LabelFrame(lower, text="Letzte Abruffehler")
        self.err_tree = make_tree(err_frame, [("time", "Zeit", 130),
                                              ("category", "Kategorie", 90),
                                              ("key", "Was", 110),
                                              ("message", "Fehler", 320)],
                                  height=6, stretch_col="message")
        lower.add(err_frame, weight=2)

        # ---------------- Symbol-Abdeckung
        sym_frame = ttk.LabelFrame(body, text="Abdeckung je Symbol (Universum des Live-Profils)")
        self.sym_tree = make_tree(sym_frame, [("symbol", "Symbol", 90),
                                              ("kurse_von", "Kurse von", 90),
                                              ("kurse_bis", "Kurse bis", 90),
                                              ("quartale", "Quartale", 70),
                                              ("letztes_quartal", "letztes Quartal", 110),
                                              ("preis", "Preis", 80),
                                              ("preis_datum", "Preis-Datum", 90),
                                              ("news", "News", 60)],
                                  stretch_col="symbol")
        body.add(sym_frame, weight=3)

        self.after(200, self.refresh)
        self.after(60_000, self._auto_refresh)

    def _auto_refresh(self) -> None:
        """Ansicht aktualisiert sich selbst: jede Minute + nach jedem Abruf
        (data_do_refresh) — kein manueller Knopf nötig."""
        if not self.busy:
            self.refresh()
        self.after(60_000, self._auto_refresh)

    # ------------------------------------------------------------- Anzeige

    def refresh(self) -> None:
        def worker():
            try:
                from ..data import hub

                conn = hub.connect()
                hub.refresh_price_meta(conn)
                summary = hub.category_summary(conn)
                apis = hub.api_status(conn)
                errors = hub.recent_fetch_errors(conn, 30)
                symbols = self._symbols()[:400]
                coverage = hub.symbol_coverage(conn, symbols) if symbols else pd.DataFrame()
                macro = {}
                for series in conn.execute(
                        "SELECT DISTINCT series FROM macro_series").fetchall():
                    macro[series[0]] = hub.load_macro_series(conn, series[0])
                conn.close()
                self.app.queue.put(("data_refreshed",
                                    (summary, apis, errors, coverage, macro)))
            except Exception as exc:
                self.app.queue.put(("error", f"Daten-Seite: {exc}"))
        threading.Thread(target=worker, daemon=True).start()
        self.app.set_status("Aktualisiere Datenübersicht …")

    def on_refreshed(self, payload) -> None:
        summary, apis, errors, coverage, macro = payload
        today = pd.Timestamp.today()

        self.api_tree.delete(*self.api_tree.get_children())
        for _, r in apis.iterrows():
            ok, fail = str(r["letzter_ok"]), str(r["letzter_fehler"])
            if ok and (not fail or ok >= fail):
                tag = "green"       # zuletzt erfolgreich geliefert
            elif fail:
                tag = "red"         # letzter Kontakt war ein Fehler
            elif "KEIN Key" in str(r["konfig"]):
                tag = "yellow"      # nutzbar, aber nicht konfiguriert
            else:
                tag = "gray"        # noch nie kontaktiert
            self.api_tree.insert("", "end", tags=(tag,), values=(
                "●", r["schnittstelle"], r["konfig"], ok or "nie",
                fail or "–", r["sitzung"], r["zweck"]))

        self.cat_tree.delete(*self.cat_tree.get_children())
        for _, r in summary.iterrows():
            ampel, tag = self._freshness(r, today)
            self.cat_tree.insert("", "end", tags=(tag,), values=(
                ampel, r["kategorie"], r["umfang"], _short(r["von"]), _short(r["bis"]),
                r["letzter_abruf"] or "nie"))

        self.err_tree.delete(*self.err_tree.get_children())
        for _, r in errors.iterrows():
            self.err_tree.insert("", "end", values=(
                str(r["time"])[:16].replace("T", " "), r["category"], r["key"],
                r["message"]))

        self.sym_tree.delete(*self.sym_tree.get_children())
        for _, r in coverage.iterrows():
            self.sym_tree.insert("", "end", values=tuple(r))

        for child in self.macro_frame.winfo_children():
            child.destroy()
        if not macro:
            ttk.Label(self.macro_frame, padding=8,
                      text="Noch keine Makro-Reihen — 'Makro (FRED + Proxys)' abrufen."
                      ).pack(anchor="w")
        for name, series in sorted(macro.items()):
            row = ttk.Frame(self.macro_frame)
            row.pack(anchor="w", padx=4, pady=2)
            spark = SparkCanvas(row)
            spark.pack(side="left")
            spark.plot(series)
            last = f"{series.iloc[-1]:,.2f}" if len(series) else "–"
            date = str(series.index[-1])[:10] if len(series) else ""
            ttk.Label(row, text=f" {name}: {last}  ({date})").pack(side="left")
        self.app.set_status("Datenübersicht aktualisiert.")

    @staticmethod
    def _freshness(row, today) -> tuple[str, str]:
        """Ampel je Kategorie: grün = Daten bis (fast) heute, gelb = älter,
        rot = leer."""
        if not row["bis"]:
            return "●", "red"
        try:
            age = (today - pd.Timestamp(str(row["bis"]))).days
        except Exception:
            return "●", "yellow"
        if age <= 7:
            return "●", "green"
        if age <= 45:
            return "●", "yellow"
        return "●", "red"

    # -------------------------------------------------------------- Abrufe

    def _symbols(self) -> list[str]:
        try:
            from ..engine import resolve_symbols

            return resolve_symbols(load_settings("live"))
        except Exception:
            return []

    def _run(self, label: str, fn) -> None:
        """Feed-Funktion im Hintergrund, mit Status und Abschluss-Refresh."""
        if self.busy:
            self.app.set_status("Es läuft bereits ein Abruf — bitte warten.")
            return
        self.busy = True
        self.app.set_status(f"{label} …")

        def worker():
            try:
                from ..data import hub

                conn = hub.connect()
                result = fn(conn)
                conn.close()
                self.app.queue.put(("status", f"{label}: fertig ({result})."))
            except Exception as exc:
                self.app.queue.put(("error", f"{label}: {exc}"))
            finally:
                self.busy = False
                self.app.queue.put(("data_do_refresh", None))
        threading.Thread(target=worker, daemon=True).start()

    def _progress(self, msg: str) -> None:
        self.app.queue.put(("status", msg))

    def _fetch_prices(self) -> None:
        symbols = self._symbols()
        self._run("Kurs-Refresh", lambda conn: __import__(
            "tradingbot.data.feeds", fromlist=["feeds"]).refresh_prices(
            conn, symbols, progress=self._progress))

    def _fetch_quotes(self) -> None:
        symbols = self._symbols()
        self._run("Aktuelle Preise", lambda conn: __import__(
            "tradingbot.data.feeds", fromlist=["feeds"]).update_quotes(
            conn, symbols, progress=self._progress))

    def _fetch_fundamentals(self) -> None:
        def fn(conn):
            from ..data.fundamentals import update_fundamentals
            from ..data.universe import load_universe

            settings = load_settings("live")
            key = settings.get("universe", "manual")
            if key in ("", "manual"):
                universe = pd.DataFrame({"symbol": settings.get("watchlist", []),
                                         "name": "", "sector": ""})
            else:
                universe = load_universe(key)
            stats = update_fundamentals(
                universe, conn,
                progress=lambda i, n, s, st: self._progress(f"Fundamentals {i}/{n} {s}: {st}"))
            return stats
        self._run("Fundamentaldaten", fn)

    def _fetch_macro(self) -> None:
        self._run("Makro", lambda conn: __import__(
            "tradingbot.data.feeds", fromlist=["feeds"]).update_macro(
            conn, progress=self._progress))

    def _fetch_earnings(self) -> None:
        symbols = self._symbols()
        self._run("Earnings-Termine", lambda conn: __import__(
            "tradingbot.data.feeds", fromlist=["feeds"]).update_earnings(
            conn, symbols, progress=self._progress))

    def _fetch_events(self) -> None:
        self._run("Ereignis-Kalender", lambda conn: __import__(
            "tradingbot.data.feeds", fromlist=["feeds"]).update_events(
            conn, progress=self._progress))

    def _fetch_actions(self) -> None:
        symbols = self._symbols()
        self._run("Corporate Actions", lambda conn: __import__(
            "tradingbot.data.feeds", fromlist=["feeds"]).update_corporate_actions(
            conn, symbols, progress=self._progress))

    def _test_apis(self) -> None:
        def fn(conn):
            from ..data.feeds import test_apis

            results = test_apis(conn, progress=self._progress)
            return "; ".join(f"{k}: {'OK' if v.startswith('OK') else 'Fehler'}"
                             for k, v in results.items())
        self._run("API-Verbindungstest", fn)

    def _fetch_news(self) -> None:
        symbols = self._symbols()
        self._run("News-Archiv", lambda conn: __import__(
            "tradingbot.data.feeds", fromlist=["feeds"]).update_news(
            conn, symbols, progress=self._progress))

    def _fetch_intraday(self) -> None:
        symbols = self._symbols()
        self._run("Intraday-Archiv (1 Std)", lambda conn: __import__(
            "tradingbot.data.feeds", fromlist=["feeds"]).update_intraday(
            conn, symbols, interval="1 hour", progress=self._progress))

    def _fetch_universe(self) -> None:
        key = load_settings("live").get("universe", "manual")
        if key in ("", "manual"):
            self.app.set_status("Universum-Snapshot: im Live-Profil ist "
                                "'Manuelle Watchlist' gewählt — Index wählen.")
            return
        self._run(f"Universum-Snapshot ({key})", lambda conn: __import__(
            "tradingbot.data.feeds", fromlist=["feeds"]).snapshot_universe(
            conn, key, progress=self._progress))


def _short(value) -> str:
    return "" if value is None or pd.isna(value) else str(value)[:10]
