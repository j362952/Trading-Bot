"""Tkinter-GUI des MarketScreeners.

Bedienung:
1. Universum wählen (S&P 500, Nasdaq 100, DAX, ... MSCI World, Watchlists)
2. "Daten aktualisieren + Analyse" — holt Fundamentaldaten (resume-fähig,
   Cache 30 Tage) und aktuelle Kurse, rechnet den Score
3. oder "Nur Analyse" — rechnet nur mit dem, was schon in der DB liegt

Der Datenabruf läuft in einem Hintergrund-Thread; die GUI bleibt bedienbar
und der Lauf ist abbrechbar. Doppelklick auf eine Zeile zeigt die
Quartals-Historie der Aktie. Jeder Lauf wird als CSV in reports/ abgelegt
und in der DB protokolliert (score_runs/scores).
"""

from __future__ import annotations

import queue
import threading
import traceback
import webbrowser
from datetime import date

import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from . import db
from .config import ANALYSE_MD, REPORTS_DIR, load_settings, save_settings
from .fundamentals import update_fundamentals
from .prices import update_prices
from .scoring import score_universe
from .universe import load_universe, universe_labels

# Tabellen-Spalten: (Key, Überschrift, Breite, Format)
COLUMNS = [
    ("rank", "#", 40, "int"),
    ("symbol", "Symbol", 90, "str"),
    ("name", "Unternehmen", 220, "str"),
    ("sector", "Sektor", 140, "str"),
    ("score", "Score", 60, "num"),
    ("value", "Value", 60, "num"),
    ("quality", "Qualität", 60, "num"),
    ("growth", "Wachstum", 65, "num"),
    ("coverage", "Abdeckung", 70, "num"),
    ("quarters", "Quartale", 60, "int"),
    ("earnings_yield", "Gewinnrend.", 80, "pct"),
    ("fcf_yield", "FCF-Rend.", 75, "pct"),
    ("return_on_equity", "ROE", 60, "pct"),
    ("debt_to_equity", "Schulden/EK", 80, "num"),
    ("revenue_growth", "Umsatz ±", 70, "pct"),
    ("last_quarter", "Letztes Q", 85, "str"),
]

DETAIL_FIELDS = [
    ("fiscal_date", "Quartal"), ("source", "Quelle"),
    ("revenue", "Umsatz"), ("gross_profit", "Bruttogewinn"),
    ("operating_income", "EBIT"), ("net_income", "Nettogewinn"),
    ("ebitda", "EBITDA"), ("eps", "EPS"),
    ("free_cashflow", "Free Cashflow"), ("total_equity", "Eigenkapital"),
    ("total_debt", "Schulden"), ("shares_outstanding", "Aktien"),
]


class ScreenerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("MarketScreener — Value-Investing-Analyse")
        root.geometry("1280x720")

        self.queue: queue.Queue = queue.Queue()
        self.cancel_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.result = None          # aktueller Ergebnis-DataFrame
        self.universe_key = None

        self._build_menu()
        self._build_toolbar()
        self._build_table()
        self._build_statusbar()
        self._poll_queue()

    # ------------------------------------------------------------ Aufbau

    def _build_menu(self) -> None:
        menu = tk.Menu(self.root)
        settings = tk.Menu(menu, tearoff=0)
        settings.add_command(label="FMP-API-Key eintragen …", command=self._edit_api_key)
        menu.add_cascade(label="Einstellungen", menu=settings)
        help_ = tk.Menu(menu, tearoff=0)
        help_.add_command(label="Analyse-Methodik (ANALYSE.md)",
                          command=lambda: webbrowser.open(ANALYSE_MD.as_uri()))
        menu.add_cascade(label="Hilfe", menu=help_)
        self.root.config(menu=menu)

    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self.root, padding=8)
        bar.pack(fill="x")

        ttk.Label(bar, text="Universum:").pack(side="left")
        self.labels = universe_labels()
        self.combo = ttk.Combobox(
            bar, state="readonly", width=28, values=list(self.labels.values())
        )
        self.combo.current(0)
        self.combo.pack(side="left", padx=(4, 12))

        self.btn_update = ttk.Button(
            bar, text="Daten aktualisieren + Analyse",
            command=lambda: self._start(update=True),
        )
        self.btn_update.pack(side="left", padx=2)
        self.btn_analyze = ttk.Button(
            bar, text="Nur Analyse (vorhandene Daten)",
            command=lambda: self._start(update=False),
        )
        self.btn_analyze.pack(side="left", padx=2)

        self.force_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="Cache ignorieren", variable=self.force_var).pack(
            side="left", padx=8
        )

        self.btn_cancel = ttk.Button(bar, text="Abbrechen", command=self._cancel,
                                     state="disabled")
        self.btn_cancel.pack(side="left", padx=2)

        self.progress = ttk.Progressbar(bar, length=220)
        self.progress.pack(side="right", padx=4)

    def _build_table(self) -> None:
        frame = ttk.Frame(self.root)
        frame.pack(fill="both", expand=True, padx=8)

        keys = [c[0] for c in COLUMNS]
        self.tree = ttk.Treeview(frame, columns=keys, show="headings")
        for key, heading, width, _fmt in COLUMNS:
            self.tree.heading(key, text=heading,
                              command=lambda k=key: self._sort_by(k))
            anchor = "w" if key in ("symbol", "name", "sector") else "e"
            self.tree.column(key, width=width, anchor=anchor, stretch=(key == "name"))

        ys = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        xs = ttk.Scrollbar(frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

        self.tree.bind("<Double-1>", self._show_detail)
        self._sort_state = ("score", True)

    def _build_statusbar(self) -> None:
        self.status = tk.StringVar(value="Bereit. Universum wählen und Analyse starten.")
        ttk.Label(self.root, textvariable=self.status, padding=(8, 4)).pack(
            fill="x", side="bottom"
        )

    # ------------------------------------------------------------ Ablauf

    def _selected_key(self) -> str:
        label = self.combo.get()
        return next(k for k, v in self.labels.items() if v == label)

    def _start(self, update: bool) -> None:
        if self.worker and self.worker.is_alive():
            return
        self.universe_key = self._selected_key()
        self.cancel_event.clear()
        self._set_running(True)
        self.worker = threading.Thread(
            target=self._run_pipeline,
            args=(self.universe_key, update, self.force_var.get()),
            daemon=True,
        )
        self.worker.start()

    def _cancel(self) -> None:
        self.cancel_event.set()
        self._status("Abbruch angefordert — laufendes Symbol wird noch beendet …")

    def _run_pipeline(self, key: str, update: bool, force: bool) -> None:
        """Läuft im Hintergrund-Thread; eigene DB-Verbindung (sqlite!)."""
        try:
            conn = db.connect()
            self._q("status", f"Lade Universum '{self.labels[key]}' …")
            universe = load_universe(key)
            symbols = list(universe["symbol"])
            self._q("status", f"{len(symbols)} Titel im Universum.")

            if update:
                stats = update_fundamentals(
                    universe, conn,
                    progress=lambda i, n, sym, st: self._q("progress", (i, n, sym, st)),
                    cancelled=self.cancel_event.is_set,
                    force=force,
                )
                note = (" — FMP-Tageslimit erreicht, Rest via Yahoo; morgen weiter"
                        if stats["fmp_limit"] else "")
                self._q("status",
                        f"Fundamentaldaten: {stats['updated']} aktualisiert, "
                        f"{stats['skipped']} frisch, {stats['failed']} ohne Daten{note}. "
                        f"Hole aktuelle Kurse …")
                if not self.cancel_event.is_set():
                    prices = update_prices(symbols, conn)
                    self._q("status", f"Kurse für {len(prices)} Titel aktualisiert. Berechne Scores …")

            result = score_universe(conn, symbols)
            if result.empty:
                self._q("error", "Keine bewertbaren Titel — erst 'Daten aktualisieren + Analyse' ausführen?")
                return

            names = universe.set_index("symbol")[["name", "sector"]]
            result = result.join(names, rsuffix="_u")

            run_id = db.save_score_run(conn, key, result)
            REPORTS_DIR.mkdir(exist_ok=True)
            csv_path = REPORTS_DIR / f"screener_{key}_{date.today().isoformat()}.csv"
            result.to_csv(csv_path)

            self._q("result", (result, f"Lauf #{run_id}: {len(result)} Titel bewertet. "
                                       f"CSV: {csv_path.name}"))
        except Exception:
            self._q("error", traceback.format_exc(limit=3))
        finally:
            self._q("done", None)

    # ------------------------------------------------------- Queue/Anzeige

    def _q(self, kind: str, payload) -> None:
        self.queue.put((kind, payload))

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "status":
                    self.status.set(payload)
                elif kind == "progress":
                    i, n, sym, st = payload
                    self.progress.configure(maximum=n, value=i)
                    self.status.set(f"[{i}/{n}] {sym}: {st}")
                elif kind == "result":
                    result, msg = payload
                    self.result = result
                    self._fill_table(result)
                    self.status.set(msg)
                elif kind == "error":
                    self.status.set("Fehler — Details im Dialog.")
                    messagebox.showerror("MarketScreener", str(payload))
                elif kind == "done":
                    self._set_running(False)
                    self.progress.configure(value=0)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    def _set_running(self, running: bool) -> None:
        state = "disabled" if running else "normal"
        self.btn_update.configure(state=state)
        self.btn_analyze.configure(state=state)
        self.combo.configure(state="disabled" if running else "readonly")
        self.btn_cancel.configure(state="normal" if running else "disabled")

    def _fill_table(self, result) -> None:
        self.tree.delete(*self.tree.get_children())
        for rank, (symbol, row) in enumerate(result.iterrows(), 1):
            values = []
            for key, _h, _w, fmt in COLUMNS:
                if key == "rank":
                    values.append(rank)
                elif key == "symbol":
                    values.append(symbol)
                else:
                    values.append(_format(row.get(key), fmt))
            self.tree.insert("", "end", iid=str(symbol), values=values)

    def _sort_by(self, key: str) -> None:
        if self.result is None or key == "rank":
            return
        prev_key, prev_desc = self._sort_state
        descending = not prev_desc if key == prev_key else True
        self._sort_state = (key, descending)
        if key == "symbol":
            sorted_df = self.result.sort_index(ascending=not descending)
        elif key in self.result.columns:
            sorted_df = self.result.sort_values(key, ascending=not descending,
                                                na_position="last")
        else:
            return
        self._fill_table(sorted_df)

    # ------------------------------------------------------------ Details

    def _show_detail(self, _event) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        symbol = selection[0]
        conn = db.connect()
        history = db.quarterly_history(conn, [symbol])
        conn.close()
        if history.empty:
            messagebox.showinfo("MarketScreener", f"Keine Quartalsdaten für {symbol}.")
            return

        win = tk.Toplevel(self.root)
        win.title(f"Quartals-Historie: {symbol}")
        win.geometry("980x420")

        keys = [f[0] for f in DETAIL_FIELDS]
        tree = ttk.Treeview(win, columns=keys, show="headings")
        for key, heading in DETAIL_FIELDS:
            tree.heading(key, text=heading)
            tree.column(key, width=110, anchor="e" if key not in ("fiscal_date", "source") else "w")
        ys = ttk.Scrollbar(win, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=ys.set)
        tree.pack(side="left", fill="both", expand=True)
        ys.pack(side="right", fill="y")

        for _, row in history.sort_values("fiscal_date", ascending=False).iterrows():
            values = []
            for key in keys:
                v = row.get(key)
                if key == "fiscal_date":
                    values.append(str(v)[:10])
                elif key == "source":
                    values.append(v)
                else:
                    values.append(_format_amount(v))
            tree.insert("", "end", values=values)

    # ------------------------------------------------------- Einstellungen

    def _edit_api_key(self) -> None:
        settings = load_settings()
        current = settings.get("fmp_api_key", "")
        hint = f" (aktuell: …{current[-4:]})" if current else " (aktuell: keiner)"
        key = simpledialog.askstring(
            "FMP-API-Key",
            "API-Key von financialmodelingprep.com" + hint + ":\n"
            "Leer lassen und OK = Key löschen.",
            parent=self.root,
        )
        if key is None:
            return
        settings["fmp_api_key"] = key.strip()
        save_settings(settings)
        self.status.set("FMP-API-Key gespeichert." if key.strip() else "FMP-API-Key entfernt.")

    def _status(self, text: str) -> None:
        self.status.set(text)


def _format(value, fmt: str) -> str:
    import math
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "–"
    if fmt == "pct":
        return f"{value * 100:.1f}%"
    if fmt == "num":
        return f"{value:.2f}" if isinstance(value, float) else str(value)
    if fmt == "int":
        return str(int(value))
    return str(value)


def _format_amount(value) -> str:
    import math
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "–"
    value = float(value)
    for divisor, unit in [(1e9, " Mrd"), (1e6, " Mio"), (1e3, " Tsd")]:
        if abs(value) >= divisor:
            return f"{value / divisor:,.2f}{unit}"
    return f"{value:,.2f}"


def main() -> None:
    root = tk.Tk()
    try:
        ttk.Style().theme_use("clam")
    except tk.TclError:
        pass
    ScreenerApp(root)
    root.mainloop()
