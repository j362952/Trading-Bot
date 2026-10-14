"""Wiederverwendbare Panels: Aktienquelle + Strategie-Liste mit Budgets.

Beide Seiten (TradeBot mit Profil "live", Backtest mit Profil "test")
nutzen dieselben Bausteine — nur das settings-Dict dahinter ist ein anderes.
"""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk

from ..strategies import STRATEGIES, STRATEGY_LABELS, param_fields
from .widgets import make_tree


class SourcePanel(ttk.LabelFrame):
    """Aktienquelle: Universum (Index/MSCI/Watchlist-Datei) oder manuelle Liste."""

    def __init__(self, parent, settings: dict, status=lambda m: None):
        super().__init__(parent, text="Aktienquelle", padding=8)
        self.settings = settings
        self.status = status

        from ..data.universe import universe_labels

        self.universe_labels = {"manual": "Manuelle Watchlist (unten)"}
        try:
            self.universe_labels.update(universe_labels())
        except Exception:
            pass
        current = settings.get("universe", "manual")
        self.universe_var = tk.StringVar(
            value=self.universe_labels.get(current, "Manuelle Watchlist (unten)"))
        top = ttk.Frame(self)
        top.pack(fill="x")
        ttk.Combobox(top, state="readonly", width=38, textvariable=self.universe_var,
                     values=list(self.universe_labels.values())).pack(side="left")
        ttk.Button(top, text="In Watchlist kopieren",
                   command=self._copy_universe).pack(side="left", padx=8)

        body = ttk.Frame(self)
        body.pack(fill="x", pady=(6, 0))
        self.watch_list = tk.Listbox(body, height=8, width=16)
        self.watch_list.pack(side="left")
        for s in settings.get("watchlist", []):
            self.watch_list.insert("end", s)
        col = ttk.Frame(body)
        col.pack(side="left", padx=6, anchor="n")
        self.watch_entry = ttk.Entry(col, width=10)
        self.watch_entry.pack()
        row = ttk.Frame(col)
        row.pack(pady=2)
        ttk.Button(row, text="+", width=3, command=self._add).pack(side="left", padx=2)
        ttk.Button(row, text="–", width=3, command=self._remove).pack(side="left")
        ttk.Label(col, wraplength=260, justify="left", text=(
            "Index gewählt = ALLE Titel des Index werden getrackt; die Watchlist "
            "gilt nur bei 'Manuelle Watchlist'.")).pack(pady=4)

    def universe_key(self) -> str:
        label = self.universe_var.get()
        return next((k for k, v in self.universe_labels.items() if v == label), "manual")

    def collect(self) -> None:
        self.settings["universe"] = self.universe_key()
        self.settings["watchlist"] = list(self.watch_list.get(0, "end"))

    def _add(self) -> None:
        symbol = self.watch_entry.get().strip().upper()
        if symbol and symbol not in self.watch_list.get(0, "end"):
            self.watch_list.insert("end", symbol)
            self.watch_entry.delete(0, "end")

    def _remove(self) -> None:
        for i in reversed(self.watch_list.curselection()):
            self.watch_list.delete(i)

    def _copy_universe(self) -> None:
        key = self.universe_key()
        if key == "manual":
            return

        def worker():
            try:
                from ..data.universe import load_universe

                symbols = list(load_universe(key)["symbol"])
                self.after(0, lambda: self._fill(symbols))
            except Exception as exc:
                self.after(0, lambda: messagebox.showerror("Universum", str(exc)))
        threading.Thread(target=worker, daemon=True).start()
        self.status(f"Lade Universum '{self.universe_var.get()}' …")

    def _fill(self, symbols: list[str]) -> None:
        self.watch_list.delete(0, "end")
        for s in symbols:
            self.watch_list.insert("end", s)
        self.status(f"{len(symbols)} Symbole in die Watchlist kopiert.")


class StrategyPanel(ttk.LabelFrame):
    """Strategien-Liste: mehrere parallel, je mit Parametern + Kapital-Budget."""

    def __init__(self, parent, settings: dict):
        super().__init__(parent, text="Strategie(n) — parallel mit Kapital-Budgets",
                         padding=8)
        self.settings = settings
        self.entries: list[dict] = list(settings.get("strategies") or [])
        if not self.entries:
            self.entries = [{"key": settings.get("strategy", "sma_cross"),
                             "params": settings.get("strategy_params", {}),
                             "budget": 1.0}]

        self.tree = make_tree(self, [("strategy", "Strategie", 260),
                                     ("budget", "Budget", 70),
                                     ("params", "Parameter", 260)],
                              height=4, stretch_col="params")
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=4)
        ttk.Button(bar, text="Hinzufügen", command=self._add).pack(side="left")
        ttk.Button(bar, text="Bearbeiten", command=self._edit).pack(side="left", padx=6)
        ttk.Button(bar, text="Entfernen", command=self._remove).pack(side="left")
        self.hint = ttk.Label(self, text="")
        self.hint.pack(anchor="w")
        self._refresh()

    # ------------------------------------------------------------- intern

    def _refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for e in self.entries:
            params = ", ".join(f"{k}={v}" for k, v in (e.get("params") or {}).items())
            self.tree.insert("", "end", values=(
                STRATEGY_LABELS.get(e["key"], e["key"]),
                f"{float(e.get('budget', 1.0)):.0%}", params or "(Defaults)"))
        total = sum(float(e.get("budget", 1.0)) for e in self.entries)
        self.hint.config(
            text=f"Budget-Summe: {total:.0%}" + ("  (über 100 % wird skaliert)"
                                                 if total > 1.0001 else ""),
            foreground="#c62828" if total > 1.0001 else "#333")

    def _selected_index(self) -> int | None:
        sel = self.tree.selection()
        if not sel:
            return None
        return self.tree.index(sel[0])

    def _add(self) -> None:
        _StrategyDialog(self, None, self._on_dialog_done)

    def _edit(self) -> None:
        i = self._selected_index()
        if i is not None:
            _StrategyDialog(self, self.entries[i], self._on_dialog_done, index=i)

    def _remove(self) -> None:
        i = self._selected_index()
        if i is not None and len(self.entries) > 1:
            self.entries.pop(i)
            self._refresh()

    def _on_dialog_done(self, entry: dict, index: int | None) -> None:
        if index is None:
            self.entries.append(entry)
        else:
            self.entries[index] = entry
        self._refresh()

    # -------------------------------------------------------------- API

    def collect(self) -> None:
        self.settings["strategies"] = self.entries
        # Einzelstrategie-Felder für Alt-Codepfade mitpflegen
        if self.entries:
            self.settings["strategy"] = self.entries[0]["key"]
            self.settings["strategy_params"] = self.entries[0].get("params", {})

    def selected_keys(self) -> list[str]:
        return [e["key"] for e in self.entries]


class _StrategyDialog(tk.Toplevel):
    def __init__(self, parent, entry: dict | None, on_done, index: int | None = None):
        super().__init__(parent)
        self.title("Strategie konfigurieren")
        self.on_done = on_done
        self.index = index
        self.transient(parent)
        self.grab_set()

        entry = entry or {"key": "momentum", "params": {}, "budget": 1.0}
        ttk.Label(self, text="Strategie:").pack(anchor="w", padx=10, pady=(10, 0))
        self.strat_var = tk.StringVar(value=STRATEGY_LABELS.get(entry["key"], ""))
        combo = ttk.Combobox(self, state="readonly", width=42, textvariable=self.strat_var,
                             values=list(STRATEGY_LABELS.values()))
        combo.pack(anchor="w", padx=10)
        combo.bind("<<ComboboxSelected>>", lambda e: self._rebuild_params({}))

        row = ttk.Frame(self)
        row.pack(anchor="w", padx=10, pady=6)
        ttk.Label(row, text="Kapital-Budget (0–1):").pack(side="left")
        self.budget_var = tk.StringVar(value=str(entry.get("budget", 1.0)))
        ttk.Entry(row, textvariable=self.budget_var, width=8).pack(side="left", padx=6)

        self.params_frame = ttk.LabelFrame(self, text="Parameter", padding=8)
        self.params_frame.pack(fill="x", padx=10, pady=6)
        self.param_vars: dict[str, tk.StringVar] = {}
        self._rebuild_params(entry.get("params", {}))

        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(bar, text="OK", command=self._ok).pack(side="right")
        ttk.Button(bar, text="Abbrechen", command=self.destroy).pack(side="right", padx=8)

    def _key(self) -> str:
        label = self.strat_var.get()
        return next((k for k, v in STRATEGY_LABELS.items() if v == label), "sma_cross")

    def _rebuild_params(self, overrides: dict) -> None:
        for child in self.params_frame.winfo_children():
            child.destroy()
        self.param_vars = {}
        for f in param_fields(STRATEGIES[self._key()]):
            row = ttk.Frame(self.params_frame)
            row.pack(anchor="w", pady=2)
            ttk.Label(row, text=f.name, width=18).pack(side="left")
            var = tk.StringVar(value=str(overrides.get(f.name, f.default)))
            ttk.Entry(row, textvariable=var, width=10).pack(side="left")
            self.param_vars[f.name] = var

    def _ok(self) -> None:
        try:
            budget = max(0.0, min(1.0, float(self.budget_var.get())))
        except ValueError:
            budget = 1.0
        entry = {"key": self._key(),
                 "params": {k: v.get() for k, v in self.param_vars.items()},
                 "budget": budget}
        self.on_done(entry, self.index)
        self.destroy()
